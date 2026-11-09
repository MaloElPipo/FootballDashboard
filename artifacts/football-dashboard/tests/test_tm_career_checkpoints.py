import gzip
import fnmatch
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_career_checkpoints as module
import tm_player_career as scraper
from tm_career_checkpoints import Checkpoints, CheckpointStorageError
from collection_metadata import complete_attempt, fail_attempt, start_attempt, read_metadata

EMPTY = {"performance": []}


class CheckpointTests(unittest.TestCase):
    def test_github_read_retries_without_retrying_writes(self):
        import subprocess
        import tm_career_checkpoints as module
        with tempfile.TemporaryDirectory() as root:
            store = Checkpoints(root, "retry")
            failure = subprocess.CalledProcessError(1, ["gh"])
            with patch.object(module.subprocess, "run", side_effect=[
                    failure, subprocess.CompletedProcess([], 0, stdout="ok")]) as run, \
                 patch.object(module.time, "sleep") as sleep:
                self.assertEqual(store._gh("release", "download", "tag", "--dir", "/tmp/test"), "ok")
                sleep.assert_called_once_with(120)
                self.assertIn("--clobber", run.call_args.args[0])
            with patch.object(module.subprocess, "run", side_effect=failure) as run, \
                 patch.object(module.time, "sleep") as sleep:
                with self.assertRaises(subprocess.CalledProcessError):
                    store._gh("release", "upload", "tag", "file")
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_bounded_manual_compaction_threshold(self):
        import os
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"TM_CHECKPOINT_COMPACT_AFTER": "900"}):
                store = Checkpoints(root, "threshold")
            self.assertEqual(store.compact_after, 900)
            store.remote = True
            store.assets = [{"name": f"{i}.jsonl.gz"} for i in range(100)]
            store.pending = {"1": {"data": EMPTY}}
            with patch.object(store, "_gh") as gh, patch.object(
                    store, "_all_records", side_effect=AssertionError("Unexpected full compaction")):
                store.flush()
            self.assertEqual(gh.call_count, 1)
            self.assertEqual(gh.call_args.args[:2], ("release", "upload"))
            self.assertEqual(len(store.assets), 101)
            for value in ("99", "901", "invalid"):
                with patch.dict(os.environ, {"TM_CHECKPOINT_COMPACT_AFTER": value}):
                    with self.assertRaises(ValueError):
                        Checkpoints(root, "threshold")

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

    def test_budget_cannot_exceed_manual_cap(self):
        with patch.object(sys, "argv", ["scraper", "--budget-seconds", "1201"]), \
             self.assertRaises(SystemExit) as raised:
            scraper.cli()
        self.assertEqual(raised.exception.code, 2)

    def test_slow_local_inventory_does_not_exhaust_source_budget(self):
        clock = [0.0]
        original = Checkpoints.get
        def slow_get(store, pid):
            clock[0] = max(clock[0], 300.0)
            return original(store, pid)
        argv = ["scraper", "--player-ids", "1", "--campaign", "c",
                "--checkpoint-dir", str(self.root / "cp"),
                "--out-dir", str(self.root / "out")]
        with patch.object(sys, "argv", argv), \
             patch("time.monotonic", side_effect=lambda: clock[0]), \
             patch.object(Checkpoints, "get", slow_get), \
             patch.object(scraper.tm_waf, "warm_up"), \
             patch.object(scraper, "_polite_pause"), \
             patch.object(scraper, "_log"), \
             patch.object(scraper, "fetch_player_career", return_value=EMPTY) as fetch:
            scraper.cli()
            fetch.assert_called_once_with("1")

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
                if fnmatch.fnmatchcase(name, args[args.index("--pattern") + 1]):
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
    def test_restored_responses_do_not_fsync_but_new_ones_do(self):
        remote = FakeGitHub()
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new, \
             patch.object(Checkpoints, "_gh", side_effect=remote.gh):
            first = Checkpoints(old, "c", True)
            first.put("1", EMPTY)
            first.flush()
            with patch("tm_career_checkpoints.os.fsync") as sync:
                restored = Checkpoints(new, "c", True)
                self.assertEqual(restored.get("1"), first.get("1"))
                sync.assert_not_called()
                restored.put("2", EMPTY)
                self.assertEqual(sync.call_count, 2)

    def test_failed_restore_does_not_delete_remote_journal(self):
        remote = FakeGitHub()
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new, \
             patch.object(Checkpoints, "_gh", side_effect=remote.gh):
            first = Checkpoints(old, "c", True)
            first.put("1", EMPTY)
            first.flush()
            before = dict(remote.assets)
            with patch("tm_career_checkpoints.RemoteIndex.ingest", side_effect=OSError("disk")), \
                 self.assertRaises(OSError):
                Checkpoints(new, "c", True)
            self.assertEqual(remote.assets, before)
            restored = Checkpoints(new, "c", True)
            self.assertEqual(restored.get("1"), first.get("1"))

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


class FlakyGitHub(FakeGitHub):
    """The next ``failures`` uploads fail, then storage works again."""
    def __init__(self, failures=0):
        super().__init__()
        self.failures = failures

    def gh(self, *args):
        if len(args) > 1 and args[1] == "upload" and self.failures:
            self.failures -= 1
            raise RuntimeError("upload failed")
        return super().gh(*args)


class StorageOutageTests(unittest.TestCase):
    """A short GitHub failure must not stop a collection; a long one fails closed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = [100.0]
        scraper._blocked.clear()
        scraper._budget_expired.clear()
        scraper._deadline = None
        self.addCleanup(setattr, scraper, "_deadline", None)
        self.addCleanup(scraper._blocked.clear)

    def start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def open(self, remote, tolerance=None):
        self.start(patch.object(Checkpoints, "_gh", side_effect=remote.gh))
        env = {} if tolerance is None else {"TM_CHECKPOINT_OUTAGE_SECONDS": str(tolerance)}
        with patch.dict(os.environ, env):
            return Checkpoints(self.root / "cp", "c", True)

    def freeze_clock(self):
        self.start(patch("time.monotonic", side_effect=lambda: self.clock[0]))

    def scrape(self, store, ids, fetch):
        with patch.object(scraper, "fetch_player_career", side_effect=fetch), \
             patch.object(scraper, "_polite_pause"), patch.object(scraper, "_log"):
            return scraper.scrape_players({pid: {} for pid in ids}, 1, store)

    def test_transient_failure_keeps_records_and_resends_after_backoff(self):
        remote = FakeGitHub()
        self.freeze_clock()
        store = self.open(remote)
        store.put("1", EMPTY)
        remote.fail_upload = True
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(store.try_flush())           # tolerated: no exception
        self.assertEqual(set(store.pending), {"1"})       # nothing lost
        self.assertIsNone(store.error)
        self.assertIn('"event": "flush_failed"', out.getvalue())
        remote.fail_upload = False
        self.assertFalse(store.try_flush())               # backing off: no attempt yet
        self.assertEqual(remote.assets, {})
        self.clock[0] += module.FLUSH_SECONDS + 1
        with redirect_stdout(out):
            self.assertTrue(store.try_flush())
        self.assertEqual(len(remote.assets), 1)
        self.assertEqual(store.pending, {})
        self.assertIsNone(store.failing_since)
        self.assertIn('"event": "flush_recovered"', out.getvalue())

    def test_outage_longer_than_the_tolerance_fails_closed(self):
        remote = FakeGitHub()
        self.freeze_clock()
        store = self.open(remote, tolerance=60)
        store.put("1", EMPTY)
        remote.fail_upload = True
        with redirect_stdout(io.StringIO()):
            self.assertFalse(store.try_flush())           # first failure
            self.clock[0] += 30
            self.assertFalse(store.try_flush())           # 30 s outage: tolerated
            self.clock[0] += 31
            with self.assertRaises(CheckpointStorageError):
                store.try_flush()                         # 61 s outage
        self.assertIsNotNone(store.error)
        with self.assertRaises(CheckpointStorageError):
            store.put("2", EMPTY)                         # no more source traffic
        self.assertTrue((store.folder / "1.json").exists())   # still durable on disk

    def test_zero_tolerance_restores_the_strict_behaviour(self):
        remote = FakeGitHub()
        store = self.open(remote, tolerance=0)
        store.put("1", EMPTY)
        remote.fail_upload = True
        with redirect_stdout(io.StringIO()), self.assertRaises(CheckpointStorageError):
            store.try_flush()

    def test_outage_setting_is_bounded(self):
        for value in ("-1", "901", "soon"):
            with patch.dict(os.environ, {"TM_CHECKPOINT_OUTAGE_SECONDS": value}), \
                 self.assertRaises(ValueError):
                Checkpoints(self.root / "bounds", "c")

    def test_periodic_flush_keeps_trying_until_the_outage_is_permanent(self):
        store = Checkpoints(self.root / "periodic", "c")
        store.remote = True
        outcomes = iter([False, True, CheckpointStorageError("down")])
        def try_flush():
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.start(patch.object(module, "FLUSH_SECONDS", 0.01))
        with patch.object(store, "try_flush", side_effect=try_flush) as flush:
            with store.periodic_flush():
                deadline = time.time() + 5
                while flush.call_count < 3 and time.time() < deadline:
                    time.sleep(0.01)
            self.assertEqual(flush.call_count, 3)        # a failed tick did not stop it

    def test_final_flush_retries_then_fails_closed_and_recovers(self):
        remote = FlakyGitHub(failures=2)
        store = self.open(remote)
        store.put("1", EMPTY)
        with patch("time.sleep") as sleep, redirect_stdout(io.StringIO()):
            store.final_flush()                           # third attempt succeeds
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [20, 40])
        self.assertEqual(len(remote.assets), 1)
        remote.failures = 99
        store.put("2", EMPTY)
        with patch("time.sleep"), redirect_stdout(io.StringIO()), \
             self.assertRaises(CheckpointStorageError):
            store.final_flush()
        self.assertIn("2", store.pending)
        self.assertTrue((store.folder / "2.json").exists())
        remote.failures = 0
        store.final_flush()                               # storage is back: nothing lost
        self.assertEqual(len(remote.assets), 2)

    def test_gh_failure_is_logged_with_githubs_message_but_never_the_arguments(self):
        store = Checkpoints(self.root / "log", "c")
        refused = subprocess.CalledProcessError(1, ["gh"], stderr="HTTP 502: Bad Gateway\n")
        for error, expected in ((refused, "HTTP 502: Bad Gateway"),
                                (subprocess.TimeoutExpired(["gh"], 60), "timeout after 60s")):
            out = io.StringIO()
            with patch.object(module.subprocess, "run", side_effect=error), \
                 redirect_stdout(out), self.assertRaises(type(error)):
                store._gh("release", "upload", "tag", "/private/asset-path")
            line = out.getvalue()
            self.assertIn('"event": "gh_error"', line)
            self.assertIn("release upload", line)
            self.assertIn(expected, line)
            self.assertNotIn("asset-path", line)

    def test_transient_outage_neither_fails_players_nor_stops_the_collection(self):
        remote = FakeGitHub()
        store = self.open(remote)
        ids = [str(i) for i in range(1, 31)]
        remote.fail_upload = True                         # the flush at record 25 fails
        with redirect_stdout(io.StringIO()):
            result = self.scrape(store, ids, lambda _: EMPTY)
        self.assertEqual(result[-1], [])                  # not a single player failed
        self.assertIsNone(store.error)
        remote.fail_upload = False
        store.final_flush()
        rows = sum(len(gzip.decompress(data).splitlines()) for data in remote.assets.values())
        self.assertEqual(rows, 30)                        # every response is durable

    def test_permanent_outage_stops_source_requests(self):
        remote = FakeGitHub()
        store = self.open(remote, tolerance=0)
        remote.fail_upload = True
        calls = []
        def fetch(pid):
            calls.append(pid)
            return EMPTY
        with redirect_stdout(io.StringIO()), self.assertRaises(CheckpointStorageError):
            self.scrape(store, [str(i) for i in range(1, 41)], fetch)
        self.assertEqual(len(calls), 25)                  # nothing asked after it gave up

    def test_storage_outage_has_its_own_exit_code(self):
        self.assertEqual(scraper.STORAGE_EXIT_CODE, 78)
        with patch.object(scraper, "cli", side_effect=CheckpointStorageError("down")), \
             patch.object(scraper, "_log"), self.assertRaises(SystemExit) as raised:
            scraper.main()
        self.assertEqual(raised.exception.code, 78)

    def test_final_flush_outage_after_a_complete_scrape_exits_78_without_export(self):
        remote = FakeGitHub()
        remote.fail_upload = True
        self.start(patch.object(Checkpoints, "_gh", side_effect=remote.gh))
        argv = ["scraper", "--player-ids", "1", "--campaign", "c",
                "--checkpoint-dir", str(self.root / "cp"), "--out-dir", str(self.root / "out"),
                "--checkpoint-remote"]
        with patch.object(sys, "argv", argv), patch("time.sleep"), \
             patch.object(scraper.tm_waf, "warm_up"), patch.object(scraper, "_polite_pause"), \
             patch.object(scraper, "_log"), \
             patch.object(scraper, "fetch_player_career", return_value=EMPTY), \
             redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            scraper.main()
        self.assertEqual(raised.exception.code, 78)
        self.assertEqual(list(self.root.glob("out/*.csv")), [])   # no partial export

    def test_storage_outage_is_a_recordable_failure_reason(self):
        start_attempt(self.root, "x")
        fail_attempt(self.root, "x", "checkpoint_storage")
        self.assertEqual(read_metadata(self.root, "x")["last_attempt"]["reason"],
                         "checkpoint_storage")


if __name__ == "__main__":
    unittest.main()
