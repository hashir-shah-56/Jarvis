"""Bounded JSON-only tool feedback. Never use arbitrary object representations."""

import json
import math

from core.models import ExecutionResult

MAX_RESULT_BYTES = 16384
MAX_DEPTH = 6
MAX_ITEMS = 50
MAX_NODES = 256
MAX_STRING_CHARS = 1024
_PRIVATE_KEYS = frozenset({
    "confirmation_id", "api_key", "gemini_api_key", "authorization",
    "headers", "credentials", "password", "secret", "token",
})


def sanitize_result(result: ExecutionResult) -> dict[str, object]:
    """Only successful data is eligible; failures/pending state are never copied."""
    truncated = False
    nodes = 0

    def clean(value, depth=0):
        nonlocal truncated, nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            truncated = True
            return None
        if value is None or type(value) is bool:
            return value
        if type(value) is int and value.bit_length() <= 128:
            return value
        if type(value) is float and math.isfinite(value):
            return value
        if type(value) is str:
            truncated |= len(value) > MAX_STRING_CHARS
            return value[:MAX_STRING_CHARS]
        if type(value) in (dict, list):
            output = {} if type(value) is dict else []
            truncated |= len(value) > MAX_ITEMS
            items = value.items() if type(value) is dict else enumerate(value)
            for index, (key, child) in enumerate(items):
                if index >= MAX_ITEMS or nodes >= MAX_NODES:
                    truncated = True
                    break
                if type(output) is dict:
                    if type(key) is not str or len(key) > 128 or key.lower() in _PRIVATE_KEYS:
                        truncated = True
                        continue
                    output[key] = clean(child, depth + 1)
                else:
                    output.append(clean(child, depth + 1))
            return output
        truncated = True
        return None

    success = result.success is True and result.error_id is None
    data = clean(result.data) if success else None
    output = {"success": success, "data": data, "truncated": truncated}
    if len(json.dumps(output, allow_nan=False).encode("utf-8")) > MAX_RESULT_BYTES:
        output.update(data=None, truncated=True)
    return output
