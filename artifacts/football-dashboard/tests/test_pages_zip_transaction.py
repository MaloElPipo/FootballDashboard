"""Offline failure-injection tests for individual and global portal ZIPs."""
import contextlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_pages as pages


class PagesZipTransactionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.full, self.current = self.root / "full", self.root / "current"
        self.site = self.root / "site"
        self.data = self.site / "data"
        for folder in (self.full, self.current, self.data):
            folder.mkdir(parents=True)
        for name, value in (("SRC_FULL", self.full), ("SRC_CURRENT", self.current),
                            ("OUT_DIR", self.site), ("OUT_DATA", self.data)):
            p = patch.object(pages, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.target = dict(code_tm="XX", kind="league", pays="France",
                           nom="Test", tier=1, region="Europe")
        for folder, suffixes in (
            (self.full, ("summary", "career", "matches", "competitions_seen")),
            (self.current, ("career", "matches")),
        ):
            for suffix in suffixes:
                (folder / f"xx_{suffix}.csv").write_bytes(
                    b'\xef\xbb\xbfname,value\r\n"Jos\xc3\xa9, test","a\nb"\r\n'
                    + f"{folder.name},{suffix}\r\n".encode()
                )
        self.files = sorted(self.full.glob("*.csv"))

    def assert_archive(self, path, files):
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), [p.name for p in files])
            for p in files:
                self.assertEqual(archive.read(p.name), p.read_bytes())

    def test_all_four_archive_types_preserve_entries_and_csv_bytes(self):
        before = {p: p.read_bytes() for p in (*self.files, *self.current.glob("*.csv"))}
        meta = pages.build_dataset_assets(self.target)
        globals_created = set()
        html = pages.render_html([meta], archive_paths=globals_created)
        self.assertEqual(len(globals_created), 2)
        full = [self.full / f"xx_{s}.csv" for s in
                ("summary", "career", "matches", "competitions_seen")]
        current = [self.current / f"xx_{s}.csv" for s in ("career", "matches")]
        for path in self.data.glob("*.zip"):
            self.assert_archive(path, current if "current" in path.name or "updates" in path.name else full)
        self.assertEqual(len(list(self.data.glob("*.zip"))), 4)
        self.assertIn("Collect all career", html)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_failures_during_compression_keep_old_zip_or_absence(self):
        dest = self.data / "test.zip"
        original_write = zipfile._ZipWriteFile.write
        for existing in (False, True):
            for error in (OSError("disk full"), KeyboardInterrupt(), SystemExit(9)):
                with self.subTest(existing=existing, error=type(error).__name__):
                    dest.unlink(missing_ok=True)
                    if existing:
                        pages.build_zip(dest, self.files[:1])
                    old = dest.read_bytes() if existing else None

                    def interrupt(writer, data):
                        original_write(writer, data)
                        raise error

                    with patch.object(zipfile._ZipWriteFile, "write", interrupt):
                        with self.assertRaises(type(error)):
                            pages.build_zip(dest, self.files)
                    self.assertEqual(dest.read_bytes() if dest.exists() else None, old)
                    self.assertFalse(dest.with_name(f".{dest.name}.tmp").exists())

    def test_close_sync_and_replace_failure_preserve_old_zip(self):
        dest = self.data / "test.zip"
        pages.build_zip(dest, self.files[:1])
        old = dest.read_bytes()
        for obj, method in ((zipfile.ZipFile, "_write_end_record"),
                            (pages.os, "fsync"), (pages.os, "replace")):
            with self.subTest(method=method):
                with patch.object(obj, method, side_effect=OSError(method)):
                    with self.assertRaises(OSError):
                        pages.build_zip(dest, self.files)
                self.assertEqual(dest.read_bytes(), old)
                self.assertFalse(dest.with_name(f".{dest.name}.tmp").exists())

    def test_replacement_sees_closed_synced_complete_zip_in_same_directory(self):
        dest = self.data / "test.zip"
        real_replace, real_sync = os.replace, os.fsync
        events = []

        def sync(fd):
            events.append("sync")
            real_sync(fd)

        def replace(src, dst):
            events.append("replace")
            self.assertEqual(Path(src).parent, dest.parent)
            self.assert_archive(src, self.files)
            real_replace(src, dst)

        with patch.object(pages.os, "fsync", sync), patch.object(pages.os, "replace", replace):
            size = pages.build_zip(dest, self.files)
        self.assertEqual(events, ["sync", "replace", "sync"])
        self.assertEqual(size, dest.stat().st_size)

    def test_sigkill_during_compression_is_recovered_on_retry(self):
        dest = self.data / "test.zip"
        pages.build_zip(dest, self.files[:1])
        old = dest.read_bytes()
        script = """
import os, signal, sys, zipfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.build_pages import build_zip
original = zipfile._ZipWriteFile.write
def kill(writer, data):
    original(writer, data)
    os.kill(os.getpid(), signal.SIGKILL)
zipfile._ZipWriteFile.write = kill
build_zip(Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]])
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT), str(dest),
                                 *map(str, self.files)], timeout=20, capture_output=True)
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)
        self.assertEqual(dest.read_bytes(), old)
        temporary = dest.with_name(f".{dest.name}.tmp")
        self.assertTrue(temporary.exists())
        pages.build_zip(dest, self.files)
        self.assert_archive(dest, self.files)
        self.assertFalse(temporary.exists())

    def test_global_archives_keep_previous_bytes_on_compression_failure(self):
        meta = pages.build_dataset_assets(self.target)
        pages.render_html([meta])
        original_write = zipfile.ZipFile.write
        for kind in ("career", "updates"):
            path = next(self.data.glob(f"collect_all_{kind}_*.zip"))
            old = path.read_bytes()

            def fail(archive, filename, *args, **kwargs):
                original_write(archive, filename, *args, **kwargs)
                if f"collect_all_{kind}_" in archive.fp.name:
                    raise KeyboardInterrupt()

            with patch.object(zipfile.ZipFile, "write", fail):
                with self.assertRaises(KeyboardInterrupt):
                    pages.render_html([meta])
            self.assertEqual(path.read_bytes(), old)

    def test_main_defers_old_output_cleanup_until_success(self):
        dest = self.data / "xx_all.zip"
        pages.build_zip(dest, self.files[:1])
        old = dest.read_bytes()
        obsolete = self.data / "obsolete.zip"
        obsolete.write_bytes(b"previous archive")
        index = self.site / "index.html"
        index.write_text("previous page")
        with patch.object(pages, "get_leagues_config", return_value=[self.target]), \
             contextlib.redirect_stdout(io.StringIO()):
            with patch.object(zipfile.ZipFile, "write", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    pages.main()
            self.assertEqual(dest.read_bytes(), old)
            self.assertTrue(obsolete.exists())
            self.assertEqual(index.read_text(), "previous page")
            self.assertEqual(pages.main(), 0)
        self.assertFalse(obsolete.exists())
        self.assertIn("Collect all career", index.read_text())

    def test_missing_file_rules_unchanged(self):
        missing = self.full / "missing.csv"
        dest = self.data / "test.zip"
        pages.build_zip(dest, [self.files[0], missing])
        self.assert_archive(dest, self.files[:1])
        old = dest.read_bytes()
        with self.assertRaises(FileNotFoundError):
            pages.build_zip(dest, [self.files[0], missing], skip_missing=False)
        self.assertEqual(dest.read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
