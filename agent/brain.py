"""One user turn, at most one action, and no autonomous planning or retries."""

from ai.base import Provider
from ai.models import (
    AssistantText, ConfirmationRequired, MAX_TEXT_CHARS, ProviderError,
    ToolCallProposal, TrustedConfirmation, TurnResult,
)
from ai.sanitize import sanitize_result
from ai.validation import validate_response
from core.logging import get_logger
from security import gateway


def _event(name: str) -> None:
    try:
        get_logger("ai").debug(name)
    except Exception:
        pass  # Operational logging is separate from mandatory Stage 4 audit.


def _failure(error_id: str, tool_succeeded=None) -> TurnResult:
    _event("provider_error")
    text = "The AI request could not be completed."
    if tool_succeeded:
        text = "The tool succeeded, but the AI final response is unavailable."
    return TurnResult(text, error_id=error_id, tool_succeeded=tool_succeeded)


class Brain:
    def __init__(self, provider: Provider):
        self._provider = provider

    def run_turn(self, user_text: str) -> TurnResult:
        if type(user_text) is not str or not user_text.strip() or len(user_text) > MAX_TEXT_CHARS:
            return _failure("AI_INVALID_INPUT")
        tool_succeeded = None
        try:
            with self._provider.turn(user_text) as turn:
                _event("provider_request_started")
                response = validate_response(turn.propose())
                _event("provider_request_completed")
                if isinstance(response, AssistantText):
                    return TurnResult(response.text)
                if isinstance(response, ProviderError):
                    return _failure(response.error_id)
                _event("provider_tool_proposed")
                result = gateway.request_execution(response.tool_name, response.arguments)
                if result.error_id == "CONFIRMATION_REQUIRED":
                    data = result.data
                    return TurnResult(
                        "Trusted user confirmation is required. No action was executed.",
                        error_id="CONFIRMATION_REQUIRED",
                        confirmation=ConfirmationRequired(data["tool_name"], data["description"]),
                        trusted_confirmation=TrustedConfirmation(data["confirmation_id"]),
                        tool_succeeded=False,
                    )
                if result.success is not True or result.error_id is not None:
                    return TurnResult(
                        "The requested action could not be completed. Check action state before retrying.",
                        error_id=result.error_id, tool_succeeded=False,
                    )
                tool_succeeded = True
                _event("provider_request_started")
                final = validate_response(turn.finish(sanitize_result(result)))
                _event("provider_request_completed")
                if isinstance(final, AssistantText):
                    return TurnResult(final.text, tool_succeeded=True)
                if isinstance(final, ToolCallProposal):
                    return _failure("AI_ACTION_LIMIT", True)
                return _failure(final.error_id, True)
        except TimeoutError:
            return _failure("AI_TIMEOUT", tool_succeeded)
        except Exception:
            return _failure("AI_PROVIDER_ERROR", tool_succeeded)
