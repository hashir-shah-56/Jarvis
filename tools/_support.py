"""Small shared metadata/error helpers, with no dispatch or authorization."""

from functools import wraps
from typing import Callable, ParamSpec

from core.logging import get_logger
from core.models import ExecutionResult, RiskLevel
from security.validator import ValidationError
from tools.base import ToolMetadata

_P = ParamSpec("_P")
_MESSAGES = {
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
