import gzip
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_player_career as scraper
from tm_career_checkpoints import Checkpoints
from collection_metadata import complete_attempt, start_attempt, read_metadata

EMPTY = {"performance": []}


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scraper._blocked.clear()
        scraper._budget_expired.clear()
        scraper._deadline = None
        self.addCleanup(setattr, scraper, "_deadline", None)
        self.addCleanup(scraper._blocked.clear)

    def scrape(self, store, ids, fetch):
        with patch.object(scraper, "fetch_player_career", side_effect=fetch), \
             patch.object(scraper, "_polite_pause"), patch.object(scraper, "_log"):
            return scraper.scrape_players({pid: {} for pid in ids}, 1, store)

    def test_interruption_resume_and_cross_league_dedup(self):
        store = Checkpoints(self.root, "campaign")
        calls = []
        def interrupted(pid):
            calls.append(pid)
            if pid == "2":
                raise KeyboardInterrupt()
            return EMPTY
        with self.assertRaises(KeyboardInterrupt):
            self.scrape(store, ["1", "2"], interrupted)
        resumed = Checkpoints(self.root, "campaign")
        def fetch(pid):
            calls.append(pid)
            return EMPTY
        result = self.scrape(resumed, ["1", "2"], fetch)
        self.assertEqual(result[-1], [])
        self.scrape(resumed, ["2", "3"], fetch)
        self.assertEqual(calls, ["1", "2", "2", "3"])
        stamp = resumed.get("1")["collected_at"]
        self.scrape(resumed, ["1"], lambda _: self.fail("duplicate GET"))
        self.assertEqual(resumed.get("1")["collected_at"], stamp)

    def test_new_campaign_refetches(self):
        Checkpoints(self.root, "old").put("1", EMPTY)
        calls = []
        self.scrape(Checkpoints(self.root, "new"), ["1"],
                    lambda pid: calls.append(pid) or EMPTY)
        self.assertEqual(calls, ["1"])

    def test_invalid_payload_and_corrupt_record_are_not_successes(self):
        store = Checkpoints(self.root, "c")
        for bad in (None, {}, [], {"performance": None},
                    {"performance": [{}]}, {"performance": ["bad"]}):
            result = self.scrape(store, ["1"], lambda _: bad)
            self.assertEqual(result[-1], ["1"])
            self.assertIsNone(store.get("1"))
        store.put("1", EMPTY)
        path = store.folder / "1.json"
        good = path.read_text()
        for key, value in (("version", 999), ("campaign", "other"),
                           ("player_id", "2"), ("collected_at", "bad")):
            record = json.loads(good)
            record[key] = value
            path.write_text(json.dumps(record))
            self.assertIsNone(store.get("1"))
        path.write_text("{")
        self.assertIsNone(store.get("1"))

    def test_atomic_replacement_retains_previous_valid_record(self):
        store = Checkpoints(self.root, "c")
        store.put("1", EMPTY)
        before = store.get("1")
        with patch("tm_career_checkpoints.os.replace", side_effect=OSError("disk")), \
             self.assertRaises(OSError):
            store.put("1", EMPTY)
        self.assertEqual(store.get("1"), before)

    def test_budget_reuses_cache_but_starts_no_missing_request(self):
        store = Checkpoints(self.root, "c")
        store.put("1", EMPTY)
        scraper._deadline = time.monotonic() - 1
        result = self.scrape(store, ["1", "2"], lambda _: self.fail("GET after budget"))
        self.assertEqual(result[-1], ["2"])
        self.assertTrue(scraper._budget_expired.is_set())

    def test_budget_cannot_be_increased(self):
        with patch.object(sys, "argv", ["scraper", "--budget-seconds", "241"]), \
             self.assertRaises(SystemExit) as raised:
            scraper.cli()
        self.assertEqual(raised.exception.code, 2)

    def test_partial_then_complete_export_and_cache_only_no_warmup(self):
        out = self.root / "out"
        out.mkdir()
        paths = [out / f"custom_{s}.csv" for s in
                 ("summary", "career", "matches", "competitions_seen")]
        for p in paths:
            p.write_text("old export\n")
        argv = ["scraper", "--player-ids", "1,2", "--campaign", "c",
                "--checkpoint-dir", str(self.root / "cp"), "--out-dir", str(out)]
        with patch.object(sys, "argv", argv), patch.object(scraper.tm_waf, "warm_up"), \
             patch.object(scraper, "_polite_pause"), patch.object(scraper, "_log"), \
             patch.object(scraper, "fetch_player_career",
                          side_effect=lambda pid: EMPTY if pid == "1" else None):
            with self.assertRaises(SystemExit):
                scraper.cli()
        self.assertTrue(all(p.read_text() == "old export\n" for p in paths))
        with patch.object(sys, "argv", argv), patch.object(scraper.tm_waf, "warm_up"), \
             patch.object(scraper, "_polite_pause"), patch.object(scraper, "_log"), \
             patch.object(scraper, "fetch_player_career", return_value=EMPTY) as fetch:
            scraper.cli()
            fetch.assert_called_once_with("2")
        with patch.object(sys, "argv", argv), patch.object(scraper, "_log"), \
             patch.object(scraper.tm_waf, "warm_up") as warm, \
             patch.object(scraper, "fetch_player_career") as fetch:
            scraper.cli()
            warm.assert_not_called()
            fetch.assert_not_called()

    def test_freshness_keeps_original_response_timestamp(self):
        store = Checkpoints(self.root / "cp", "c")
        store.put("1", EMPTY)
        record = store.get("1")
        record["collected_at"] = "2020-01-01T00:00:00+00:00"
        store._write(record)
        start_attempt(self.root, "x")
        with patch("collection_metadata.fingerprints", return_value={}):
            complete_attempt(self.root, "x", store.evidence(["1"]))
        success = read_metadata(self.root, "x")["last_success"]
        self.assertEqual(success["completed_at"], record["collected_at"])
        self.assertEqual(success["campaign"], "c")


class FakeGitHub:
    def __init__(self):
        self.created = False
        self.assets = {}
        self.fail_upload = False

    def gh(self, *args):
        if args[0] == "api":
            return json.dumps([[{"tag_name": "tm-checkpoints-c"}]] if self.created else [[]])
        command = args[1]
        if command == "create":
            self.created = True
        elif command == "view":
            return json.dumps({"assets": [{"name": n} for n in self.assets]})
        elif command == "download":
            folder = Path(args[args.index("--dir") + 1])
            for name, data in self.assets.items():
                (folder / name).write_bytes(data)
        elif command == "upload":
            if self.fail_upload:
                raise RuntimeError("upload failed")
            path = Path(args[3])
            self.assets[path.name] = path.read_bytes()
        elif command == "delete-asset":
            del self.assets[args[3]]
        return ""


class DurableTests(unittest.TestCase):
    def test_runner_disappearance_and_atomic_compaction(self):
        remote = FakeGitHub()
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new, \
             patch.object(Checkpoints, "_gh", side_effect=remote.gh):
            first = Checkpoints(old, "c", True)
            for i in range(25):
                first.put(str(i), EMPTY)
            self.assertEqual(len(remote.assets), 1)  # before end-of-job
            restored = Checkpoints(new, "c", True)
            self.assertTrue(all(restored.get(str(i)) for i in range(25)))
            # Interrupted compaction cannot delete the published journal.
            restored.assets *= 100
            restored.put("100", EMPTY)
            remote.fail_upload = True
            with self.assertRaises(RuntimeError):
                restored.flush()
            self.assertEqual(len(remote.assets), 1)
            remote.fail_upload = False
            # Use 100 distinct segments to exercise successful compaction.
            data = next(iter(remote.assets.values()))
            remote.assets = {f"{i}.jsonl.gz": data for i in range(100)}
            restored.assets = [{"name": n} for n in remote.assets]
            restored.flush()
            self.assertEqual(len(remote.assets), 1)
            rows = gzip.decompress(next(iter(remote.assets.values()))).splitlines()
            self.assertEqual(len(rows), 26)

    def test_failed_upload_local_success_republished_on_restart(self):
        remote = FakeGitHub()
        with tempfile.TemporaryDirectory() as root, \
             patch.object(Checkpoints, "_gh", side_effect=remote.gh):
            first = Checkpoints(root, "c", True)
            first.put("1", EMPTY)
            remote.fail_upload = True
            with self.assertRaises(RuntimeError):
                first.flush()
            remote.fail_upload = False
            second = Checkpoints(root, "c", True)
            self.assertIn("1", second.pending)
            second.flush()
            self.assertEqual(len(remote.assets), 1)


if __name__ == "__main__":
    unittest.main()
