import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_checkpoint_retention as retention
from tm_career_checkpoints import Checkpoints

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)
OLD = "2026-01-01T00:00:00Z"


def release(i, closed=True):
    return {
        "id": i, "tag_name": f"tm-checkpoints-c{i}", "draft": True,
        "created_at": f"2026-02-{i:02d}T00:00:00Z", "updated_at": OLD,
        "body": retention.CLOSED_MARKER + json.dumps({
            "closed_at": OLD, "no_resume_needed": True, "reason": "exports verified"
        }) if closed else "Private collection checkpoints",
        "assets": [{"id": i * 10, "name": "batch.jsonl.gz", "size": 123,
                    "created_at": OLD, "updated_at": OLD}],
    }


class FakeGitHub:
    repo = "owner/repo"

    def __init__(self, releases):
        self.data = releases
        self.calls = []
        self.blocked = False

    def releases(self):
        return copy.deepcopy(self.data)

    def require_maintenance_lock(self):
        if self.blocked:
            raise RuntimeError("active")

    def api(self, path, method, payload=None):
        self.calls.append((path, method, payload))
        rid = int(path.split("/")[-1])
        if method == "DELETE":
            self.data = [r for r in self.data if r["id"] != rid]
        else:
            next(r for r in self.data if r["id"] == rid).update(payload)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.data = [release(i) for i in range(1, 6)]

    def report(self):
        return retention.inventory(self.data, "owner/repo", NOW)

    def test_empty_inventory(self):
        report = retention.inventory([], "owner/repo", NOW)
        self.assertEqual(report["total_bytes"], 0)
        self.assertEqual(report["delete_count"], 0)

    def test_keep_three_and_count_all_bytes(self):
        report = self.report()
        self.assertEqual(report["delete_count"], 2)
        self.assertEqual(report["total_bytes"], 615)
        self.assertEqual(report["reclaimable_bytes"], 246)
        self.assertEqual([r["id"] for r in report["campaigns"] if r["delete"]], [2, 1])

    def test_resumable_old_campaign_is_never_candidate(self):
        self.data[0] = release(1, closed=False)
        row = self.report()["campaigns"][-1]
        self.assertFalse(row["delete"])
        self.assertEqual(row["reason"], "resumable-or-unknown")

    def test_corrupt_or_ambiguous_closure_protected(self):
        for body in (retention.CLOSED_MARKER + "{",
                     self.data[0]["body"] + "\n" + self.data[0]["body"],
                     retention.CLOSED_MARKER + '{"no_resume_needed":false}'):
            with self.subTest(body=body):
                self.data[0]["body"] = body
                self.assertFalse(self.report()["campaigns"][-1]["delete"])

    def test_public_release_never_deleted(self):
        self.data[0]["draft"] = False
        self.assertEqual(self.report()["campaigns"][-1]["reason"], "not-draft")

    def test_recent_closure_release_or_asset_protected(self):
        recent = "2026-10-20T00:00:00Z"
        for target in ("closure", "release", "asset"):
            with self.subTest(target=target):
                self.data[0] = release(1)
                if target == "closure":
                    c = retention.closure(self.data[0]["body"])
                    c["closed_at"] = recent
                    self.data[0]["body"] = retention.CLOSED_MARKER + json.dumps(c)
                elif target == "release":
                    self.data[0]["updated_at"] = recent
                else:
                    self.data[0]["assets"][0]["updated_at"] = recent
                self.assertFalse(self.report()["campaigns"][-1]["delete"])

    def test_invalid_timestamp_aborts_inventory(self):
        self.data[0]["updated_at"] = "unknown"
        with self.assertRaises(ValueError):
            self.report()

    def test_confirmation_binds_repository_assets_and_policy(self):
        original = self.report()["confirmation"]
        self.data[0]["assets"][0]["size"] += 1
        self.assertNotEqual(original, self.report()["confirmation"])
        self.assertNotEqual(self.report()["confirmation"],
                            retention.inventory(self.data, "other/repo", NOW)["confirmation"])

    def test_apply_only_confirmed_candidates(self):
        gh = FakeGitHub(self.data)
        confirmation = retention.inventory(gh.releases(), gh.repo)["confirmation"]
        retention.apply_plan(gh, confirmation)
        self.assertEqual([r["id"] for r in gh.data], [3, 4, 5])
        self.assertTrue(all(c[1] == "DELETE" for c in gh.calls))

    def test_stale_or_missing_confirmation_does_not_delete(self):
        gh = FakeGitHub(self.data)
        confirmation = retention.inventory(gh.releases(), gh.repo)["confirmation"]
        gh.data[0]["assets"][0]["size"] += 1
        for value in ("", confirmation):
            with self.assertRaises(ValueError):
                retention.apply_plan(gh, value)
        self.assertEqual(gh.calls, [])

    def test_active_run_blocks_close_and_apply(self):
        gh = FakeGitHub(self.data)
        gh.blocked = True
        with self.assertRaises(RuntimeError):
            retention.apply_plan(gh, "")
        with self.assertRaises(RuntimeError):
            retention.close_campaign(gh, "c1", "reason", "CLOSE-c1")
        self.assertEqual(gh.calls, [])

    def test_change_between_simulation_and_delete_stops(self):
        gh = FakeGitHub(self.data)
        confirmation = retention.inventory(gh.releases(), gh.repo)["confirmation"]
        calls = 0
        def snapshots():
            nonlocal calls
            calls += 1
            if calls > 1:
                gh.data[1]["assets"][0]["size"] += 1
            return copy.deepcopy(gh.data)
        gh.releases = snapshots
        with self.assertRaises(RuntimeError):
            retention.apply_plan(gh, confirmation)
        self.assertEqual(gh.calls, [])

    def test_delete_failure_stops_without_further_deletes(self):
        gh = FakeGitHub(self.data)
        confirmation = retention.inventory(gh.releases(), gh.repo)["confirmation"]
        with patch.object(gh, "api", side_effect=RuntimeError("network")) as api:
            with self.assertRaises(RuntimeError):
                retention.apply_plan(gh, confirmation)
        self.assertEqual(api.call_count, 1)

    def test_close_requires_confirmation_reason_and_existing_draft(self):
        gh = FakeGitHub([release(1, False)])
        for campaign, reason, confirm in (("c1", "reason", ""), ("c1", "", "CLOSE-c1"),
                                          ("missing", "reason", "CLOSE-missing")):
            with self.assertRaises(ValueError):
                retention.close_campaign(gh, campaign, reason, confirm)
        self.assertEqual(gh.calls, [])
        retention.close_campaign(gh, "c1", "no further resume needed", "CLOSE-c1")
        self.assertTrue(retention.closure(gh.data[0]["body"])["no_resume_needed"])
        with self.assertRaises(ValueError):
            retention.close_campaign(gh, "c1", "reset age", "CLOSE-c1")

    def test_closed_remote_campaign_cannot_resume(self):
        with tempfile.TemporaryDirectory() as root, \
                patch.object(Checkpoints, "_gh", return_value=json.dumps([[release(1)]])):
            with self.assertRaisesRegex(RuntimeError, "explicitly closed"):
                Checkpoints(root, "c1", remote=True)

    def test_mutations_refused_outside_maintenance_workflow(self):
        gh = retention.GitHub("owner/repo")
        with patch.dict("os.environ", {}, clear=True), \
                self.assertRaises(RuntimeError):
            gh.require_maintenance_lock()

    def test_assets_and_releases_are_paginated(self):
        gh = retention.GitHub("owner/repo")
        r = release(1)
        with patch.object(gh, "api", side_effect=[
                [[r], [release(2)]], [[r["assets"][0]], [dict(r["assets"][0], id=99)]],
                [[]]]) as api:
            result = gh.releases()
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]["assets"]), 2)
        self.assertTrue(all(c.kwargs["paginate"] for c in api.call_args_list))

    def test_actions_failure_is_not_treated_as_no_activity(self):
        gh = retention.GitHub("owner/repo")
        with patch.object(gh, "api", side_effect=RuntimeError("permissions")), \
                self.assertRaises(RuntimeError):
            gh.active_runs()


if __name__ == "__main__":
    unittest.main()
