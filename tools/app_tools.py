"""Allowlisted Windows app launching using native ShellExecute via startfile."""

import os
from pathlib import Path
from subprocess import list2cmdline

from config.tool_settings import APPLICATION_LOCATIONS
from core.models import ExecutionResult, RiskLevel
from security.validator import ValidationError, validate_local_path
from tools._support import _metadata, _safe_result

OPEN_APPLICATION_METADATA = _metadata("app.open_application", "Request launch of a centrally allowlisted Windows application.", RiskLevel.LOW, {"alias": {"type": "string", "enum": list(APPLICATION_LOCATIONS)}}, ("alias",))
OPEN_PROJECT_IN_VSCODE_METADATA = _metadata("app.open_project_in_vscode", "Open an existing local project directory in VS Code with extensions disabled.", RiskLevel.LOW, {"path": {"type": "string", "minLength": 1}}, ("path",))


def _find_application(alias: str) -> Path:
    for variable, relative in APPLICATION_LOCATIONS[alias]:
        root = os.environ.get(variable)
        if not root or not Path(root).is_absolute():
            continue
        try:
            candidate = validate_local_path(Path(root) / relative)
        except FileNotFoundError:
            continue
        if candidate.is_file():
            return candidate
    raise ValidationError("APP_NOT_FOUND")


@_safe_result
def open_application(alias: str) -> ExecutionResult:
    if not isinstance(alias, str) or alias not in APPLICATION_LOCATIONS:
        raise ValidationError("APP_NOT_ALLOWED")
    if os.name != "nt":
        raise ValidationError("UNSUPPORTED_PLATFORM")
    executable = _find_application(alias)
    # No arbitrary arguments, PATH search, command interpreter, or shell command.
    os.startfile(str(executable), "open")
    return ExecutionResult(True, "Application launch requested; readiness is not verified.", {
        "alias": alias, "launch_requested": True,
    })


@_safe_result
def open_project_in_vscode(path: str | Path) -> ExecutionResult:
    project = validate_local_path(path, directory=True)
    if os.name != "nt":
        raise ValidationError("UNSUPPORTED_PLATFORM")
    executable = _find_application("vscode")
    # Quote Windows argv for ShellExecute, not for a command shell. Direct Code.exe
    # avoids running the code.cmd batch shim. Never pass project-controlled flags.
    arguments = list2cmdline([
        "--new-window", "--disable-extensions", str(project),
    ])
    os.startfile(str(executable), "open", arguments=arguments)
    return ExecutionResult(True, "VS Code launch requested; readiness is not verified.", {
        "alias": "vscode", "launch_requested": True,
    })
