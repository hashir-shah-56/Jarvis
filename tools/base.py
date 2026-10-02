"""Provider-independent metadata for direct-call tools and a future registry."""

from dataclasses import dataclass
from typing import Mapping

from core.models import RiskLevel


@dataclass(frozen=True)
class ToolMetadata:
    """Describe a tool independently of any LLM provider.

    name must be unique in the future registry. arguments_schema describes
    arguments using JSON Schema; validation and uniqueness enforcement belong
    to later stages. Stage 2 operations return core.models.ExecutionResult.
    Metadata alone never authorizes execution.
    """

    name: str
    description: str
    risk_level: RiskLevel
    arguments_schema: Mapping[str, object]
