"""Current-season byte compatibility and offline write/crash fault injection."""
import errno
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import career_export_transaction as exports
from scripts import make_current_season as current, build_pages


class CurrentSeasonTransactionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src, self.out = self.root / "src", self.root / "current"
        self.src.mkdir()
        self.out.mkdir()
        self.names = ["fr1_career.csv", "fr1_matches.csv"]
        self.old = {name: b"season,name\r\n2025,Old\r\n" for name in self.names}
        self.expected = {
            name: 'season,name\r\n2026,"Éric, ""Test""\nSuite"\r\n'.encode()
            for name in self.names
        }
        for name in self.names:
            (self.out / name).write_bytes(self.old[name])
            (self.src / name).write_bytes(self.expected[name] + b"2025,Other\r\n")
        for key, value in (("SRC_DIR", self.src), ("OUT_DIR", self.out)):
            p = patch.object(current, key, value)
            p.start()
            self.addCleanup(p.stop)

    def assert_outputs(self, expected):
        self.assertEqual({p.name: p.read_bytes() for p in self.out.glob("*.csv")},
                         expected)

    def recover(self):
        exports.recover_exports(self.out, exports.CURRENT_SUFFIXES)

    def inject(self, phase, index, death=False):
        original_filter = current.filter_csv_by_season
        original_replace = os.replace

        def fail():
            if death:
                os.kill(os.getpid(), signal.SIGKILL)
            raise OSError(errno.ENOSPC, "disk full")

        def filtering(src, dst, season):
            if phase == "write" and dst.name == self.names[index]:
                dst.write_bytes(b"partial")
                fail()
            return original_filter(src, dst, season)

        def replacing(src, dst):
            result = original_replace(src, dst)
            if (phase == "replace" and Path(src).parent == self.out / ".fr1.pending/new"
                    and Path(src).name == self.names[index]):
                fail()
            return result

        with patch.object(current, "filter_csv_by_season", filtering), \
             patch.object(exports.os, "replace", replacing):
            current.process_league("FR1")

    def crash(self, phase, index):
        pid = os.fork()
        if pid == 0:
            self.inject(phase, index, death=True)
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

    def test_success_bytes_and_counts(self):
        result = current.process_league("FR1")
        self.assertEqual(result, dict(code="FR1", ok=True, season=2026,
                                     n_career=1, n_matches=1))
        self.assert_outputs(self.expected)

    def test_disk_full_during_each_write_and_replacement(self):
        for phase in ("write", "replace"):
            for index in range(2):
                with self.subTest(phase=phase, index=index), self.assertRaises(OSError):
                    self.inject(phase, index)
                self.assert_outputs(self.old)

    def test_sigkill_during_each_write_and_replacement(self):
        for phase in ("write", "replace"):
            for index in range(2):
                with self.subTest(phase=phase, index=index):
                    self.crash(phase, index)
                    self.recover()
                    self.recover()
                    self.assert_outputs(self.old)

    def test_first_generation_restores_absence(self):
        for name in self.names:
            (self.out / name).unlink()
        for index in range(2):
            self.crash("replace", index)
            self.recover()
            self.assert_outputs({})

    def test_missing_matches_preserves_previous_file_or_absence(self):
        (self.src / self.names[1]).unlink()
        result = current.process_league("FR1")
        self.assertEqual(result["n_matches"], 0)
        self.assert_outputs({self.names[0]: self.expected[self.names[0]],
                             self.names[1]: self.old[self.names[1]]})
        (self.out / self.names[1]).unlink()
        current.process_league("FR1")
        self.assert_outputs({self.names[0]: self.expected[self.names[0]]})

    def test_next_filter_recovers_before_inspecting_sources(self):
        self.crash("replace", 0)
        def detect(_):
            self.assert_outputs(self.old)
            return None
        with patch.object(current, "detect_current_season", side_effect=detect):
            self.assertFalse(current.process_league("FR1")["ok"])

    def test_zip_consumer_recovers_current_pair(self):
        self.crash("replace", 0)
        with patch.object(build_pages, "SRC_FULL", self.src), \
             patch.object(build_pages, "SRC_CURRENT", self.out), \
             patch.object(build_pages, "OUT_DATA", self.root / "zips"):
            build_pages.build_dataset_assets({"code_tm": "FR1"})
        self.assert_outputs(self.old)
        with zipfile.ZipFile(self.root / "zips/fr1_current.zip") as archive:
            self.assertEqual({n: archive.read(n) for n in archive.namelist()}, self.old)

    def test_failed_recovery_blocks_consumers(self):
        self.crash("replace", 0)
        with patch.object(exports.os, "link", side_effect=OSError("restore failed")), \
             patch.object(current, "_process_league") as process, \
             patch.object(build_pages, "SRC_FULL", self.src), \
             patch.object(build_pages, "SRC_CURRENT", self.out), \
             patch.object(build_pages, "_build_dataset_assets") as build:
            with self.assertRaises(OSError):
                current.process_league("FR1")
            with self.assertRaises(OSError):
                build_pages.build_dataset_assets({"code_tm": "FR1"})
            process.assert_not_called()
            build.assert_not_called()
        self.recover()
        self.assert_outputs(self.old)


if __name__ == "__main__":
    unittest.main()
