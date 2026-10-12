"""Deterministic accumulated feedback bounds, independent of SDK types."""

import json

from config import agent_settings as limits


def bound_feedback(feedback: list[dict[str, object]]) -> list[dict[str, object]]:
    """Retain success markers; discard oldest payloads until the byte budget fits."""
    result = json.loads(json.dumps(feedback, allow_nan=False))
    for item in result:
        if len(json.dumps(result).encode("utf-8")) <= limits.MAX_FEEDBACK_BYTES:
            break
        item.update(data=None, truncated=True)
    if len(json.dumps(result).encode("utf-8")) > limits.MAX_FEEDBACK_BYTES:
        raise ValueError("AI_CONTEXT_LIMIT")
    return result
