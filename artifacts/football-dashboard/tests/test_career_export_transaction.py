"""Offline fault injection, including real process death during replacement."""
import errno
import csv
import io
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
import tm_player_career as scraper
from scripts.build_pages import build_zip
from scripts import build_pages, make_current_season


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.tx = exports.ExportTransaction(self.out, "custom")
        self.old = {n: f"old {n}\r\n".encode() for n in self.tx.names}
        self.new = {n: f'new,"é,{n}"\r\n'.encode() for n in self.tx.names}
        for n, data in self.old.items():
            (self.out / n).write_bytes(data)

    def prepare(self, directory):
        for n, data in self.new.items():
            (directory / n).write_bytes(data)

    def assert_files(self, expected):
        self.assertEqual({p.name: p.read_bytes() for p in self.out.glob("*.csv")},
                         expected)

    def test_success_keeps_exact_names_and_bytes(self):
        with exports.export_transaction(self.out, "custom") as tx:
            tx.write(self.prepare)
        self.assert_files(self.new)
        self.assertFalse(self.tx.pending.exists())

    def test_csv_serialization_and_zip_contract_unchanged(self):
        rows = [{"player_id": "1", "player_name": 'Éric, "Test"\nSuite',
                 "minutes": 12, "ignored": "extra"}]
        counts = {"FR1": 3, "GB1": 3, "ES1": 1}
        expected = {}
        for suffix, cols in (("summary", scraper.SUMMARY_COLS),
                             ("career", scraper.CAREER_COLS),
                             ("matches", scraper.MATCHES_COLS)):
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            expected[f"custom_{suffix}.csv"] = stream.getvalue().encode("utf-8")
        expected["custom_competitions_seen.csv"] = (
            b"competition_id,n_players_with_match\r\nFR1,3\r\nGB1,3\r\nES1,1\r\n")
        with patch.object(sys, "argv", ["scraper", "--player-ids", "1",
                                       "--out-dir", str(self.out)]), \
             patch.object(scraper.tm_waf, "warm_up"), \
             patch.object(scraper, "_log"), \
             patch.object(scraper, "scrape_players",
                          return_value=(rows, rows, rows, counts, [])):
            scraper.cli()
        self.assert_files(expected)
        archive = self.out / "custom_all.zip"
        build_zip(archive, [self.out / n for n in self.tx.names])
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.namelist(), self.tx.names)
            self.assertEqual({n: z.read(n) for n in z.namelist()}, expected)

    def test_full_disk_at_each_preparation_file(self):
        for fail_at in range(4):
            def prepare(directory):
                for i, (name, data) in enumerate(self.new.items()):
                    (directory / name).write_bytes(data[:2])
                    if i == fail_at:
                        raise OSError(errno.ENOSPC, "disk full")
                    (directory / name).write_bytes(data)
            with self.subTest(file=fail_at), self.assertRaises(OSError):
                with exports.export_transaction(self.out, "custom") as tx:
                    tx.write(prepare)
            self.assert_files(self.old)

    def failing_replace(self, fail_at, death=False):
        real = os.replace
        count = 0

        def replace(src, dst):
            nonlocal count
            result = real(src, dst)
            if Path(src).parent == self.tx.pending / "new":
                count += 1
                if count == fail_at:
                    if death:
                        os.kill(os.getpid(), signal.SIGKILL)
                    raise OSError(errno.ENOSPC, "disk full")
            return result
        return replace

    def test_error_after_each_replacement_rolls_back(self):
        for i in range(1, 5):
            with self.subTest(file=i), self.assertRaises(OSError):
                with exports.export_transaction(self.out, "custom") as tx:
                    with patch.object(exports.os, "replace", self.failing_replace(i)):
                        tx.write(self.prepare)
            self.assert_files(self.old)

    def crash_write(self, i):
        pid = os.fork()
        if pid == 0:
            with exports.export_transaction(self.out, "custom") as tx:
                with patch.object(exports.os, "replace", self.failing_replace(i, True)):
                    tx.write(self.prepare)
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

    def test_kill_at_every_replacement_recovers_before_network(self):
        for i in range(1, 5):
            self.crash_write(i)
            def network(**kwargs):
                self.assert_files(self.old)
                raise RuntimeError("offline")
            with patch.object(sys, "argv", ["scraper", "--player-ids", "1",
                                           "--out-dir", str(self.out)]), \
                 patch.object(scraper.tm_waf, "warm_up", side_effect=network), \
                 self.assertRaisesRegex(RuntimeError, "offline"):
                scraper.cli()
            self.assert_files(self.old)

    def test_killed_final_attempt_then_direct_zip_consumption(self):
        for i in range(1, 5):
            self.crash_write(i)
            with patch.object(build_pages, "SRC_FULL", self.out), \
                 patch.object(build_pages, "SRC_CURRENT", self.out / "current"), \
                 patch.object(build_pages, "OUT_DATA", self.out / "zips"):
                meta = build_pages.build_dataset_assets({"code_tm": "CUSTOM"})
            self.assert_files(self.old)
            self.assertTrue(meta["has_full"])
            with zipfile.ZipFile(self.out / "zips/custom_all.zip") as z:
                self.assertEqual({n: z.read(n) for n in z.namelist()}, self.old)

    def test_killed_final_attempt_then_current_season_consumption(self):
        for name in self.tx.names:
            self.old[name] = b"season,player_id\r\n2026,1\r\n2025,2\r\n"
            (self.out / name).write_bytes(self.old[name])
        self.crash_write(3)
        with patch.object(make_current_season, "SRC_DIR", self.out), \
             patch.object(make_current_season, "OUT_DIR", self.out / "current"):
            result = make_current_season.process_league("custom")
        self.assertTrue(result["ok"])
        self.assert_files(self.old)
        for suffix in ("career", "matches"):
            self.assertEqual((self.out / "current" / f"custom_{suffix}.csv").read_bytes(),
                             b"season,player_id\r\n2026,1\r\n")

    def test_failed_recovery_prevents_zip_and_filter_reads(self):
        self.crash_write(2)
        with patch.object(exports.os, "link", side_effect=OSError("cannot restore")), \
             patch.object(build_pages, "SRC_FULL", self.out), \
             patch.object(build_pages, "_build_dataset_assets") as build, \
             patch.object(make_current_season, "SRC_DIR", self.out), \
             patch.object(make_current_season, "_process_league") as process:
            with self.assertRaises(OSError):
                build_pages.build_dataset_assets({"code_tm": "CUSTOM"})
            with self.assertRaises(OSError):
                make_current_season.process_league("custom")
            with self.assertRaises(OSError):
                exports.recover_exports(self.out)
            build.assert_not_called()
            process.assert_not_called()
        exports.recover_exports(self.out)
        self.assert_files(self.old)

    def test_first_export_and_partial_existing_set_recover_absence(self):
        for existing in ([], self.tx.names[:2]):
            for n in self.tx.names:
                (self.out / n).unlink(missing_ok=True)
            for n in existing:
                (self.out / n).write_bytes(self.old[n])
            self.crash_write(3)
            with exports.export_transaction(self.out, "custom"):
                pass
            self.assert_files({n: self.old[n] for n in existing})

    def test_interrupted_recovery_can_be_repeated(self):
        self.crash_write(3)
        real = os.replace
        def fail_restore(src, dst):
            real(src, dst)
            if Path(src).name == "restore":
                raise OSError("restore interrupted")
        with patch.object(exports.os, "replace", fail_restore), \
             self.assertRaises(OSError):
            self.tx.recover()
        self.assertTrue(self.tx.pending.is_dir())
        with exports.export_transaction(self.out, "custom"):
            pass
        self.assert_files(self.old)

    def test_committed_cleanup_failure_does_not_rollback(self):
        with exports.export_transaction(self.out, "custom") as tx:
            with patch.object(exports.shutil, "rmtree", side_effect=OSError("cleanup")), \
                 self.assertRaises(OSError):
                tx.write(self.prepare)
        with exports.export_transaction(self.out, "custom"):
            pass
        self.assert_files(self.new)


if __name__ == "__main__":
    unittest.main()
