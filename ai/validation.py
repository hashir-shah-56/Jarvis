"""Validate provider contract shapes, without granting authority."""

import json
import math

from ai.models import (
    AssistantText, ERROR_IDS, MAX_ARGUMENT_BYTES, MAX_TEXT_CHARS,
    ProviderError, ProviderResponse, ToolCallProposal,
)


def snapshot_arguments(value: object) -> dict[str, object]:
    """Reject non-JSON objects, excessive nesting/items and coercible types."""
    remaining = 256

    def check(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 6:
            raise ValueError("AI_INVALID_RESPONSE")
        if item is None or type(item) in (bool, int):
            return
        if type(item) is str and len(item) <= MAX_ARGUMENT_BYTES:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is dict and len(item) <= 50:
            for key, child in item.items():
                if type(key) is not str or len(key) > 128:
                    raise ValueError("AI_INVALID_RESPONSE")
                check(child, depth + 1)
            return
        if type(item) is list and len(item) <= 50:
            for child in item:
                check(child, depth + 1)
            return
        raise ValueError("AI_INVALID_RESPONSE")

    if type(value) is not dict:
        raise ValueError("AI_INVALID_RESPONSE")
    check(value)
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ValueError("AI_INVALID_RESPONSE")
    return json.loads(encoded)


def validate_response(value: object) -> ProviderResponse:
    try:
        if type(value) is AssistantText:
            if type(value.text) is str and value.text.strip() and len(value.text) <= MAX_TEXT_CHARS:
                return value
        elif type(value) is ToolCallProposal:
            if type(value.tool_name) is str and 0 < len(value.tool_name) <= 128:
                return ToolCallProposal(value.tool_name, snapshot_arguments(value.arguments))
        elif type(value) is ProviderError:
            if type(value.error_id) is str and value.error_id in ERROR_IDS:
                return value
    except Exception:
        pass
    return ProviderError("AI_INVALID_RESPONSE")
