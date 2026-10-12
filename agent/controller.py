"""Synchronous bounded state machine. Only Stage 4 may authorize an action."""

import hashlib
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from threading import RLock

from agent.models import ActionReview, TaskResult, TurnStatus
from agent.planner import Planner
from ai.models import AssistantText, MAX_TEXT_CHARS, ProviderError
from config import agent_settings as limits
from core.logging import get_logger
from security import gateway
from tools.registry import REGISTRY
from tools.schema import validate_arguments


def _event(name):
    try:
        get_logger("controller").debug(name)
    except Exception:
        pass


@dataclass(repr=False)
class _Turn:
    planner: Planner
    status: TurnStatus = TurnStatus.RUNNING
    provider_calls: int = 0
    tool_actions: int = 0
    completed_actions: int = 0
    fingerprints: set[str] = field(default_factory=set)
    confirmation_id: str | None = None
    review: ActionReview | None = None
    expires_at: float = 0


def _transition(turn, status):
    allowed = {
        TurnStatus.RUNNING: set(TurnStatus) - {TurnStatus.RUNNING},
        TurnStatus.WAITING_FOR_CONFIRMATION: {
            TurnStatus.RUNNING, TurnStatus.CANCELLED, TurnStatus.FAILED, TurnStatus.DENIED,
        },
    }
    if status not in allowed.get(turn.status, set()):
        raise ValueError("CONTROLLER_STATE_FAILED")
    turn.status = status


class Controller:
    """One instance owns at most 32 paused turns; operations serialize under a lock."""

    def __init__(self, provider):
        self._provider = provider
        self._pending = {}
        self._lock = RLock()
        self._last_time = float("-inf")
        self._closed = False

    def _now(self):
        now = time.monotonic()
        if not math.isfinite(now) or now < self._last_time:
            raise ValueError("CONTROLLER_STATE_FAILED")
        self._last_time = now
        return now

    def _discard(self, turn):
        if turn.confirmation_id is not None:
            identifier, turn.confirmation_id = turn.confirmation_id, None
            try:
                gateway.reject_confirmation(identifier)
            except Exception:
                pass
        turn.planner.close()

    def _end(self, turn, status, text, error=None, kind=None):
        _transition(turn, status)
        self._discard(turn)
        _event("turn_completed" if status is TurnStatus.COMPLETED else "turn_failed")
        return TaskResult(status, text, error, kind, turn.provider_calls,
                          turn.tool_actions, turn.completed_actions)

    def _broken(self, turn=None):
        if turn is not None:
            self._discard(turn)
        _event("turn_failed")
        return TaskResult(TurnStatus.FAILED, "The controller stopped safely. Check action state before retrying.",
                          "CONTROLLER_STATE_FAILED", "controller_state",
                          turn.provider_calls if turn else 0, turn.tool_actions if turn else 0,
                          turn.completed_actions if turn else 0)

    def _purge(self):
        now = self._now()
        for identifier, turn in list(self._pending.items()):
            if now >= turn.expires_at:
                del self._pending[identifier]
                self._discard(turn)

    def run_turn(self, text):
        with self._lock:
            turn = None
            try:
                if self._closed:
                    return self._broken()
                self._purge()
                if type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARS:
                    return TaskResult(TurnStatus.FAILED, "Enter a nonempty request within the text limit.",
                                      "AI_INVALID_INPUT", "invalid_input")
                turn = _Turn(Planner(self._provider, text))
                _event("turn_started")
                return self._drive(turn)
            except (KeyboardInterrupt, EOFError):
                if turn is not None:
                    self._discard(turn)
                raise
            except Exception:
                # A broken clock or bookkeeping cannot leave resumable state.
                self._clear_pending()
                return self._broken(turn)

    def _fingerprint(self, proposal):
        # Metadata-only lookup for progress detection, never authorization.
        metadata = next((item for item in REGISTRY.list_metadata()
                         if item["name"] == proposal.tool_name), None)
        if metadata is None:
            return None, None
        try:
            args = validate_arguments(proposal.arguments, metadata["arguments_schema"])
        except ValueError:
            return None, None  # Let Stage 4 reject/audit the original invalid request.
        canonical = dict(args)
        for key, definition in metadata["arguments_schema"]["properties"].items():
            if key not in canonical and "default" in definition:
                canonical[key] = definition["default"]
        encoded = json.dumps([proposal.tool_name, canonical], sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), args

    def _pause(self, turn, result, args, requested_at):
        turn.confirmation_id = result.data["confirmation_id"]
        if args is None:
            return self._broken(turn)
        if len(self._pending) >= limits.MAX_PENDING_TURNS:
            return self._end(turn, TurnStatus.FAILED, "Too many turns are awaiting confirmation.",
                             "PENDING_TURN_LIMIT_REACHED", "controller_state")
        for _ in range(3):
            identifier = secrets.token_urlsafe(24)
            if identifier not in self._pending:
                break
        else:
            return self._broken(turn)
        turn.review = ActionReview(result.data["tool_name"], result.data["description"],
                                   result.data["risk_level"], json.dumps(args, sort_keys=True, ensure_ascii=True))
        turn.expires_at = requested_at + limits.PENDING_TURN_TTL_SECONDS
        _transition(turn, TurnStatus.WAITING_FOR_CONFIRMATION)
        self._pending[identifier] = turn
        _event("turn_paused")
        return TaskResult(turn.status, "This action requires trusted user confirmation.",
                          "CONFIRMATION_REQUIRED", "confirmation_required", turn.provider_calls,
                          turn.tool_actions, turn.completed_actions, identifier, turn.review)

    def _failed_action(self, turn, result):
        error = result.error_id
        if error == "PERMISSION_DENIED":
            return self._end(turn, TurnStatus.DENIED, "The action was denied. The task has stopped.",
                             error, "permission_denial")
        if error in {"CONFIRMATION_EXPIRED", "CONFIRMATION_NOT_FOUND"}:
            return self._end(turn, TurnStatus.FAILED, "Authorization expired or is no longer available. Submit a new request if needed.",
                             error, "confirmation_expired")
        kind = "invalid_tool_proposal" if error in {"TOOL_NOT_FOUND", "INVALID_TOOL_NAME", "INVALID_TOOL_ARGUMENTS"} else "tool_execution"
        return self._end(turn, TurnStatus.FAILED, "The action failed. Check action state before retrying; no retry was attempted.",
                         error or "TOOL_EXECUTION_FAILED", kind)

    def _drive(self, turn):
        while turn.status is TurnStatus.RUNNING:
            if turn.tool_actions >= limits.MAX_TOOL_ACTIONS_PER_TURN:
                _event("limit_reached")
                return self._end(turn, TurnStatus.ACTION_LIMIT_REACHED, "The action limit was reached. The task has stopped.",
                                 "ACTION_LIMIT_REACHED", "action_limit")
            if turn.provider_calls >= limits.MAX_PROVIDER_CALLS_PER_TURN:
                _event("limit_reached")
                return self._end(turn, TurnStatus.PROVIDER_LIMIT_REACHED, "The provider-call limit was reached. The task has stopped.",
                                 "PROVIDER_CALL_LIMIT_REACHED", "provider_limit")
            turn.provider_calls += 1
            response = turn.planner.next_step()
            if isinstance(response, AssistantText):
                return self._end(turn, TurnStatus.COMPLETED, response.text)
            if isinstance(response, ProviderError):
                kind = "invalid_model_response" if response.error_id in {"AI_INVALID_RESPONSE", "AI_MULTIPLE_TOOL_CALLS"} else "provider"
                return self._end(turn, TurnStatus.FAILED, "The AI request failed. The task has stopped.", response.error_id, kind)
            fingerprint, args = self._fingerprint(response)
            if fingerprint is not None and fingerprint in turn.fingerprints:
                return self._end(turn, TurnStatus.FAILED, "A repeated action was blocked. The task has stopped.",
                                 "REPEATED_ACTION", "repeated_action")
            if fingerprint is not None:
                turn.fingerprints.add(fingerprint)
            turn.tool_actions += 1
            _event("tool_proposed")
            requested_at = self._now()
            result = gateway.request_execution(response.tool_name, response.arguments)
            if result.error_id == "CONFIRMATION_REQUIRED":
                return self._pause(turn, result, args, requested_at)
            if result.success is not True or result.error_id is not None:
                return self._failed_action(turn, result)
            turn.completed_actions += 1
            _event("tool_completed")
            turn.planner.observe(result)
        return self._broken(turn)

    def _resume(self, identifier, approve):
        with self._lock:
            turn = None
            try:
                if type(identifier) is not str or len(identifier) != 32:
                    return self._missing()
                turn = self._pending.pop(identifier, None)  # Consume before any action.
                if turn is None:
                    return self._missing()
                if turn.status is not TurnStatus.WAITING_FOR_CONFIRMATION or not turn.confirmation_id:
                    return self._broken(turn)
                if self._now() >= turn.expires_at:
                    return self._end(turn, TurnStatus.FAILED, "Authorization expired. Submit a new request if needed.",
                                     "CONFIRMATION_EXPIRED", "confirmation_expired")
                confirmation_id, turn.confirmation_id = turn.confirmation_id, None
                if not approve:
                    result = gateway.reject_confirmation(confirmation_id)
                    if not result.success:
                        return self._failed_action(turn, result)
                    return self._end(turn, TurnStatus.CANCELLED, "The action was cancelled. The task has stopped.",
                                     "TURN_CANCELLED", "cancelled")
                result = gateway.confirm_execution(confirmation_id)
                if result.success is not True or result.error_id is not None:
                    return self._failed_action(turn, result)
                turn.completed_actions += 1
                _transition(turn, TurnStatus.RUNNING)
                turn.review = None
                _event("turn_resumed")
                turn.planner.observe(result)
                return self._drive(turn)
            except (KeyboardInterrupt, EOFError):
                if turn is not None:
                    self._discard(turn)
                raise
            except Exception:
                self._clear_pending()
                return self._broken(turn)

    def _missing(self):
        return TaskResult(TurnStatus.FAILED, "No pending turn is available.", "TURN_NOT_FOUND", "controller_state")

    def confirm_turn(self, turn_id):
        """Trusted UI only, after explicit approval of the displayed exact action."""
        return self._resume(turn_id, True)

    def reject_turn(self, turn_id):
        """Trusted UI only; cancel, without inviting the model to work around it."""
        return self._resume(turn_id, False)

    def _clear_pending(self):
        pending, self._pending = self._pending, {}
        for turn in pending.values():
            self._discard(turn)

    def close(self):
        with self._lock:
            self._closed = True
            self._clear_pending()
