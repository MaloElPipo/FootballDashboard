"""Sélection des effectifs et câblage CI, sans réseau ni modification des CSV."""
import contextlib
from datetime import datetime
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.leagues_master import LEAGUES
from scripts import scrape_all_squads as squads

WORKFLOW = ROOT.parents[1] / ".github/workflows/scrape-weekly.yml"


class SquadSelectionTest(unittest.TestCase):
    def run_main(self, args, failed_code=None):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            original = {}
            for league in LEAGUES:
                path = directory / f"{league['code_tm'].lower()}.csv"
                original[path] = b"player,season\nretained,2025\n"
                path.write_bytes(original[path])

            def fake_run(code, slug, extra_args):
                if code == failed_code:
                    return {"ok": False, "elapsed_s": 0, "error": "offline failure"}
                return {"ok": True, "elapsed_s": 0, "n_rows": 1, "size_kb": 1}

            with (
                patch.object(sys, "argv", ["scrape_all_squads.py", *args]),
                patch.object(squads, "TM_SCRAP_DIR", directory),
                patch.object(squads, "PROGRESS_FILE", directory / "progress.json"),
                patch.object(squads, "run_one", side_effect=fake_run) as run,
                patch.object(squads.subprocess, "run", side_effect=AssertionError("network forbidden")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                try:
                    status = squads.main()
                except SystemExit as exc:
                    status = exc.code
                for path, content in original.items():
                    self.assertEqual(path.read_bytes(), content)
                return status, run.call_args_list, (directory / "progress.json").exists()

    def test_targeted_refresh_normalizes_and_deduplicates(self):
        status, calls, _ = self.run_main(
            ["--refresh-current", "--leagues", " fr1, L1,FR1 "])
        self.assertEqual(status, 0)
        self.assertEqual([call.args[0] for call in calls], ["FR1", "L1"])
        year = datetime.utcnow().year
        for call in calls:
            self.assertEqual(call.kwargs["extra_args"],
                             ["--seasons", f"{year - 1},{year}", "--merge"])

    def test_full_refresh_includes_every_configured_league(self):
        for selection in ([], ["--leagues", ""]):
            with self.subTest(selection=selection):
                status, calls, _ = self.run_main(["--refresh-current", *selection])
                self.assertEqual(status, 0)
                self.assertEqual([call.args[0] for call in calls],
                                 [league["code_tm"] for league in LEAGUES])

    def test_invalid_selection_fails_before_any_scrape_or_progress_write(self):
        for args in (
            ["--leagues", "FR1,UNKNOWN"], ["--only", "UNKNOWN"],
            ["--leagues", "FR1,"], ["--leagues", ","], ["--leagues", " "],
            ["--leagues", "FR1\nleagues=L1"], ["--only", ""],
            ["--only", "FR1,L1"], ["--only", "FR1", "--leagues", "L1"],
        ):
            with self.subTest(args=args):
                status, calls, progress_written = self.run_main(["--refresh-current", *args])
                self.assertEqual(status, 2)
                self.assertEqual(calls, [])
                self.assertFalse(progress_written)

    def test_only_compatibility_and_existing_file_skip(self):
        status, calls, _ = self.run_main(["--refresh-current", "--only", "fr1"])
        self.assertEqual(status, 0)
        self.assertEqual([call.args[0] for call in calls], ["FR1"])
        status, calls, _ = self.run_main(["--leagues", "FR1,L1"])
        self.assertEqual((status, calls), (0, []))
        status, calls, _ = self.run_main(["--force", "--leagues", "FR1"])
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0].kwargs["extra_args"])

    def test_partial_failure_continues_only_with_selected_leagues(self):
        status, calls, _ = self.run_main(
            ["--refresh-current", "--leagues", "FR1,L1"], failed_code="FR1")
        self.assertEqual(status, 1)
        self.assertEqual([call.args[0] for call in calls], ["FR1", "L1"])

    def test_workflow_selection_script_and_refresh_argument(self):
        workflow = WORKFLOW.read_text()
        listing = workflow.split("        id: list_leagues\n", 1)[1].split(
            "\n      - name:", 1)[0]
        self.assertIn("REQUESTED_LEAGUES: ${{ github.event.inputs.leagues }}", listing)
        script = textwrap.dedent(listing.split("        run: |\n", 1)[1])
        refresh = workflow.split(
            "      - name: Rafraîchir les effectifs existants", 1)[1].split(
                "\n      - name:", 1)[0]
        self.assertIn("SELECTED_LEAGUES: ${{ steps.list_leagues.outputs.leagues }}", refresh)
        self.assertIn('--refresh-current --leagues "$SELECTED_LEAGUES"', refresh)
        for selection, expected in (
            (" fr1,L1,FR1 ", "fr1,l1"),
            ("", ",".join(league["code_tm"].lower() for league in LEAGUES)),
            ("FR1,UNKNOWN", None),
            ('FR1,$(touch injected)', None),
        ):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "output"
                result = subprocess.run(
                    ["bash", "-e", "-c", script], cwd=ROOT,
                    env={**os.environ, "REQUESTED_LEAGUES": selection,
                         "GITHUB_OUTPUT": str(output)},
                    capture_output=True, text=True,
                )
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), f"leagues={expected}\n")


if __name__ == "__main__":
    unittest.main()
