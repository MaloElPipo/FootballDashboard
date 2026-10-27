"""Offline checks of the experiment's budget, stop conditions and safe output."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import tm_http_diagnostic as d


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.sample = [(d.LEAGUES[i % 12], str(i + 1)) for i in range(36)]

    def tearDown(self):
        d.career._blocked.clear()

    def run_probe(self, result):
        fetch, sleep = Mock(return_value=result), Mock()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            report = d.probe(self.sample, "private-cookie", fetch=fetch, sleep=sleep)
        self.assertNotIn("private", output.getvalue())
        return report, fetch, sleep

    def test_three_stages_and_exact_budget(self):
        report, fetch, sleep = self.run_probe(
            ({"success": True, "data": {"performance": []}}, 200, None, False, "private-cookie"))
        self.assertEqual(fetch.call_count, 36)
        self.assertEqual(report["completed_stages"], [6, 18, 36])
        self.assertEqual(report["successes"], 36)
        self.assertEqual(report["circuit_triggers"], 0)
        self.assertEqual([c.args[0] for c in sleep.call_args_list].count(30), 2)
        self.assertEqual(sleep.call_count, 35)

    def test_stop_on_every_failure_without_retry_or_sensitive_log(self):
        for status, error, challenge, expected in (
            (405, "HTTP 405; waf=captcha private", False, "captcha"),
            (403, "private", False, "http_403"),
            (429, "private", False, "http_429"),
            (202, "private", True, "waf_challenge"),
            (500, "private", False, "http_500"),
            (None, "private", False, "transport_error"),
            (200, "private", False, "invalid_payload"),
        ):
            with self.subTest(status=status):
                report, fetch, sleep = self.run_probe((None, status, error, challenge, "private"))
                self.assertEqual(fetch.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(report["stop_reason"], expected)
                self.assertEqual(report["circuit_triggers"], 1)

    def test_late_failure_does_not_reset_circuit_at_league_boundary(self):
        fetch = Mock(side_effect=[
            ({"success": True, "data": {"performance": []}}, 200, None, False, None)
        ] * 13 + [(None, 405, "HTTP 405", False, None)])
        with contextlib.redirect_stdout(io.StringIO()):
            report = d.probe(self.sample, None, fetch=fetch, sleep=lambda _: None)
        self.assertEqual(report["attempted"], 14)
        self.assertEqual(report["successes"], 13)
        self.assertEqual(report["completed_stages"], [6])

    def test_time_budget_before_network(self):
        fetch = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            report = d.probe(self.sample, None, fetch=fetch, sleep=Mock(),
                             clock=Mock(side_effect=[0, 901, 901]))
        fetch.assert_not_called()
        self.assertEqual(report["stop_reason"], "time_budget")

    def test_redirects_not_followed(self):
        self.assertIsNone(d.NoRedirect().redirect_request(None, None, 302, "", {}, "private"))

    def test_invalid_or_duplicate_sample_rejected(self):
        for sample in (self.sample[:2], [("a1", "1")] * 36):
            with self.assertRaises(ValueError):
                d.probe(sample, None)

    def test_sample_current_season_deduplicated_across_leagues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i, league in enumerate(d.LEAGUES):
                (root / f"{league}.csv").write_text(
                    "season,player_id\n2024,99999\n" +
                    "".join(f"2025,{i * 10 + j}\n" for j in range(1, 6)))
            sample, sources = d.select_sample(root)
        self.assertEqual(len(set(pid for _, pid in sample)), 36)
        self.assertEqual(len(set(league for league, _ in sample)), 12)
        self.assertNotIn("99999", [pid for _, pid in sample])
        self.assertTrue(all(s["season"] == 2025 for s in sources.values()))

    def test_bootstrap_stops_at_cap_without_logging_cookie(self):
        # Mock the browser, but exercise the real request/response handlers.
        context, browser, page = Mock(), Mock(), Mock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        manager = Mock()
        manager.__enter__ = Mock(return_value=Mock())
        manager.__exit__ = Mock(return_value=False)
        manager.__enter__.return_value.chromium.launch.return_value = browser
        module = Mock()
        module.sync_playwright.return_value = manager
        routes = [Mock() for _ in range(41)]
        for route in routes:
            route.request.url = "https://www.transfermarkt.com/"
            route.request.resource_type = "document"

        def goto(*args, **kwargs):
            handler = context.route.call_args.args[1]
            for route in routes:
                handler(route)

        page.goto.side_effect = goto
        with patch.dict("sys.modules", {"playwright.sync_api": module}):
            token, stats = d.bootstrap()
        self.assertIsNone(token)
        self.assertEqual(stats["requests"], 40)
        self.assertEqual(stats["stop"], "bootstrap_budget")
        routes[-1].abort.assert_called_once()
        context.cookies.assert_not_called()
        browser.close.assert_called_once()

    def test_setup_failure_still_writes_safe_report_only_in_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"RUNNER_TEMP": directory}), \
                    patch.object(d, "select_sample", side_effect=RuntimeError("private")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(d.main(), 1)
            report = json.loads((Path(directory) / "tm-http-diagnostic.json").read_text())
            self.assertEqual(report["stop_reason"], "setup_error")
            self.assertNotIn("private", output.getvalue())

    def test_invalid_sample_does_not_open_browser(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"RUNNER_TEMP": directory}), \
                patch.object(d, "select_sample", side_effect=ValueError("private")), \
                patch.object(d, "bootstrap") as bootstrap, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(), 1)
            bootstrap.assert_not_called()
            report = json.loads((Path(directory) / "tm-http-diagnostic.json").read_text())
            self.assertEqual(report["stop_reason"], "invalid_sample")


if __name__ == "__main__":
    unittest.main()
