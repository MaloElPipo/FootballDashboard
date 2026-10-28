import contextlib
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collection_metadata import (
    read_metadata, collection_evidence, start_attempt, incomplete_attempt,
    write_metadata,
)
from scripts import build_pages
import tm_player_career as scraper


class CollectionFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.full = self.root / "full"
        self.current = self.root / "current"
        self.output = self.root / "site" / "data"
        for folder in (self.full, self.current, self.output):
            folder.mkdir(parents=True)
        self.target = dict(code_tm="XX", kind="league", pays="France",
                           nom="Test league", tier=1, region="Europe")
        for name, value in (("SRC_FULL", self.full), ("SRC_CURRENT", self.current),
                            ("OUT_DATA", self.output)):
            p = patch.object(build_pages, name, value)
            p.start()
            self.addCleanup(p.stop)

    def collect(self, failed=False, extra=(), write_error=False, missing=False,
                empty=False, interrupt=False, request_error=False):
        result = ([{"player_id": "1"}], [{"player_id": "1"}],
                  [{"player_id": "1"}], {"FR1": 1}, ["2"] if failed else [])
        def scrape(*args, checkpoints, **kwargs):
            if interrupt:
                raise KeyboardInterrupt()
            if request_error:
                raise RuntimeError("private request URL")
            checkpoints.put("1", {"performance": []})
            return result
        with patch.object(sys, "argv", ["scraper", "--league", "xx",
                                       "--out-dir", str(self.full),
                                       "--checkpoint-dir", str(self.root / "cp"), *extra]), \
             patch.object(scraper.os.path, "exists", return_value=not missing), \
             patch.object(scraper, "max_season_in_csv", return_value=2026), \
             patch.object(scraper, "load_player_meta_from_league_csv",
                          return_value={} if empty else {"1": {}}), \
             patch.object(scraper.tm_waf, "warm_up"), \
             patch.object(scraper, "scrape_players", side_effect=scrape), \
             contextlib.redirect_stdout(io.StringIO()):
            if write_error:
                with patch.object(scraper, "write_csv", side_effect=OSError("disk full")):
                    scraper.cli()
            else:
                scraper.cli()

    def build(self):
        meta = build_pages.build_dataset_assets(self.target)
        return meta, build_pages.render_html([meta])

    def test_success_failure_rebuild_preserve_evidence_and_archives(self):
        self.collect()
        before = read_metadata(self.full, "xx")["last_success"]
        original = {p.name: p.read_bytes() for p in self.full.glob("*.csv")}
        current = {name: content for name, content in original.items()
                   if name in ("xx_career.csv", "xx_matches.csv")}
        for name, content in current.items():
            (self.current / name).write_bytes(content)
        meta, html = self.build()
        self.assertEqual(meta["collection_status"], "updated")
        self.assertIn("Actualisées lors de la dernière tentative", html)
        for p in self.full.glob("*.csv"):
            os.utime(p, (946684800, 946684800))
        self.assertEqual(self.build()[0]["last_update"], meta["last_update"])
        with self.assertRaises(SystemExit):
            self.collect(failed=True)
        self.assertEqual(read_metadata(self.full, "xx")["last_success"], before)
        retained, html = self.build()
        self.assertEqual(retained["last_update"], meta["last_update"])
        self.assertEqual(retained["collection_status"], "retained")
        self.assertIn("Anciennes données conservées", html)
        self.assertIn("Requêtes joueurs échouées", html)
        self.assertIn("Dernière tentative", html)
        self.assertIn("UTC", html)
        saved = (self.full / "xx_collection.json").read_bytes()
        self.build()
        self.assertEqual((self.full / "xx_collection.json").read_bytes(), saved)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.full.glob("*.csv")})
        for archive in self.output.glob("*.zip"):
            with zipfile.ZipFile(archive) as z:
                expected = current if "updates" in archive.name or "_current" in archive.name else original
                self.assertEqual(set(z.namelist()), set(expected))
                for name in z.namelist():
                    self.assertEqual(z.read(name), expected[name])

    def test_legacy_and_corrupt_metadata_are_unknown(self):
        self.collect()
        path = self.full / "xx_collection.json"
        for contents in (None, "{broken", '{"last_success": []}',
                         '{"last_success":{"completed_at":"2026-01-01"}}'):
            if contents is None:
                path.unlink()
            else:
                path.write_text(contents)
            meta, html = self.build()
            self.assertIsNone(meta["last_update"])
            self.assertIn("Date inconnue", html)
            self.assertEqual(meta["collection_status"], "unknown")

    def test_export_exception_cannot_advance_success(self):
        self.collect()
        before = read_metadata(self.full, "xx")["last_success"]
        with self.assertRaises(OSError):
            self.collect(write_error=True)
        self.assertEqual(read_metadata(self.full, "xx")["last_success"], before)
        self.assertEqual(collection_evidence(self.full, "xx")[1], "retained")
        self.assertEqual(incomplete_attempt(self.full, "xx")[1], "Écriture échouée")

    def test_causes_preserve_last_success_and_clear_on_success(self):
        self.collect()
        before = read_metadata(self.full, "xx")["last_success"]
        for options, error, label in (
            ({"missing": True}, SystemExit, "Effectif absent"),
            ({"empty": True}, SystemExit, "Effectif absent"),
            ({"interrupt": True}, KeyboardInterrupt, "Collecte interrompue"),
            ({"request_error": True}, RuntimeError, "Requêtes joueurs échouées"),
        ):
            with self.subTest(options=options):
                with self.assertRaises(error):
                    self.collect(**options)
                self.assertEqual(read_metadata(self.full, "xx")["last_success"], before)
                self.assertEqual(incomplete_attempt(self.full, "xx")[1], label)
                self.assertIn(label, self.build()[1])
                self.assertNotIn("private request URL", self.build()[1])
        self.collect()
        self.assertEqual(incomplete_attempt(self.full, "xx"), (None, None))
        self.assertNotIn("Dernière tentative</span>", self.build()[1])

    def test_interrupted_without_exports_and_untrusted_metadata(self):
        start_attempt(self.full, "xx")
        html = self.build()[1]
        self.assertIn("Collecte interrompue", html)
        self.assertIn("Données indisponibles", html)
        for reason in (None, [], "<script>private-token</script>"):
            write_metadata(self.full, "xx", {"last_attempt": {
                "status": "incomplete", "reason": reason,
                "started_at": "private-token",
            }})
            self.assertEqual(incomplete_attempt(self.full, "xx"), (None, None))
            self.assertNotIn("private-token", self.build()[1])

    def test_workflow_missing_squad_skip_records_attempt(self):
        self.collect()
        before = read_metadata(self.full, "xx")["last_success"]
        workflow = (ROOT.parents[1] / ".github/workflows/scrape-weekly.yml").read_text()
        start = workflow.index('            if [ ! -f "$f" ]')
        end = workflow.index("\n            fi\n", start) + len("\n            fi")
        skip_branch = workflow[start:end]
        (self.root / "tm_player_career.py").symlink_to(ROOT / "tm_player_career.py")
        data = self.root / "live/data"
        squads = data / "tm_scrap"
        squads.mkdir(parents=True)
        (data / "tm_career").symlink_to(self.full, target_is_directory=True)
        command = (
            'SKIP=0; for code in xx; do f="live/data/tm_scrap/${code}.csv";\n'
            + skip_branch + '\ndone; test "$SKIP" = 1'
        )
        for contents in (None, "player_id,season\n"):
            with self.subTest(contents=contents):
                if contents is not None:
                    (squads / "xx.csv").write_text(contents)
                result = subprocess.run(["bash", "-ec", command], cwd=self.root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(read_metadata(self.full, "xx")["last_success"], before)
                stamp, reason = incomplete_attempt(self.full, "xx")
                self.assertIsNotNone(stamp)
                self.assertEqual(reason, "Effectif absent")
                meta, html = self.build()
                self.assertEqual(meta["collection_status"], "retained")
                self.assertIn("Effectif absent", html)
                self.assertIn("Dernière tentative", html)

    def test_test_mode_and_unproven_replacement_do_not_certify_collection(self):
        self.collect(extra=("--test",))
        self.assertIsNone(collection_evidence(self.full, "xx")[0])
        self.collect()
        (self.full / "xx_career.csv").write_text("changed\n")
        self.assertIsNone(collection_evidence(self.full, "xx")[0])

    def test_failed_legacy_collection_retains_unknown_date(self):
        self.collect(extra=("--test",))
        with self.assertRaises(SystemExit):
            self.collect(failed=True)
        meta, _ = self.build()
        self.assertIsNone(meta["last_update"])
        self.assertEqual(meta["collection_status"], "retained")


if __name__ == "__main__":
    unittest.main()
