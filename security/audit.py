"""Bounded security records, separate from application logging; never arguments.

Default records are in memory. Trusted setup may opt into an append-only JSONL
file. Neither mode is tamper-resistant; local Python/filesystem access is trusted.
"""

import json
import re
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock

from agent.permissions import PermissionDecision
from core.models import RiskLevel
from tools._support import _MESSAGES
from tools.base import ToolMetadata


class AuditEvent(str, Enum):
    REQUEST_REJECTED = "request_rejected"
    REQUEST_ALLOWED = "request_allowed"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_ACCEPTED = "confirmation_accepted"
    CONFIRMATION_REJECTED = "confirmation_rejected"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    CONFIRMATION_INVALID = "confirmation_invalid"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"


class AuditError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("SECURITY_AUDIT_FAILED")


@dataclass(frozen=True)
class _AuditRecord:
    timestamp: str
    event: str
    tool_name: str | None
    risk_level: str | None
    decision: str | None
    error_id: str | None


class AuditTrail:
    """Keep the latest 1,000 sanitized events and optionally append JSONL.

    File paths are trusted configuration, never request input. Parent directories
    must already exist. No file is opened at import or construction time.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._records: deque[_AuditRecord] = deque(maxlen=1000)
        self._lock = Lock()

    def record(
        self, event: AuditEvent, metadata: ToolMetadata | None = None,
        decision: PermissionDecision | None = None, error_id: str | None = None,
    ) -> None:
        """Accept fixed vocabulary and trusted metadata, never arbitrary fields."""
        try:
            if type(event) is not AuditEvent:
                raise AuditError()
            name = risk = None
            if type(metadata) is ToolMetadata:
                if type(metadata.name) is str and re.fullmatch(
                    r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", metadata.name,
                ):
                    name = metadata.name
                if type(metadata.risk_level) is RiskLevel:
                    risk = metadata.risk_level.value
            record = _AuditRecord(
                datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                event.value, name, risk,
                decision.value if type(decision) is PermissionDecision else None,
                error_id if type(error_id) is str and error_id in _MESSAGES else None,
            )
            with self._lock:
                self._records.append(record)
                if self._path is not None:
                    with self._path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(asdict(record)) + "\n")
        except Exception:
            raise AuditError() from None

    def snapshot(self) -> list[dict[str, object]]:
        """Detached JSON-compatible records without confirmation IDs or values."""
        with self._lock:
            return [asdict(record) for record in self._records]


_DEFAULT_AUDIT = AuditTrail()


def get_audit_records() -> list[dict[str, object]]:
    """Review the default gateway's recent in-process security audit events."""
    return _DEFAULT_AUDIT.snapshot()
