"""All browser calls are mocked; validation never fetches or resolves hosts."""

import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from tools import browser_tools as browser


class BrowserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        boundary = patch("tools.browser_tools.webbrowser.open", return_value=True)
        self.open_browser = boundary.start()
        self.addCleanup(boundary.stop)

    def test_http_and_https(self) -> None:
        for url in ("https://example.com/path?q=hello", "http://example.com", "https://[::1]:8080/", "https://例え.jp/"):
            with self.subTest(url=url):
                self.assertTrue(browser.open_url(url).success)
        self.assertEqual(self.open_browser.call_count, 4)

    def test_disallowed_schemes(self) -> None:
        for url in ("javascript:alert(1)", "file:///C:/file.txt", "data:text/html,hello", "ftp://example.com", "custom://host"):
            with self.subTest(url=url):
                self.assertEqual(browser.open_url(url).error_id, "UNSUPPORTED_URL_SCHEME")
        self.open_browser.assert_not_called()

    def test_malformed_urls_and_credentials(self) -> None:
        for url in (
            "", "https://", "https:///path", "https://bad host/", "https://user:secret@example.com",
            "https://example.com:99999/", "https://example.com:/", "https://example.com:0/",
            "https://bad_host/", "https://[broken", "https://[::1]evil/", "https://999.999.999.999/",
            "https://example.com/%xx", "https://example.com\\evil", "https://example..com",
            "https://example.com../", "https://example.com/\n", None, 123,
        ):
            with self.subTest(url=url):
                self.assertEqual(browser.open_url(url).error_id, "INVALID_URL")
        self.open_browser.assert_not_called()

    def test_missing_host(self) -> None:
        self.assertEqual(browser.open_url("https:///search").error_id, "INVALID_URL")
        self.open_browser.assert_not_called()

    def test_query_is_encoded_without_parameter_injection(self) -> None:
        query = "C++ & python? #café / windows"
        result = browser.search_web(query)
        self.assertTrue(result.success)
        opened = self.open_browser.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(opened).query), {"q": [query]})
        self.assertEqual(urlsplit(opened).netloc, "www.google.com")
        self.assertEqual(self.open_browser.call_args.kwargs, {"new": 2})

    def test_bad_queries(self) -> None:
        for query in ("", " ", "x" * 2001, "bad\nquery", None):
            self.assertEqual(browser.search_web(query).error_id, "INVALID_ARGUMENT")
        self.open_browser.assert_not_called()

    def test_search_uses_url_validation(self) -> None:
        with patch.object(browser, "SEARCH_URL", "file:///unsafe"):
            self.assertEqual(browser.search_web("query").error_id, "UNSUPPORTED_URL_SCHEME")
        self.open_browser.assert_not_called()

    def test_browser_rejection_and_exception(self) -> None:
        self.open_browser.return_value = False
        self.assertEqual(browser.open_url("https://example.com").error_id, "BROWSER_OPEN_FAILED")
        self.open_browser.side_effect = RuntimeError("sensitive")
        result = browser.open_url("https://example.com")
        self.assertEqual(result.error_id, "TOOL_EXECUTION_FAILED")
        self.assertNotIn("sensitive", result.message)
