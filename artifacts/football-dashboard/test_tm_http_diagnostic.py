"""Offline checks of the experiment's budget, stop conditions and safe output."""
import contextlib
import io
import unittest
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
