"""Explicit Stage 2 allowlist for controlled Python callers, not authorization."""

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType

from core.models import ExecutionResult
from tools import app_tools, browser_tools, file_tools, memory_tools, system_tools
from tools.base import ToolMetadata


@dataclass(frozen=True)
class RegisteredTool:
    """Bind descriptive metadata to a trusted implementation, without policy."""

    metadata: ToolMetadata
    implementation: Callable[..., ExecutionResult] = field(repr=False)


def _copy_tool(tool: RegisteredTool) -> RegisteredTool:
    return RegisteredTool(deepcopy(tool.metadata), tool.implementation)


@dataclass(frozen=True, init=False)
class ToolRegistry:
    """A fixed snapshot built by trusted code; no runtime registration API.

    Construction and reads copy metadata, including nested schemas. The callable
    is deliberately preserved. This is not a sandbox against Python code that
    can modify private module/class state.
    """

    _tools: Mapping[str, RegisteredTool] = field(repr=False)

    def __init__(self, tools: Iterable[RegisteredTool]) -> None:
        entries = {}
        for tool in tools:
            name = tool.metadata.name
            if type(name) is not str or not name or not callable(tool.implementation):
                raise ValueError("INVALID_TOOL_REGISTRATION")
            if name in entries:
                raise ValueError("DUPLICATE_TOOL_NAME")
            entries[name] = _copy_tool(tool)
        object.__setattr__(self, "_tools", MappingProxyType(entries))

    def get(self, name: str) -> RegisteredTool | None:
        """Resolve an exact name; unknown or malformed names return None."""
        if type(name) is not str or not name:
            return None
        tool = self._tools.get(name)
        return None if tool is None else _copy_tool(tool)

    def contains(self, name: str) -> bool:
        """Check exact membership without normalization or dynamic resolution."""
        return type(name) is str and name in self._tools

    def list_metadata(self) -> list[dict[str, object]]:
        """Return detached, JSON-compatible descriptions in registration order."""
        return [
            {
                "name": tool.metadata.name,
                "description": tool.metadata.description,
                "risk_level": tool.metadata.risk_level.value,
                "arguments_schema": deepcopy(tool.metadata.arguments_schema),
            }
            for tool in self._tools.values()
        ]


# Each binding is reviewed in source. No scanning, import paths, or caller-supplied
# callables are used by the executor. Constructing this allowlist invokes no tools.
REGISTRY = ToolRegistry((
    RegisteredTool(system_tools.GET_SYSTEM_INFO_METADATA, system_tools.get_system_info),
    RegisteredTool(system_tools.GET_CPU_INFO_METADATA, system_tools.get_cpu_info),
    RegisteredTool(system_tools.GET_CPU_USAGE_METADATA, system_tools.get_cpu_usage),
    RegisteredTool(system_tools.GET_MEMORY_INFO_METADATA, system_tools.get_memory_info),
    RegisteredTool(system_tools.GET_DISK_INFO_METADATA, system_tools.get_disk_info),
    RegisteredTool(system_tools.LIST_PROCESSES_METADATA, system_tools.list_processes),
    RegisteredTool(app_tools.OPEN_APPLICATION_METADATA, app_tools.open_application),
    RegisteredTool(app_tools.OPEN_PROJECT_IN_VSCODE_METADATA, app_tools.open_project_in_vscode),
    RegisteredTool(file_tools.LIST_DIRECTORY_METADATA, file_tools.list_directory),
    RegisteredTool(file_tools.FIND_FILES_METADATA, file_tools.find_files),
    RegisteredTool(file_tools.OPEN_PATH_METADATA, file_tools.open_path),
    RegisteredTool(file_tools.CREATE_DIRECTORY_METADATA, file_tools.create_directory),
    RegisteredTool(file_tools.RENAME_PATH_METADATA, file_tools.rename_path),
    RegisteredTool(file_tools.MOVE_PATH_METADATA, file_tools.move_path),
    RegisteredTool(browser_tools.OPEN_URL_METADATA, browser_tools.open_url),
    RegisteredTool(browser_tools.SEARCH_WEB_METADATA, browser_tools.search_web),
    RegisteredTool(memory_tools.LIST_METADATA, memory_tools.list),
    RegisteredTool(memory_tools.GET_METADATA, memory_tools.get),
    RegisteredTool(memory_tools.SEARCH_METADATA, memory_tools.search),
    RegisteredTool(memory_tools.CREATE_METADATA, memory_tools.create),
    RegisteredTool(memory_tools.UPDATE_METADATA, memory_tools.update),
    RegisteredTool(memory_tools.DELETE_METADATA, memory_tools.delete),
))
