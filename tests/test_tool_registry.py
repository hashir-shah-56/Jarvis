"""Exact allowlist resolution and isolation of descriptive metadata."""

import inspect
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock

from core.models import ExecutionResult
from tools import app_tools, browser_tools, file_tools, system_tools
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry


EXPECTED = {
    "system.get_system_info": (system_tools.GET_SYSTEM_INFO_METADATA, system_tools.get_system_info),
    "system.get_cpu_info": (system_tools.GET_CPU_INFO_METADATA, system_tools.get_cpu_info),
    "system.get_cpu_usage": (system_tools.GET_CPU_USAGE_METADATA, system_tools.get_cpu_usage),
    "system.get_memory_info": (system_tools.GET_MEMORY_INFO_METADATA, system_tools.get_memory_info),
    "system.get_disk_info": (system_tools.GET_DISK_INFO_METADATA, system_tools.get_disk_info),
    "system.list_processes": (system_tools.LIST_PROCESSES_METADATA, system_tools.list_processes),
    "app.open_application": (app_tools.OPEN_APPLICATION_METADATA, app_tools.open_application),
    "app.open_project_in_vscode": (app_tools.OPEN_PROJECT_IN_VSCODE_METADATA, app_tools.open_project_in_vscode),
    "file.list_directory": (file_tools.LIST_DIRECTORY_METADATA, file_tools.list_directory),
    "file.find_files": (file_tools.FIND_FILES_METADATA, file_tools.find_files),
    "file.open_path": (file_tools.OPEN_PATH_METADATA, file_tools.open_path),
    "file.create_directory": (file_tools.CREATE_DIRECTORY_METADATA, file_tools.create_directory),
    "file.rename_path": (file_tools.RENAME_PATH_METADATA, file_tools.rename_path),
    "file.move_path": (file_tools.MOVE_PATH_METADATA, file_tools.move_path),
    "browser.open_url": (browser_tools.OPEN_URL_METADATA, browser_tools.open_url),
    "browser.search_web": (browser_tools.SEARCH_WEB_METADATA, browser_tools.search_web),
}


class ToolRegistryTests(unittest.TestCase):
    def test_exactly_16_unique_tools_in_deterministic_order(self) -> None:
        names = [item["name"] for item in REGISTRY.list_metadata()]
        self.assertEqual(len(names), 16)
        self.assertEqual(len(set(names)), 16)
        self.assertEqual(names, list(EXPECTED))
        self.assertEqual(REGISTRY.list_metadata(), REGISTRY.list_metadata())

    def test_exact_bindings_and_metadata_match_existing_tools(self) -> None:
        for name, (metadata, implementation) in EXPECTED.items():
            with self.subTest(name=name):
                tool = REGISTRY.get(name)
                self.assertTrue(REGISTRY.contains(name))
                self.assertEqual(tool.metadata, metadata)
                self.assertIsNot(tool.metadata, metadata)
                self.assertIs(tool.implementation, implementation)

    def test_unknown_and_malformed_names_fail_without_resolution(self) -> None:
        for name in (
            "", "missing", "SYSTEM.GET_CPU_INFO", " system.get_cpu_info",
            "system.get_cpu_info ", "get_cpu_info", "tools.system_tools.get_cpu_info",
            "os.system", "__import__('os')", "C:/private/tool.exe", None, [], {},
            3, True, system_tools.get_cpu_info,
        ):
            with self.subTest(name=name):
                self.assertIsNone(REGISTRY.get(name))
                self.assertFalse(REGISTRY.contains(name))

    def test_duplicate_names_cannot_overwrite(self) -> None:
        tool = REGISTRY.get("system.get_cpu_info")
        replacement = RegisteredTool(tool.metadata, Mock())
        with self.assertRaisesRegex(ValueError, "^DUPLICATE_TOOL_NAME$"):
            ToolRegistry((tool, replacement))
        self.assertIs(REGISTRY.get(tool.metadata.name).implementation, tool.implementation)

    def test_invalid_registration_has_fixed_error(self) -> None:
        tool = REGISTRY.get("system.get_cpu_info")
        for invalid in (
            RegisteredTool(replace(tool.metadata, name=""), tool.implementation),
            RegisteredTool(tool.metadata, "private-module.path"),
        ):
            with self.assertRaisesRegex(ValueError, "^INVALID_TOOL_REGISTRATION$"):
                ToolRegistry((invalid,))

    def test_metadata_listing_is_json_compatible_and_has_no_callable(self) -> None:
        listing = REGISTRY.list_metadata()
        self.assertEqual(json.loads(json.dumps(listing)), listing)
        for item in listing:
            expected = EXPECTED[item["name"]][0]
            self.assertEqual(item, {
                "name": expected.name, "description": expected.description,
                "risk_level": expected.risk_level.value,
                "arguments_schema": expected.arguments_schema,
            })

    def test_lookup_and_listing_do_not_expose_mutable_schemas(self) -> None:
        before = REGISTRY.list_metadata()
        tool = REGISTRY.get("app.open_application")
        tool.metadata.arguments_schema["properties"]["alias"]["enum"].append("cmd")
        tool.metadata.arguments_schema["required"].clear()
        listing = REGISTRY.list_metadata()
        listing[0]["arguments_schema"]["additionalProperties"] = True
        listing.clear()
        self.assertEqual(REGISTRY.list_metadata(), before)
        with self.assertRaises(FrozenInstanceError):
            tool.implementation = Mock()
        with self.assertRaises(TypeError):
            REGISTRY._tools["os.system"] = tool
        with self.assertRaises(FrozenInstanceError):
            REGISTRY._tools = {}

    def test_constructor_snapshots_input_without_invoking_implementation(self) -> None:
        tool = REGISTRY.get("app.open_application")
        operation = Mock(return_value=ExecutionResult(True, "Completed"))
        entries = [RegisteredTool(tool.metadata, operation)]
        registry = ToolRegistry(entries)
        entries.clear()
        tool.metadata.arguments_schema["properties"]["alias"]["enum"].clear()
        self.assertEqual(registry.get(tool.metadata.name).metadata, EXPECTED[tool.metadata.name][0])
        operation.assert_not_called()

    def test_every_schema_default_matches_python_signature(self) -> None:
        for name, (metadata, implementation) in EXPECTED.items():
            signature = inspect.signature(implementation)
            for key, definition in metadata.arguments_schema["properties"].items():
                with self.subTest(tool=name, argument=key):
                    if "default" in definition:
                        self.assertEqual(definition["default"], signature.parameters[key].default)
                        self.assertNotIn(key, metadata.arguments_schema["required"])
