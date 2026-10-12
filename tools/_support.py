"""Small shared metadata/error helpers, with no dispatch or authorization."""

from functools import wraps
from typing import Callable, ParamSpec

from core.logging import get_logger
from core.models import ExecutionResult, RiskLevel
from security.validator import ValidationError
from tools.base import ToolMetadata

_P = ParamSpec("_P")
_MESSAGES = {
    "PERMISSION_DENIED": "The action is not permitted by security policy.",
    "CONFIRMATION_REQUIRED": "Trusted user confirmation is required.",
    "CONFIRMATION_NOT_FOUND": "The confirmation is not available.",
    "CONFIRMATION_EXPIRED": "The confirmation has expired; request the action again.",
    "CONFIRMATION_UNAVAILABLE": "A confirmation cannot be created; try again later.",
    "SECURITY_AUDIT_FAILED": "Security audit recording failed; check action state before retrying.",
    "INVALID_TOOL_NAME": "Provide a nonempty tool name string.",
    "TOOL_NOT_FOUND": "The requested tool is not registered.",
    "INVALID_TOOL_ARGUMENTS": "Arguments do not match the tool contract.",
    "INVALID_ARGUMENT": "One or more arguments are invalid.",
    "INVALID_PATH": "Provide an unambiguous local path without parent traversal.",
    "PATH_NOT_FOUND": "The requested path does not exist.",
    "NOT_A_DIRECTORY": "The requested path must be a directory.",
    "DESTINATION_EXISTS": "The destination already exists; nothing was overwritten.",
    "ACCESS_DENIED": "Access to the requested resource was denied.",
    "UNSAFE_PATH": "Links, reparse points, and nonlocal drives are not supported.",
    "UNSUPPORTED_FILE_TYPE": "This file type cannot be opened by this tool.",
    "UNSUPPORTED_PLATFORM": "This operation requires Windows.",
    "CROSS_DEVICE_MOVE": "Moving between volumes is not supported.",
    "INVALID_URL": "Provide a valid HTTP or HTTPS URL without credentials.",
    "UNSUPPORTED_URL_SCHEME": "Only HTTP and HTTPS URLs are supported.",
    "APP_NOT_ALLOWED": "The application alias is not allowed.",
    "APP_NOT_FOUND": "The allowed application was not found in a supported location.",
    "BROWSER_OPEN_FAILED": "The browser launch request was not accepted.",
    "PROCESS_QUERY_FAILED": "The process summary could not be retrieved.",
    "MEMORY_DATABASE_UNAVAILABLE": "Memory storage is currently unavailable.",
    "MEMORY_DATABASE_CORRUPT": "Memory storage is corrupted and cannot be accessed.",
    "MEMORY_RECORD_NOT_FOUND": "The specified memory record was not found.",
    "MEMORY_CAPACITY_EXCEEDED": "Memory storage limit has been reached.",
    "MEMORY_SCHEMA_UNSUPPORTED": "Unsupported memory schema version.",
    "MEMORY_INVALID_RECORD": "Memory fields are invalid or exceed their limits.",
    "MEMORY_CONFLICT": "The memory changed or conflicts with an existing record. Review it again.",
    "MEMORY_STORAGE_FAILED": "The memory operation failed. Check its state before retrying.",
    "SECRET_DETECTED": "Content contains sensitive credentials or secrets and cannot be stored.",
    "TOOL_EXECUTION_FAILED": "The operation could not be completed.",
}


def _failure(error_id: str) -> ExecutionResult:
    return ExecutionResult(False, _MESSAGES[error_id], error_id=error_id)


def _safe_result(operation: Callable[_P, ExecutionResult]) -> Callable[_P, ExecutionResult]:
    """Sanitize errors at direct public operation boundaries; never log inputs."""
    @wraps(operation)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> ExecutionResult:
        try:
            result = operation(*args, **kwargs)
        except ValidationError as error:
            result = _failure(error.error_id)
        except FileExistsError:
            result = _failure("DESTINATION_EXISTS")
        except FileNotFoundError:
            result = _failure("PATH_NOT_FOUND")
        except NotADirectoryError:
            result = _failure("NOT_A_DIRECTORY")
        except PermissionError:
            result = _failure("ACCESS_DENIED")
        except Exception:
            result = _failure("TOOL_EXECUTION_FAILED")
        get_logger(operation.__module__).debug(
            "%s: %s", operation.__name__, result.error_id or "completed"
        )
        return result
    return wrapped


def _metadata(
    name: str,
    description: str,
    risk: RiskLevel,
    properties: dict[str, object] | None = None,
    required: tuple[str, ...] = (),
) -> ToolMetadata:
    return ToolMetadata(name, description, risk, {
        "type": "object", "properties": properties or {},
        "required": list(required), "additionalProperties": False,
    })


def _limit(value: int, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValidationError("INVALID_ARGUMENT")
    return value
