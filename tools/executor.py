"""Standard execution for controlled Python callers only; no permission engine.

Risk metadata is descriptive and is never used to authorize or prompt. There is
no LLM/controller integration, callable injection, or dynamic tool resolution.
"""

from collections.abc import Mapping

from core.logging import get_logger
from core.models import ExecutionResult
from tools._support import _failure
from tools.registry import REGISTRY
from tools.schema import ArgumentValidationError, validate_arguments


def _rejected(error_id: str) -> ExecutionResult:
    get_logger("tools.executor").debug("execution rejected: %s", error_id)
    return _failure(error_id)


def execute_tool(tool_name: str, arguments: Mapping[str, object]) -> ExecutionResult:
    """Resolve, validate, then invoke exactly one allowlisted Stage 2 operation.

    Pass an empty mapping for zero-argument calls. All ordinary internal failures
    are sanitized, including lookup, validation, invocation, and result failures.
    Existing Stage 2 validation and its safe-result wrapper remain in force.
    """
    try:
        if type(tool_name) is not str or not tool_name:
            return _rejected("INVALID_TOOL_NAME")
        tool = REGISTRY.get(tool_name)
        if tool is None:
            return _rejected("TOOL_NOT_FOUND")
        try:
            validated = validate_arguments(arguments, tool.metadata.arguments_schema)
        except ArgumentValidationError:
            return _rejected("INVALID_TOOL_ARGUMENTS")
        result = tool.implementation(**validated)
        if not isinstance(result, ExecutionResult):
            return _rejected("TOOL_EXECUTION_FAILED")
        get_logger("tools.executor").debug("execution completed")
        return result
    except Exception:
        # Do not echo exceptions, argument values, names, or unexpected results.
        return _failure("TOOL_EXECUTION_FAILED")
