"""Validated default-browser opening only; no scraping or browser automation."""

import webbrowser
from urllib.parse import urlencode

from config.tool_settings import SEARCH_URL
from core.models import ExecutionResult, RiskLevel
from security.validator import ValidationError, validate_url
from tools._support import _metadata, _safe_result

OPEN_URL_METADATA = _metadata("browser.open_url", "Request the default browser to open an HTTP(S) URL without embedded credentials.", RiskLevel.LOW, {"url": {"type": "string", "minLength": 1, "maxLength": 8192}}, ("url",))
SEARCH_WEB_METADATA = _metadata("browser.search_web", "Open an encoded query with the configured search provider; do not retrieve results.", RiskLevel.LOW, {"query": {"type": "string", "minLength": 1, "maxLength": 2000}}, ("query",))


@_safe_result
def open_url(url: str) -> ExecutionResult:
    validated = validate_url(url)
    if not webbrowser.open(validated, new=2):
        raise ValidationError("BROWSER_OPEN_FAILED")
    return ExecutionResult(True, "Browser launch requested; page loading is not verified.", {
        "launch_requested": True,
    })


@_safe_result
def search_web(query: str) -> ExecutionResult:
    if (
        not isinstance(query, str) or not query.strip() or len(query) > 2000
        or any(ord(char) < 32 or ord(char) == 127 for char in query)
    ):
        raise ValidationError("INVALID_ARGUMENT")
    return open_url(f"{SEARCH_URL}?{urlencode({'q': query})}")
