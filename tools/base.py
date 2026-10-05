"""Provider-independent metadata for deterministic tools and their registry."""

from dataclasses import dataclass
from typing import Mapping

from core.models import RiskLevel


@dataclass(frozen=True)
class ToolMetadata:
    """Describe a tool independently of any LLM provider.

    name is unique in the registry. arguments_schema describes arguments using
    the JSON Schema subset validated by the Stage 3 executor. Stage 2 operations
    return core.models.ExecutionResult.
    Metadata alone never authorizes execution.
    """

    name: str
    description: str
    risk_level: RiskLevel
    arguments_schema: Mapping[str, object]
