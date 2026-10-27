"""Offline regression tests; no network and no CSV writes."""
import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

import tm_player_career as scraper


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        scraper._blocked.clear()
        scraper._recovery_used = False

    def tearDown(self):
        scraper._blocked.clear()
        scraper._recovery_used = False

    def test_success_does_not_refresh(self):
        with patch.object(scraper, "_fetch_json_once", return_value=({}, 200, None, False, "old")), patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            self.assertEqual(scraper._fetch_json("test")[:2], ({}, 200))
            refresh.assert_not_called()

    def test_one_refresh_recovers(self):
        with patch.object(scraper, "_fetch_json_once", side_effect=[
            (None, 405, "HTTP 405", False, "old"), ({"data": {}}, 200, None, False, "new")
        ]), patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            self.assertEqual(scraper._fetch_json("test")[1], 200)
            refresh.assert_called_once_with(force_refresh=True, stale="old")
            self.assertFalse(scraper._blocked.is_set())

    def test_persistent_failure_stops_network(self):
        with patch.object(scraper, "_fetch_json_once", return_value=(None, 405, "HTTP 405", False, "old")) as fetch, patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            scraper._fetch_json("test")
            scraper._fetch_json("another")
            self.assertEqual(fetch.call_count, 2)
            refresh.assert_called_once()
            self.assertTrue(scraper._blocked.is_set())

    def test_captcha_not_retried(self):
        with patch.object(scraper, "_fetch_json_once", return_value=(None, 405, "HTTP 405; waf=captcha; body=html", False, "old")) as fetch, patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            scraper._fetch_json("test")
            self.assertEqual(fetch.call_count, 1)
            refresh.assert_not_called()
            self.assertTrue(scraper._blocked.is_set())

    def test_concurrent_failure_refreshes_once(self):
        with patch.object(scraper, "_fetch_json_once", return_value=(None, 405, "HTTP 405", False, "old")), patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(scraper._fetch_json, ["test"] * 20))
            refresh.assert_called_once()
            self.assertTrue(scraper._blocked.is_set())

    def test_header_classification_no_body_or_secrets(self):
        headers = Message()
        headers["x-amzn-waf-action"] = "captcha"
        headers["Content-Type"] = "text/html"
        error = HTTPError("test", 405, "error", headers, io.BytesIO(b"private content"))
        with patch.object(scraper.tm_waf, "get_waf_token", return_value=None), patch.object(scraper.urllib.request, "urlopen", side_effect=error):
            result = scraper._fetch_json_once("https://example.com")
            self.assertEqual(result[2], "HTTP 405; waf=captcha; body=html")

    def test_existing_challenge_retry_kept(self):
        with patch.object(scraper, "_fetch_json_once", side_effect=[
            (None, 202, "WAF challenge", True, "old"), ({}, 200, None, False, "new")
        ]), patch.object(scraper.tm_waf, "get_waf_token") as refresh:
            self.assertEqual(scraper._fetch_json("test")[1], 200)
            refresh.assert_called_once()

    def test_blocked_players_all_marked_failed(self):
        scraper._blocked.set()
        with patch.object(scraper, "fetch_player_career") as fetch:
            summary, career, matches, counts, failed = scraper.scrape_players({"1": {}, "2": {}}, workers=2)
            self.assertEqual(set(failed), {"1", "2"})
            self.assertEqual((summary, career, matches), ([], [], []))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
