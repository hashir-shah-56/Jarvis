"""Small, untrusted provider outputs and separate trusted application state."""

from dataclasses import dataclass, field

MAX_TEXT_CHARS = 16000
MAX_ARGUMENT_BYTES = 16384
ERROR_IDS = frozenset({
    "AI_NOT_CONFIGURED", "AI_INVALID_CONFIGURATION", "AI_AUTH_FAILED",
    "AI_RATE_LIMITED", "AI_TIMEOUT", "AI_NETWORK_ERROR", "AI_PROVIDER_ERROR",
    "AI_INVALID_RESPONSE", "AI_MULTIPLE_TOOL_CALLS", "AI_ACTION_LIMIT",
    "AI_INVALID_INPUT",
})


@dataclass(frozen=True, slots=True)
class AssistantText:
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    tool_name: str
    arguments: dict[str, object] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderError:
    error_id: str


ProviderResponse = AssistantText | ToolCallProposal | ProviderError


@dataclass(frozen=True, slots=True)
class ConfirmationRequired:
    tool_name: str
    safe_description: str


@dataclass(frozen=True, slots=True)
class TrustedConfirmation:
    """Application-only capability. Never serialize this into model context."""

    confirmation_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class TurnResult:
    text: str
    error_id: str | None = None
    confirmation: ConfirmationRequired | None = None
    trusted_confirmation: TrustedConfirmation | None = field(default=None, repr=False)
    tool_succeeded: bool | None = None

    @property
    def confirmation_required(self) -> bool:
        return self.confirmation is not None
