"""Authoritative gateway and separate trusted confirmation interface.

Future model/controller requests may access request_execution only. Confirmation
and rejection are trusted UI responsibilities, never registry tools. This is an
architectural boundary, not a sandbox against malicious local Python code.
"""

import math
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Lock

from agent.permissions import PermissionDecision
from core.models import ExecutionResult
from security.audit import AuditError, AuditEvent, AuditTrail, _DEFAULT_AUDIT
from security.permissions import evaluate_permission
from security.policies import DEFAULT_POLICY, PermissionPolicy
from tools._execution import _PreparedTool, _invoke_tool, _prepare_tool
from tools._support import _failure
from tools.registry import REGISTRY, ToolRegistry

CONFIRMATION_TTL_SECONDS = 300
_MAX_PENDING = 128


@dataclass(frozen=True)
class _PendingConfirmation:
    action: _PreparedTool = field(repr=False)
    expires_at: float


class SecurityGateway:
    """Trusted setup object with isolated, synchronized pending state.

    Registry, policy, audit destination, and clock are setup dependencies, never
    request parameters. Production confirmation TTL is fixed at five minutes.
    """

    def __init__(
        self, *, registry: ToolRegistry = REGISTRY,
        policy: PermissionPolicy = DEFAULT_POLICY, audit: AuditTrail | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._audit = audit if audit is not None else AuditTrail()
        self._clock = clock
        self._pending: dict[str, _PendingConfirmation] = {}
        self._lock = Lock()
        self._last_time = float("-inf")

    def _now(self) -> float:
        """Called under the state lock; a broken/backwards clock fails closed."""
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self._last_time:
            raise ValueError("INVALID_CONFIRMATION_CLOCK")
        self._last_time = now
        return now

    def _decision(self, action: _PreparedTool) -> PermissionDecision:
        try:
            decision = evaluate_permission(action.tool.metadata, self._policy)
            return decision if type(decision) is PermissionDecision else PermissionDecision.DENY
        except Exception:
            return PermissionDecision.DENY

    def _denied(self, action: _PreparedTool) -> ExecutionResult:
        self._audit.record(AuditEvent.PERMISSION_DENIED, action.tool.metadata,
                           PermissionDecision.DENY, "PERMISSION_DENIED")
        return _failure("PERMISSION_DENIED")

    def _execute(self, action: _PreparedTool, decision: PermissionDecision) -> ExecutionResult:
        self._audit.record(AuditEvent.EXECUTION_ATTEMPTED, action.tool.metadata, decision)
        result = _invoke_tool(action)
        event = AuditEvent.EXECUTION_COMPLETED if result.success is True else AuditEvent.EXECUTION_FAILED
        self._audit.record(event, action.tool.metadata, decision, result.error_id)
        return result

    def _store(self, action: _PreparedTool) -> ExecutionResult:
        with self._lock:
            now = self._now()
            # Discard expired arguments on new sensitive requests. No background
            # thread or unbounded replay/tombstone history is needed.
            for identifier, pending in list(self._pending.items()):
                if now >= pending.expires_at:
                    del self._pending[identifier]
                    self._audit.record(AuditEvent.CONFIRMATION_EXPIRED,
                                       pending.action.tool.metadata,
                                       PermissionDecision.REQUIRE_CONFIRMATION,
                                       "CONFIRMATION_EXPIRED")
            if len(self._pending) >= _MAX_PENDING:
                return _failure("CONFIRMATION_UNAVAILABLE")
            for _ in range(3):
                identifier = secrets.token_urlsafe(32)
                if identifier not in self._pending:
                    break
            else:
                return _failure("CONFIRMATION_UNAVAILABLE")
            self._audit.record(AuditEvent.CONFIRMATION_REQUIRED, action.tool.metadata,
                               PermissionDecision.REQUIRE_CONFIRMATION, "CONFIRMATION_REQUIRED")
            self._pending[identifier] = _PendingConfirmation(action, now + CONFIRMATION_TTL_SECONDS)
        metadata = action.tool.metadata
        return ExecutionResult(False, "Trusted user confirmation is required.", {
            "confirmation_id": identifier,
            "tool_name": metadata.name,
            "description": metadata.description,
            "risk_level": metadata.risk_level.value,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
        }, "CONFIRMATION_REQUIRED")

    def request_execution(self, tool_name: str, arguments: Mapping[str, object]) -> ExecutionResult:
        """Validate, decide, then execute or create one exact pending action."""
        try:
            action = _prepare_tool(tool_name, arguments, self._registry)
            if isinstance(action, ExecutionResult):
                self._audit.record(AuditEvent.REQUEST_REJECTED, error_id=action.error_id)
                return action
            decision = self._decision(action)
            if decision is PermissionDecision.DENY:
                return self._denied(action)
            if decision is PermissionDecision.REQUIRE_CONFIRMATION:
                return self._store(action)
            self._audit.record(AuditEvent.REQUEST_ALLOWED, action.tool.metadata, decision)
            return self._execute(action, decision)
        except AuditError:
            return _failure("SECURITY_AUDIT_FAILED")
        except Exception:
            return _failure("TOOL_EXECUTION_FAILED")

    def _take(self, confirmation_id: str) -> _PendingConfirmation | ExecutionResult:
        """Consume atomically before any authorization check or execution attempt."""
        pending = None
        if type(confirmation_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{43}", confirmation_id):
            with self._lock:
                pending = self._pending.pop(confirmation_id, None)
                if pending is not None and self._now() >= pending.expires_at:
                    self._audit.record(AuditEvent.CONFIRMATION_EXPIRED,
                                       pending.action.tool.metadata,
                                       PermissionDecision.REQUIRE_CONFIRMATION,
                                       "CONFIRMATION_EXPIRED")
                    return _failure("CONFIRMATION_EXPIRED")
        if pending is None:
            self._audit.record(AuditEvent.CONFIRMATION_INVALID, error_id="CONFIRMATION_NOT_FOUND")
            return _failure("CONFIRMATION_NOT_FOUND")
        return pending

    def confirm_execution(self, confirmation_id: str) -> ExecutionResult:
        """Trusted UI only: approve the stored action, never replacements.

        The ID is consumed even if policy, auditing, or the operation later fails.
        This API must never be offered to a model as a callable tool.
        """
        try:
            pending = self._take(confirmation_id)
            if isinstance(pending, ExecutionResult):
                return pending
            action = pending.action
            if self._decision(action) is PermissionDecision.DENY:
                return self._denied(action)
            decision = PermissionDecision.REQUIRE_CONFIRMATION
            self._audit.record(AuditEvent.CONFIRMATION_ACCEPTED, action.tool.metadata, decision)
            return self._execute(action, decision)
        except AuditError:
            return _failure("SECURITY_AUDIT_FAILED")
        except Exception:
            return _failure("TOOL_EXECUTION_FAILED")

    def reject_confirmation(self, confirmation_id: str) -> ExecutionResult:
        """Trusted UI only: discard a pending action without invoking it."""
        try:
            pending = self._take(confirmation_id)
            if isinstance(pending, ExecutionResult):
                return pending
            self._audit.record(AuditEvent.CONFIRMATION_REJECTED,
                               pending.action.tool.metadata, PermissionDecision.DENY)
            return ExecutionResult(True, "Pending action rejected.")
        except AuditError:
            return _failure("SECURITY_AUDIT_FAILED")
        except Exception:
            return _failure("TOOL_EXECUTION_FAILED")


_DEFAULT_GATEWAY = SecurityGateway(audit=_DEFAULT_AUDIT)


def request_execution(tool_name: str, arguments: Mapping[str, object]) -> ExecutionResult:
    """Public request boundary; future controller/model requests must enter here."""
    return _DEFAULT_GATEWAY.request_execution(tool_name, arguments)


def confirm_execution(confirmation_id: str) -> ExecutionResult:
    """Trusted user-interface boundary, never an LLM tool."""
    return _DEFAULT_GATEWAY.confirm_execution(confirmation_id)


def reject_confirmation(confirmation_id: str) -> ExecutionResult:
    """Trusted user-interface cancellation, never an LLM tool."""
    return _DEFAULT_GATEWAY.reject_confirmation(confirmation_id)
