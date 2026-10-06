"""Internal Stage 3 machinery: only the security gateway may invoke tools.

These primitives do not authorize actions and must not be exposed to a model or
controller. Preparation snapshots the binding and schema-approved arguments.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from core.logging import get_logger
from core.models import ExecutionResult
from tools._support import _failure
from tools.registry import RegisteredTool, ToolRegistry
from tools.schema import ArgumentValidationError, validate_arguments


@dataclass(frozen=True)
class _PreparedTool:
    tool: RegisteredTool = field(repr=False)
    arguments_json: str = field(repr=False)


def _rejected(error_id: str) -> ExecutionResult:
    get_logger("tools.executor").debug("execution rejected: %s", error_id)
    return _failure(error_id)


def _prepare_tool(
    tool_name: str, arguments: Mapping[str, object], registry: ToolRegistry,
) -> _PreparedTool | ExecutionResult:
    """Resolve and validate without invoking; snapshot only approved JSON."""
    try:
        if type(tool_name) is not str or not tool_name:
            return _rejected("INVALID_TOOL_NAME")
        tool = registry.get(tool_name)
        if tool is None:
            return _rejected("TOOL_NOT_FOUND")
        try:
            validated = validate_arguments(arguments, tool.metadata.arguments_schema)
        except ArgumentValidationError:
            return _rejected("INVALID_TOOL_ARGUMENTS")
        # Validation rebuilds nested objects and rejects arbitrary Python values.
        # Immutable JSON separates pending actions from all caller-held references.
        # Optional defaults deliberately remain omitted.
        return _PreparedTool(tool, json.dumps(validated, allow_nan=False))
    except Exception:
        return _failure("TOOL_EXECUTION_FAILED")


def _invoke_tool(prepared: _PreparedTool) -> ExecutionResult:
    """Invoke the stored binding after authorization, retaining Stage 2 checks."""
    try:
        result = prepared.tool.implementation(**json.loads(prepared.arguments_json))
        if not isinstance(result, ExecutionResult):
            return _rejected("TOOL_EXECUTION_FAILED")
        get_logger("tools.executor").debug("execution completed")
        return result
    except Exception:
        return _failure("TOOL_EXECUTION_FAILED")
