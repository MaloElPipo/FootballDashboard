"""Administration tests: fake GitHub and archives only, never source traffic."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_collection_queue as q
import tm_queue_admin as admin
from scripts import collection_queue as runner


class Store:
    def __init__(self):
        self.state = q.new_campaign("test", ["fr1"])
        self.state["owner"] = "123"
        q.begin(self.state, "fr1", 0)
        q.suspend(self.state, "interrupted_attempt")
        self.run_state = {"id": 123, "status": "completed", "conclusion": "cancelled"}
        self.writes = 0
        self.archives = {}
        self.other = []

    def inventory(self):
        return [(1, copy.deepcopy(self.state))] + copy.deepcopy(self.other)

    def run(self, run_id):
        return copy.deepcopy(self.run_state)

    def public_fetcher(self):
        return lambda path: self.archives[path]

    def save(self, rid, state):
        self.writes += 1
        self.state = copy.deepcopy(state)
        self.state["revision"] += 1


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def report(self, action="reconcile", ack=False):
        return admin.inspect(self.store, "test", action, "Operator decision", ack)

    def apply(self, report):
        return admin.apply(self.store, report, report["confirmation"], "999", now=100)

    def test_simulation_has_owner_attempts_reason_and_proofs_without_write(self):
        report = self.report()
        self.assertEqual(report["runs"]["123"]["conclusion"], "cancelled")
        self.assertEqual(report["queue"]["leagues"]["fr1"]["attempts"], 1)
        self.assertEqual(report["queue"]["reason"], "interrupted_attempt")
        self.assertEqual(report["public_proofs"]["fr1"]["all"]["status"],
                         "no_expected_fingerprints")
        admin.transition(report, 100, "simulation")
        self.assertEqual(self.store.writes, 0)
        self.assertEqual(self.store.state["leagues"]["fr1"]["state"], "running")

    def test_retry_keeps_consumed_attempt_and_backoff_and_audit(self):
        state = self.apply(self.report())
        item = state["leagues"]["fr1"]
        self.assertEqual(item["attempts"], 1)
        self.assertEqual(item["due"], 3700)
        self.assertEqual(q.due_codes(state, 3699), [])
        self.assertEqual(q.due_codes(state, 3700), ["fr1"])
        self.assertEqual(state["administration"][0]["previous_owner"], "123")
        self.assertEqual(state["last_owner"], "123")

    def test_no_reset_of_exhausted_attempts(self):
        self.store.state["leagues"]["fr1"]["attempts"] = 4
        state = self.apply(self.report())
        self.assertEqual(state["leagues"]["fr1"]["state"], "exhausted")
        self.assertEqual(state["leagues"]["fr1"]["attempts"], 4)
        self.assertEqual(q.due_codes(state, 999999), [])

    def test_close_is_not_success_and_does_not_reopen(self):
        before = copy.deepcopy(self.store.state["leagues"])
        state = self.apply(self.report("close"))
        self.assertEqual(state["status"], "closed")
        self.assertEqual(state["leagues"], before)
        with self.assertRaisesRegex(ValueError, "cannot be reopened"):
            self.apply(self.report())

    def test_live_uncertain_or_wrong_owner_never_mutates(self):
        for status, conclusion in [("in_progress", None), ("queued", None),
                                   ("completed", None)]:
            self.store.run_state.update(status=status, conclusion=conclusion)
            with self.assertRaises(ValueError):
                self.apply(self.report("close"))
        self.store.run_state["id"] = 456
        with self.assertRaises(ValueError):
            self.report()
        self.assertEqual(self.store.writes, 0)

    def test_cleared_owner_still_inspected(self):
        q.reconcile_owner(self.store.state, self.store.run_state)
        self.assertIsNone(self.store.state["owner"])
        self.assertIn("123", self.report()["runs"])

    def test_stale_confirmation_or_changed_state_never_mutates(self):
        report = self.report()
        with self.assertRaises(ValueError):
            admin.apply(self.store, report, "yes", "999")
        self.store.state["revision"] += 1
        with self.assertRaisesRegex(ValueError, "changed"):
            self.apply(report)
        self.assertEqual(self.store.writes, 0)

    def test_run_changed_after_inspection(self):
        report = self.report()
        self.store.run_state["status"] = "in_progress"
        with self.assertRaisesRegex(ValueError, "changed"):
            self.apply(report)

    def test_refusal_close_preserves_global_hold_until_explicit_decision(self):
        q.result(self.store.state, "fr1", "access_blocked", 0)
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            self.apply(self.report())
        state = self.apply(self.report("close"))
        self.assertTrue(state["access_hold"])
        with patch.object(runner, "require_access_clearance"):
            with self.assertRaisesRegex(RuntimeError, "suspended"):
                runner.prepare(self.store, "999", create=True)
        state = self.apply(self.report(ack=True))
        self.assertEqual(state["status"], "closed")
        self.assertFalse(state["access_hold"])
        self.assertEqual(state["leagues"]["fr1"]["attempts"], 1)
        # Administration never changes the separate migration latch.
        with tempfile.TemporaryDirectory() as tmp:
            latch = Path(tmp) / "access.json"
            latch.write_text('{"version":1,"status":"suspended"}')
            with patch.object(runner, "ACCESS_FILE", latch):
                with self.assertRaisesRegex(RuntimeError, "Historical"):
                    runner.require_access_clearance()

    def test_explicit_refusal_reconciliation_does_not_collect(self):
        q.result(self.store.state, "fr1", "access_blocked", 0)
        state = self.apply(self.report(ack=True))
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["leagues"]["fr1"]["attempts"], 1)
        self.assertEqual(q.due_codes(state, 100), [])

    def test_publication_cannot_clear_source_hold(self):
        self.prepare_publication()
        item = self.store.state["leagues"]["fr1"]
        item.update(state="publishing", publication_started=0)
        q.suspend(self.store.state, "access_blocked")
        q.verify_publication(self.store.state, self.store.public_fetcher(), 100)
        self.assertEqual(self.store.state["status"], "complete")
        self.assertTrue(self.store.state["access_hold"])
        with patch.object(runner, "require_access_clearance"):
            with self.assertRaises(RuntimeError):
                runner.prepare(self.store, "999", create=True)
        state = self.apply(self.report(ack=True))
        self.assertEqual(state["status"], "complete")
        self.assertFalse(state["access_hold"])

    def test_other_campaign_and_missing_resolution_fail_closed(self):
        self.store.other = [(2, q.new_campaign("other", ["l1"]))]
        with self.assertRaisesRegex(ValueError, "Another"):
            self.apply(self.report())
        self.store.other = []
        report = admin.inspect(self.store, "test", "close", "")
        with self.assertRaisesRegex(ValueError, "resolution"):
            self.apply(report)

    def prepare_publication(self):
        item = self.store.state["leagues"]["fr1"]
        item.update(state="suspended", reason="publication_timeout", expected={})
        for kind in ("all", "current"):
            files = {"fr1_career.csv": b"season,goals\n2026,2\n"}
            item["expected"][kind] = {n: q.digest(b) for n, b in files.items()}
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as archive:
                for n, b in files.items():
                    archive.writestr(n, b)
            self.store.archives[f"data/fr1_{kind}.zip"] = out.getvalue()

    def test_exact_public_proofs_reconcile_timeout_without_recollecting(self):
        self.prepare_publication()
        state = self.apply(self.report())
        self.assertEqual(state["status"], "complete")
        self.assertEqual(state["leagues"]["fr1"]["attempts"], 1)

    def test_missing_mismatched_and_changed_public_evidence(self):
        self.prepare_publication()
        report = self.report()
        self.store.archives["data/fr1_all.zip"] = b"bad archive"
        with self.assertRaisesRegex(ValueError, "changed"):
            self.apply(report)
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.apply(self.report())
        del self.store.archives["data/fr1_all.zip"]
        self.assertEqual(self.report()["public_proofs"]["fr1"]["all"]["status"],
                         "unavailable")
        with self.assertRaises(ValueError):
            self.apply(self.report())
        self.assertEqual(self.store.writes, 0)

    def test_failed_save_propagates_without_retry(self):
        with patch.object(self.store, "save", side_effect=RuntimeError("not confirmed")) as save:
            with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                self.apply(self.report())
            save.assert_called_once()

    def test_cli_default_read_only_and_local_confirmation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ["admin", "--campaign", "test", "--resolution", "Operator decision",
                    "--output", str(Path(tmp) / "report.json")]
            with patch.object(admin, "GitHubStore", return_value=self.store), \
                    patch.object(sys, "argv", args), patch("builtins.print"):
                admin.main()
            report = json.loads((Path(tmp) / "report.json").read_text())
            self.assertEqual(self.store.writes, 0)
            with patch.object(admin, "GitHubStore", return_value=self.store), \
                    patch.object(sys, "argv", args + ["--confirm", report["confirmation"]]), \
                    patch.dict("os.environ", {}, clear=True), patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "locked"):
                    admin.main()
            self.assertEqual(self.store.writes, 0)

    def test_workflow_uses_collector_lock_and_no_collection_commands(self):
        root = Path(__file__).resolve().parents[3]
        workflow = (root / ".github/workflows/tm-queue-admin.yml").read_text()
        collector = (root / ".github/workflows/scrape-weekly.yml").read_text()
        for text in (workflow, collector):
            self.assertIn("group: scrape-weekly", text)
            self.assertIn("cancel-in-progress: false", text)
        self.assertNotIn("playwright", workflow)
        self.assertNotIn("collection_queue.py collect", workflow)


if __name__ == "__main__":
    unittest.main()
