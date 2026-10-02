"""Permission vocabulary only; policy evaluation/enforcement arrive in Stage 4.

READ_ONLY and LOW normally allow automatic approval. MEDIUM may require
confirmation depending on future configuration. HIGH requires explicit user
confirmation. These are planned defaults, not active grants. The controller
must enforce decisions independently of any LLM; unknown decisions deny.
"""

from enum import Enum


class PermissionDecision(str, Enum):
    """Possible future permission outcomes, never self-issued by the LLM."""

    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"
