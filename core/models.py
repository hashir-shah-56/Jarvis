"""Provider-independent risk and result models; no execution behavior."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class RiskLevel(str, Enum):
    """Declared risk metadata, not an authorization decision."""

    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ExecutionResult:
    """A future tool/controller outcome using sanitized, user-safe content.

    Structured data should contain JSON-compatible values. Callers must avoid
    secrets and raw exception objects/text in both message and data.
    """

    success: bool
    message: str
    data: Mapping[str, object] | None = None
    error_id: str | None = None
