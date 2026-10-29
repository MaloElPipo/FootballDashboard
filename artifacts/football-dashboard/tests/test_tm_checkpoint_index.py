import gzip
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_tm_career_checkpoints import FakeGitHub, EMPTY
from tm_career_checkpoints import Checkpoints


def record(pid, campaign="c", stamp="2020-01-01T00:00:00+00:00"):
    return dict(version=1, campaign=campaign, player_id=str(pid),
                collected_at=stamp, data=EMPTY)


def journal(*records):
    return gzip.compress("".join(json.dumps(r) + "\n" for r in records).encode())


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.remote = FakeGitHub()
        self.remote.created = True
        self.remote.assets = {"old.jsonl.gz": journal(record(1), record(2))}
        self.patch = patch.object(Checkpoints, "_gh", side_effect=self.remote.gh)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def store(self, root=None):
        return Checkpoints(root or self.tmp.name, "c", True)

    def test_repeat_skips_download_and_deleted_index_rebuilds(self):
        first = self.store()
        self.assertEqual(first.restore_downloads, 1)
        self.assertEqual(list(first.folder.glob("*.json")), [])
        second = self.store()
        self.assertEqual(second.restore_downloads, 0)
        self.assertEqual(second.restore_bytes, 0)
        self.assertEqual(second.get("2"), record(2))
        second.index.path.unlink()
        self.assertEqual(self.store().restore_downloads, 1)

    def test_only_new_asset_downloaded_and_original_dates_preserved(self):
        self.store()
        self.remote.assets["new.jsonl.gz"] = journal(record(3))
        second = self.store()
        self.assertEqual(second.restore_downloads, 1)
        self.assertEqual(second.restore_bytes, len(self.remote.assets["new.jsonl.gz"]))
        self.assertEqual(second.evidence(["1", "3"])["collected_from"],
                         record(1)["collected_at"])

    def test_interrupted_import_rolls_back_rows_and_receipt(self):
        self.remote.assets["old.jsonl.gz"] = gzip.compress(
            (json.dumps(record(1)) + "\ninvalid\n").encode())
        with self.assertRaises(ValueError):
            self.store()
        from tm_checkpoint_index import RemoteIndex
        index = RemoteIndex(Path(self.tmp.name) / "c")
        self.assertIsNone(index.get("1"))
        self.assertFalse(index.contains({"name": "old.jsonl.gz"}))
        self.remote.assets["old.jsonl.gz"] = journal(record(1), record(2))
        self.assertEqual(self.store().get("2"), record(2))

    def test_wrong_campaign_rejected(self):
        self.remote.assets["old.jsonl.gz"] = journal(record(1, campaign="other"))
        with self.assertRaises(ValueError):
            self.store()

    def test_process_death_during_transaction_replays_asset(self):
        code = """
import os, sys
from tm_checkpoint_index import RemoteIndex
index = RemoteIndex(__import__('pathlib').Path(sys.argv[1]))
def rows():
    yield dict(player_id="9", collected_at="2020", data={})
    os._exit(19)
index.ingest({"name": "killed.jsonl.gz"}, rows())
"""
        folder = Path(self.tmp.name) / "c"
        folder.mkdir()
        result = subprocess.run([sys.executable, "-c", code, str(folder)],
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 19)
        store = self.store()
        self.assertIsNone(store.get("9"))
        self.assertEqual(store.get("2"), record(2))
        self.assertFalse(store.index.contains({"name": "killed.jsonl.gz"}))

    def test_newest_remote_wins_even_if_older_asset_is_imported_last(self):
        newer = record(1, stamp="2021-01-01T00:00:00+00:00")
        self.remote.assets = {"new.jsonl.gz": journal(newer),
                              "old.jsonl.gz": journal(record(1))}
        store = self.store()
        store._write(record(1))
        self.assertEqual(store.get("1"), newer)
        resumed = self.store()
        self.assertNotIn("1", resumed.pending)

    def test_local_newer_response_and_unvisited_league_survive_compaction(self):
        store = self.store()
        store.put("1", EMPTY)
        newest = store.get("1")
        self.remote.assets = {f"{i}.jsonl.gz": journal(record(1), record(2))
                              for i in range(100)}
        store = self.store()
        store.flush()
        self.assertEqual(len(self.remote.assets), 1)
        with tempfile.TemporaryDirectory() as fresh:
            restored = self.store(fresh)
            self.assertEqual(restored.get("1"), newest)
            self.assertEqual(restored.get("2"), record(2))

    def test_crash_during_compaction_delete_is_replayable(self):
        self.remote.assets = {f"{i}.jsonl.gz": journal(record(1), record(2))
                              for i in range(100)}
        store = self.store()
        store.put("3", EMPTY)
        original = self.remote.gh
        def interrupted(*args):
            if args[:2] == ("release", "delete-asset"):
                raise OSError("crash after upload")
            return original(*args)
        with patch.object(Checkpoints, "_gh", side_effect=interrupted):
            with self.assertRaises(OSError):
                store.flush()
        with tempfile.TemporaryDirectory() as fresh:
            restored = self.store(fresh)
            self.assertTrue(all(restored.get(str(pid)) for pid in (1, 2, 3)))

    def test_remote_errors_not_hidden_by_warm_index(self):
        self.store()
        with patch.object(Checkpoints, "_gh", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                self.store()


if __name__ == "__main__":
    unittest.main()
