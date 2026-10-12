"""Detached application outcomes and explicit controller states."""

from dataclasses import dataclass, field
from enum import Enum


class TurnStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    FAILED = "FAILED"
    ACTION_LIMIT_REACHED = "ACTION_LIMIT_REACHED"
    PROVIDER_LIMIT_REACHED = "PROVIDER_LIMIT_REACHED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ActionReview:
    tool_name: str
    description: str
    risk: str
    arguments_json: str = field(repr=False)


@dataclass(frozen=True)
class TaskResult:
    status: TurnStatus
    text: str = field(repr=False)
    error_id: str | None = None
    failure_kind: str | None = None
    provider_calls: int = 0
    tool_actions: int = 0
    completed_actions: int = 0
    turn_id: str | None = field(default=None, repr=False)
    confirmation: ActionReview | None = None

    @property
    def confirmation_required(self) -> bool:
        return self.status is TurnStatus.WAITING_FOR_CONFIRMATION
