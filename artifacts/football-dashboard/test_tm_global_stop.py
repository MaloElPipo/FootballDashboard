"""Offline simulation of the real workflow shell, with no HTTP/browser access."""
import os
from contextlib import chdir
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import tm_player_career as scraper


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/scrape-weekly.yml"


class GlobalStopTest(unittest.TestCase):
    def setUp(self):
        scraper._blocked.clear()
        scraper._recovery_used = False

    def tearDown(self):
        scraper._blocked.clear()
        scraper._recovery_used = False

    def simulate(self, leagues, outcomes, missing=()):
        workflow = WORKFLOW.read_text()
        step = workflow.split("        id: scrape_career\n", 1)[1].split("\n      - name:", 1)[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        script = script.replace("${{ steps.list_leagues.outputs.leagues }}", ",".join(leagues))
        # Replace only the network executable, keeping the actual coordination,
        # timeout, exit statuses, output handling and retry branches unchanged.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for code in leagues:
                if code not in missing:
                    path = root / f"live/data/tm_scrap/{code}.csv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("player_id\n1\n")
            fake = root / "tm_player_career.py"
            fake.write_text(
                "import sys\nfrom pathlib import Path\n"
                f"outcomes = {outcomes!r}\n"
                "code = sys.argv[sys.argv.index('--league') + 1]\n"
                "p = Path('calls')\n"
                "calls = p.read_text().splitlines() if p.exists() else []\n"
                "n = calls.count(code)\n"
                "p.write_text('\\n'.join(calls + [code]) + '\\n')\n"
                "values = outcomes.get(code, [0])\n"
                "sys.exit(values[min(n, len(values)-1)])\n"
            )
            output = root / "outputs"
            # CSV exports and portal are not touched by the coordinator.
            previous = root / "previous.csv"
            previous.write_bytes(b"old complete export\n")
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script],
                cwd=root, env={**os.environ, "GITHUB_OUTPUT": str(output)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(previous.read_bytes(), b"old complete export\n")
            return (root / "calls").read_text().splitlines(), output.read_text()

    def test_late_block_stops_remaining_leagues_and_retry(self):
        leagues = [f"league{i}" for i in range(15)]
        calls, output = self.simulate(leagues, {"league1": [1], "league11": [75]})
        self.assertEqual(calls, leagues[:12])
        self.assertIn("blocked=true", output)
        self.assertIn("failed_leagues=league1,league11,league12,league13,league14", output)

    def test_block_during_retry_stops_remaining_retries(self):
        calls, output = self.simulate(["a", "b", "c"], {"a": [1, 75], "b": [124], "c": [1]})
        self.assertEqual(calls, ["a", "b", "c", "a"])
        self.assertIn("failed_leagues=a,b,c", output)
        self.assertIn("blocked=true", output)

    def test_ordinary_errors_still_retry(self):
        calls, output = self.simulate(["a", "b", "c"], {"a": [1, 0], "b": [124, 0]})
        self.assertEqual(calls, ["a", "b", "c", "a", "b"])
        self.assertIn("blocked=false", output)
        self.assertIn("failed_leagues=\n", output)

    def test_missing_squad_branch_honors_block(self):
        calls, output = self.simulate(["a", "b"], {"a": [75]}, missing=["a"])
        self.assertEqual(calls, ["a"])
        self.assertIn("blocked=true", output)

    def test_new_runner_dispatch_is_disabled_on_block(self):
        step = WORKFLOW.read_text().split("- name: Relancer les ligues", 1)[1]
        condition = step.split("        if:", 1)[1].splitlines()[0]
        self.assertIn("steps.scrape_career.outputs.blocked != 'true'", condition)

    def test_persistent_challenge_and_captcha_stop_without_more_sessions(self):
        for response, expected_fetches, expected_refreshes in [
            ((None, 202, "WAF challenge", True, "old"), 2, 1),
            ((None, 403, "WAF captcha", False, "old"), 1, 0),
            ((None, 429, "HTTP 429", False, "old"), 1, 0),
        ]:
            with self.subTest(response=response):
                self.setUp()
                with patch.object(scraper, "_fetch_json_once", return_value=response) as fetch, \
                        patch.object(scraper.tm_waf, "get_waf_token") as refresh:
                    scraper._fetch_json("offline")
                    scraper._fetch_json("must-not-request")
                self.assertTrue(scraper._blocked.is_set())
                self.assertEqual(fetch.call_count, expected_fetches)
                self.assertEqual(refresh.call_count, expected_refreshes)

    def test_cli_emits_blocked_exit_and_keeps_previous_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            squads = Path(tmp) / "live/data/tm_scrap"
            squads.mkdir(parents=True)
            (squads / "a.csv").write_text("player_id,season\n1,2026\n2,2026\n")
            files = [Path(tmp) / f"a_{suffix}.csv" for suffix in
                     ("summary", "career", "matches", "competitions_seen")]
            for path in files:
                path.write_bytes(b"previous complete export\n")
            def blocked_scrape(*args, **kwargs):
                scraper._blocked.set()
                return [{}], [], [], {}, ["2"]
            with chdir(tmp), patch("sys.argv", ["scraper", "--league", "a", "--out-dir", tmp]), \
                    patch.object(scraper.tm_waf, "warm_up"), \
                    patch.object(scraper, "scrape_players", side_effect=blocked_scrape):
                with self.assertRaises(SystemExit) as raised:
                    scraper.cli()
            self.assertEqual(raised.exception.code, scraper.BLOCKED_EXIT_CODE)
            for path in files:
                self.assertEqual(path.read_bytes(), b"previous complete export\n")
            self.assertTrue((Path(tmp) / "a_collection.json").exists())
            calls, output = self.simulate(["a", "b", "c"], {"a": [raised.exception.code]})
            self.assertEqual(calls, ["a"])
            self.assertIn("blocked=true", output)

    def test_challenge_then_transient_error_keeps_collection_and_retry_enabled(self):
        for response in [
            (None, None, "timeout", False, "new"),
            (None, 500, "HTTP 500", False, "new"),
            (None, 200, "JSON decode: invalid", False, "new"),
        ]:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as tmp:
                self.setUp()
                def transient_scrape(*args, **kwargs):
                    self.assertIsNone(scraper._fetch_json("offline")[0])
                    return [], [], [], {}, ["1"]
                with patch.object(scraper, "_fetch_json_once", side_effect=[
                    (None, 202, "WAF challenge", True, "old"), response,
                ]) as fetch, patch.object(scraper.tm_waf, "get_waf_token") as refresh, \
                        patch.object(scraper.tm_waf, "warm_up"), \
                        patch.object(scraper, "scrape_players", side_effect=transient_scrape), \
                        patch("sys.argv", ["scraper", "--player-ids", "1", "--out-dir", tmp]):
                    with self.assertRaises(SystemExit) as raised:
                        scraper.cli()
                self.assertEqual(raised.exception.code, 1)
                self.assertFalse(scraper._blocked.is_set())
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(refresh.call_count, 1)
                calls, output = self.simulate(
                    ["a", "b", "c"], {"a": [raised.exception.code, 0]}
                )
                self.assertEqual(calls, ["a", "b", "c", "a"])
                self.assertIn("blocked=false", output)
                self.assertIn("failed_leagues=\n", output)


if __name__ == "__main__":
    unittest.main()
