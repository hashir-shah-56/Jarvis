"""Shared permission vocabulary; Stage 4 enforcement lives in security/."""

from enum import Enum


class PermissionDecision(str, Enum):
    """Security policy outcomes, never self-issued by an LLM."""

    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"
