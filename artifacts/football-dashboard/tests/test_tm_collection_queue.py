"""Offline only: no credentials, browser, source requests or real GitHub."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_collection_queue as q
from scripts import collection_queue as runner
import tm_player_career as career
import tm_league_scraper as squad


class Store:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.run_state = {"id": 1, "status": "completed", "conclusion": "failure"}
        self.fail = False

    def inventory(self):
        return [(1, copy.deepcopy(self.state))]

    def save(self, _, state):
        if self.fail:
            raise OSError("storage unavailable")
        self.state = copy.deepcopy(state)

    def run(self, _):
        return self.run_state


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, value in files.items():
            z.writestr(name, value)
    return out.getvalue()


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        clearance = Path(self.temp.name) / "access.json"
        clearance.write_text(json.dumps({
            "version": 1, "status": "reconciled",
            "resolution": "Synthetic operator reconciliation for offline tests",
            "reviewed_at": "2026-10-29T00:00:00+00:00",
        }))
        self.access_patch = patch.object(runner, "ACCESS_FILE", clearance)
        self.access_patch.start()
        self.addCleanup(self.access_patch.stop)
        self.state = q.new_campaign("c", ["l1", "fr1", "l1"], refresh=False)
        self.state["owner"] = "1"

    def test_first_weekly_run_without_queue_respects_historical_refusal(self):
        historical = Path(self.temp.name) / "historical-refusal.json"
        historical.write_text(json.dumps({
            "version": 1, "status": "suspended",
            "reason": "historical_captcha", "resolution": None, "reviewed_at": None,
        }))
        store = Mock()
        store.inventory.return_value = []  # historical run predates queue releases
        with patch.object(runner, "ACCESS_FILE", historical):
            for campaign in ("", "fresh-id", "legacy"):
                with self.assertRaisesRegex(RuntimeError, "Historical"):
                    runner.prepare(store, "new-weekly-run", campaign=campaign, create=True)
            with self.assertRaisesRegex(RuntimeError, "Historical"):
                runner.collect(store, 1, self.state, run=Mock())
        store.inventory.assert_not_called()
        store.create.assert_not_called()
        store.save.assert_not_called()

    def test_missing_corrupt_or_incomplete_clearance_fails_closed(self):
        for data in ("", "{}", '{"version":1,"status":"reconciled"}',
                     '{"version":1,"status":"suspended"}'):
            runner.ACCESS_FILE.write_text(data)
            with self.assertRaises(RuntimeError):
                runner.require_access_clearance()
        runner.ACCESS_FILE.unlink()
        with self.assertRaises(RuntimeError):
            runner.require_access_clearance()

    def test_squad_request_uses_official_case_not_queue_key(self):
        state = q.new_campaign("case-test", ["l1"], refresh=True)
        state["owner"] = "1"
        store = Store(state)
        run = Mock(return_value=Mock(returncode=1))
        with patch.object(runner, "select_leagues", return_value=[
                {"code_tm": "L1", "slug": "1-bundesliga"}]):
            runner.collect(store, 1, state, run=run)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--comp") + 1], "L1")
        self.assertTrue(command[command.index("--out") + 1].endswith("/l1.csv"))

    def test_backoff_bounded_and_no_duplicate_attempt(self):
        now = 0
        for attempt in range(q.MAX_ATTEMPTS):
            q.begin(self.state, "l1", now)
            with self.assertRaises(ValueError):
                q.begin(self.state, "l1", now)
            q.result(self.state, "l1", "budget_exhausted", now)
            self.assertNotIn("l1", q.due_codes(self.state, now))
            if attempt < q.MAX_ATTEMPTS - 1:
                now = self.state["leagues"]["l1"]["due"]
                self.assertIn("l1", q.due_codes(self.state, now))
        self.assertEqual(self.state["leagues"]["l1"]["state"], "exhausted")
        self.assertIn("fr1", q.due_codes(self.state, now))

    def test_partial_success_retained_after_temporary_failure(self):
        q.begin(self.state, "l1", 0)
        q.result(self.state, "l1", "success", 0)
        q.begin(self.state, "fr1", 0)
        q.result(self.state, "fr1", "temporary_network", 0)
        self.assertEqual(q.due_codes(self.state, 4000), ["fr1"])
        self.assertEqual(self.state["leagues"]["l1"]["state"], "collected")

    def test_refusal_suspends_all_future_work(self):
        q.begin(self.state, "l1", 0)
        q.result(self.state, "l1", "access_blocked", 0)
        self.assertEqual(q.due_codes(self.state, 999999), [])
        with self.assertRaises(RuntimeError):
            runner.prepare(Store(self.state), "2", create=True)

    def test_interruption_and_cancel_never_restart_source(self):
        for conclusion in ["failure", "cancelled", "timed_out"]:
            state = copy.deepcopy(self.state)
            q.begin(state, "l1", 0)
            store = Store(state)
            store.run_state["conclusion"] = conclusion
            self.assertIsNone(runner.prepare(store, "2"))
            self.assertEqual(store.state["status"], "suspended")

    def test_watcher_expiry_reattaches_to_running_run(self):
        store = Store(self.state)
        store.run_state["status"] = "in_progress"
        self.assertIsNone(runner.prepare(store, "2"))
        self.assertEqual(store.state["owner"], "1")
        self.assertEqual(store.state["leagues"]["l1"]["attempts"], 0)

    def test_completed_partial_run_continues_only_due_work(self):
        store = Store(self.state)
        q.begin(store.state, "l1", 0)
        q.result(store.state, "l1", "temporary_network", 0)
        with patch.object(runner.time, "time", return_value=4000):
            result = runner.prepare(store, "2")
        self.assertEqual(result[1]["owner"], "2")

    def test_unavailable_store_prevents_any_source_call(self):
        store = Store(self.state)
        store.fail = True
        with patch.object(runner.subprocess, "run") as process:
            with self.assertRaises(OSError):
                runner.collect(store, 1, self.state)
            process.assert_not_called()

    def test_unknown_campaign_and_same_run_cannot_restart(self):
        with self.assertRaises(RuntimeError):
            runner.prepare(Store(self.state), "2", campaign="legacy")
        self.assertIsNone(runner.prepare(Store(self.state), "1"))

    def test_two_public_archives_must_match_and_delayed_publish_no_scrape(self):
        item = self.state["leagues"]["l1"]
        files = {"a.csv": b"validated"}
        item.update(state="publishing", publication_started=0,
                    expected={kind: {"a.csv": q.digest(b"validated")}
                              for kind in ("all", "current")})
        q.verify_publication(self.state, lambda path: archive(
            files if "_all." in path else {"a.csv": b"old"}), 10)
        self.assertEqual(item["state"], "publishing")
        self.assertNotIn("l1", q.due_codes(self.state, 9999))
        q.verify_publication(self.state, lambda _: archive(files), 20)
        self.assertEqual(item["state"], "done")

    def test_publication_timeout_and_network_outage(self):
        item = self.state["leagues"]["l1"]
        item.update(state="publishing", publication_started=0,
                    expected={"all": {"a": "x"}, "current": {"b": "y"}})
        def down(_):
            raise OSError("offline")
        q.verify_publication(self.state, down, 1)
        self.assertEqual(item["state"], "publishing")
        q.verify_publication(self.state, down, q.PUBLICATION_LIMIT)
        self.assertEqual(self.state["status"], "suspended")

    def test_zip_duplicate_extra_or_corrupt_files_refused(self):
        self.assertFalse(q.zip_matches(b"invalid", {}))
        self.assertFalse(q.zip_matches(archive({"a": b"x", "b": b"y"}),
                                      {"a": q.digest(b"x")}))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("a", b"x")
            z.writestr("a", b"x")
        self.assertFalse(q.zip_matches(out.getvalue(), {"a": q.digest(b"x")}))

    def test_refusal_never_refreshes_career_or_squad_session(self):
        for status in (403, 405, 429):
            career._blocked.clear()
            squad._access_blocked.clear()
            with patch.object(career, "_fetch_json_once",
                              return_value=(None, status, "refused", True, None)), \
                 patch.object(career.tm_waf, "get_waf_token") as refresh:
                career._fetch_json("fake")
                refresh.assert_not_called()
                self.assertTrue(career._blocked.is_set())
            with patch.object(squad, "_fetch_once",
                              return_value=("", status, "refused", True, None)), \
                 patch.object(squad.tm_waf, "get_waf_token") as refresh:
                squad._fetch("fake")
                refresh.assert_not_called()
                self.assertTrue(squad._access_blocked.is_set())
        career._blocked.clear()
        squad._access_blocked.clear()

    def test_patch_preserves_draft_identity_and_requires_readback(self):
        store = q.GitHubStore()
        state = copy.deepcopy(self.state)
        old = json.dumps(state)
        def api(path, method="GET", data=None):
            if method == "PATCH":
                self.assertEqual(data["tag_name"], "tm-queue-c")
                self.assertTrue(data["draft"])
                return {}
            return {"body": old, "tag_name": "tm-queue-c", "draft": True}
        with patch.object(store, "api", side_effect=api):
            with self.assertRaises(RuntimeError):
                store.save(1, state)  # lost/stale write cannot authorize traffic

    def test_previous_47_archives_cannot_be_erased(self):
        tree = {"tree": [{"path": f"data/l{i}_{kind}.zip"}
                         for i in range(47) for kind in ("all", "current")]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            for entry in tree["tree"]:
                (root / entry["path"]).write_bytes(b"retained")
            q.guard_existing_archives(tree, root)
            (root / "data/l46_current.zip").unlink()
            with self.assertRaises(ValueError):
                q.guard_existing_archives(tree, root)
            with self.assertRaises(ValueError):
                q.guard_existing_archives({"truncated": True}, root)

    def test_seal_validates_both_exports_and_rejects_stale_current(self):
        from collection_metadata import start_attempt, complete_attempt
        from scripts.make_current_season import filter_csv_by_season
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full, current, build = [root / name for name in ("full", "current", "build")]
            for folder in (full, current, build):
                folder.mkdir()
            for suffix in ("summary", "career", "matches", "competitions_seen"):
                (full / f"l1_{suffix}.csv").write_text("season,value\n2025,old\n2026,new\n")
            for suffix in ("career", "matches"):
                filter_csv_by_season(full / f"l1_{suffix}.csv",
                                     current / f"l1_{suffix}.csv", 2026)
            start_attempt(full, "l1")
            complete_attempt(full, "l1", {"campaign": "c", "collected_from": "2026-01-01T00:00:00+00:00"})
            for kind, folder in (("all", full), ("current", current)):
                (build / f"l1_{kind}.zip").write_bytes(archive(
                    {p.name: p.read_bytes() for p in folder.glob("*.csv")}))
            self.state["leagues"]["l1"]["state"] = "collected"
            runner.seal(Store(self.state), 1, self.state, full, current, build)
            self.assertEqual(self.state["leagues"]["l1"]["state"], "publishing")
            self.state["leagues"]["l1"]["state"] = "collected"
            (current / "l1_career.csv").write_text("stale")
            with self.assertRaises(ValueError):
                runner.seal(Store(self.state), 1, self.state, full, current, build)

    def test_browser_refusal_is_shared_and_never_retried(self):
        waf = career.tm_waf
        waf._access_refused.clear()
        self.addCleanup(waf._access_refused.clear)
        with patch.object(waf, "_token", None), patch.object(waf, "_disabled", False), \
             patch.object(waf, "_gave_up", False), \
             patch.object(waf, "_launch_and_get_token",
                          side_effect=waf.AccessRefused("blocked")) as launch:
            for _ in range(2):
                with self.assertRaises(waf.AccessRefused):
                    waf.get_waf_token()
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
