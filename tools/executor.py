"""Supported execution API: always enter the Stage 4 permission gateway."""

from collections.abc import Mapping

from core.models import ExecutionResult
from security.gateway import request_execution


def execute_tool(tool_name: str, arguments: Mapping[str, object]) -> ExecutionResult:
    """Request an action; sensitive tools return CONFIRMATION_REQUIRED.

    No confirmation flag, risk override, callable, or replacement registry is
    accepted. Approval belongs to the separate trusted interface API.
    """
    return request_execution(tool_name, arguments)
