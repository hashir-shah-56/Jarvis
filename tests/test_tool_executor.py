"""Dispatcher contracts without real launches, user-file changes, or services."""

import inspect
import unittest
from collections import UserDict
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock, patch

from config.settings import PROJECT_ROOT
from core.models import ExecutionResult, RiskLevel
from security import gateway
from tools import _execution, executor
from tools.registry import REGISTRY, RegisteredTool, ToolRegistry


class ToolExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = ExecutionResult(True, "Completed", {"count": 1})
        self.operations = {}
        entries = []
        for metadata in REGISTRY.list_metadata():
            tool = REGISTRY.get(metadata["name"])
            operation = Mock(return_value=self.result)
            self.operations[tool.metadata.name] = operation
            entries.append(RegisteredTool(tool.metadata, operation))
        self.gateway = gateway.SecurityGateway(registry=ToolRegistry(entries))
        self.registry_patch = patch.object(gateway, "_DEFAULT_GATEWAY", self.gateway)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)

    def execute_with_confirmation(self, name, arguments):
        """Stage 3 dispatch assertions now cross the required Stage 4 gate."""
        result = executor.execute_tool(name, arguments)
        if result.error_id == "CONFIRMATION_REQUIRED":
            self.operations[name].assert_not_called()
            return gateway.confirm_execution(result.data["confirmation_id"])
        return result

    def assert_rejected(self, name, arguments, error_id="INVALID_TOOL_ARGUMENTS") -> None:
        result = executor.execute_tool(name, arguments)
        self.assertIsInstance(result, ExecutionResult)
        self.assertFalse(result.success)
        self.assertEqual(result.error_id, error_id)
        self.assertIsNone(result.data)
        for operation in self.operations.values():
            operation.assert_not_called()

    def test_only_name_and_argument_mapping_are_execution_inputs(self) -> None:
        self.assertEqual(list(inspect.signature(executor.execute_tool).parameters), ["tool_name", "arguments"])

    def test_valid_calls_dispatch_to_each_of_the_22_bound_operations(self) -> None:
        cases = {
            "system.get_system_info": {}, "system.get_cpu_info": {},
            "system.get_cpu_usage": {}, "system.get_memory_info": {},
            "system.get_disk_info": {"path": "."},
            "system.list_processes": {"limit": 4},
            "app.open_application": {"alias": "notepad"},
            "app.open_project_in_vscode": {"path": "project"},
            "file.list_directory": {"path": "data", "limit": 5},
            "file.find_files": {"root": "data", "pattern": "*.txt", "limit": 2, "max_depth": 0, "max_entries": 3},
            "file.open_path": {"path": "example.txt"},
            "file.create_directory": {"path": "new"},
            "file.rename_path": {"path": "old", "new_name": "new"},
            "file.move_path": {"source": "old", "destination": "new"},
            "browser.open_url": {"url": "https://example.com"},
            "browser.search_web": {"query": "example query"},
            "memory.list": {},
            "memory.get": {"memory_id": "m" * 22},
            "memory.search": {"query": "concise"},
            "memory.create": {"content": "Concise", "category": "preference"},
            "memory.update": {"memory_id": "m" * 22, "expected_updated_at": "2026-10-08T00:00:00Z", "content": "Detailed", "category": "preference"},
            "memory.delete": {"memory_id": "m" * 22, "expected_updated_at": "2026-10-08T00:00:00Z", "expected_content": "Concise", "category": "preference"},
        }
        self.assertEqual(set(cases), set(self.operations))
        for name, arguments in cases.items():
            with self.subTest(name=name):
                for operation in self.operations.values():
                    operation.reset_mock()
                self.assertIs(self.execute_with_confirmation(name, arguments), self.result)
                self.operations[name].assert_called_once_with(**arguments)
                for other, operation in self.operations.items():
                    if other != name:
                        operation.assert_not_called()

    def test_optional_arguments_remain_omitted(self) -> None:
        for name, arguments in (
            ("system.get_disk_info", {}), ("system.list_processes", {}),
            ("file.list_directory", {"path": "data"}),
            ("file.find_files", {"root": "data"}),
        ):
            self.assertIs(executor.execute_tool(name, arguments), self.result)
            self.operations[name].assert_called_once_with(**arguments)

    def test_every_required_argument_is_enforced(self) -> None:
        for item in REGISTRY.list_metadata():
            schema = item["arguments_schema"]
            valid = {key: definition.get("enum", ["value"])[0] for key, definition in schema["properties"].items() if key in schema["required"]}
            for key in schema["required"]:
                with self.subTest(tool=item["name"], missing=key):
                    self.assert_rejected(item["name"], {k: v for k, v in valid.items() if k != key})

    def test_extra_arguments_rejected_for_every_tool(self) -> None:
        for item in REGISTRY.list_metadata():
            schema = item["arguments_schema"]
            arguments = {
                key: definition.get("enum", ["value"])[0]
                for key, definition in schema["properties"].items()
                if key in schema["required"]
            }
            self.assert_rejected(item["name"], {**arguments, "unexpected": "private"})

    def test_wrong_string_types_are_rejected(self) -> None:
        for value in (None, 1, True, [], {}, b"text", Path("data")):
            self.assert_rejected("browser.search_web", {"query": value})

    def test_integer_types_are_not_coerced_and_boolean_is_rejected(self) -> None:
        for value in (None, "10", 10.0, True, False, [], {}):
            self.assert_rejected("system.list_processes", {"limit": value})

    def test_all_declared_string_and_integer_bounds(self) -> None:
        for item in REGISTRY.list_metadata():
            schema = item["arguments_schema"]
            required = {key: definition.get("enum", ["x" * max(1, definition.get("minLength", 1))])[0] for key, definition in schema["properties"].items() if key in schema["required"]}
            for key, definition in schema["properties"].items():
                for bound, delta in (("minLength", -1), ("maxLength", 1), ("minimum", -1), ("maximum", 1)):
                    if bound not in definition:
                        continue
                    edge = definition[bound]
                    invalid = edge + delta
                    if definition["type"] == "string":
                        edge, invalid = "x" * edge, "x" * invalid
                    with self.subTest(tool=item["name"], key=key, bound=bound):
                        self.assert_rejected(item["name"], {**required, key: invalid})
                        self.assertIs(self.execute_with_confirmation(item["name"], {**required, key: edge}), self.result)
                        self.operations[item["name"]].reset_mock()

    def test_application_enum_is_exact(self) -> None:
        for invalid in ("cmd", "Notepad", "notepad ", "C:/Windows/notepad.exe"):
            self.assert_rejected("app.open_application", {"alias": invalid})
        aliases = REGISTRY.get("app.open_application").metadata.arguments_schema["properties"]["alias"]["enum"]
        for alias in aliases:
            self.assertIs(executor.execute_tool("app.open_application", {"alias": alias}), self.result)

    def test_malformed_argument_payloads(self) -> None:
        for value in (None, [], [("limit", 1)], "{}", 3, True, {1: "value"}):
            self.assert_rejected("system.list_processes", value)

    def test_caller_mappings_are_not_mutated(self) -> None:
        for arguments in ({"root": "data"}, UserDict(root="data"), MappingProxyType({"root": "data"})):
            before = dict(arguments)
            self.assertIs(executor.execute_tool("file.find_files", arguments), self.result)
            self.assertEqual(dict(arguments), before)
            self.assertNotIn("pattern", arguments)
        invalid = {"limit": "10"}
        executor.execute_tool("system.list_processes", invalid)
        self.assertEqual(invalid, {"limit": "10"})

    def test_invalid_names_do_not_invoke_registry(self) -> None:
        with patch.object(self.gateway, "_registry") as registry:
            for name in (None, "", [], {}, 4, True, lambda: None):
                self.assert_rejected(name, {}, "INVALID_TOOL_NAME")
            registry.get.assert_not_called()

    def test_unknown_names_never_invoke_a_tool(self) -> None:
        for name in ("unknown-private-name", "SYSTEM.GET_CPU_INFO", "system.get_cpu_info ", "os.system", "tools.system_tools.get_cpu_info", "__import__('os')"):
            self.assert_rejected(name, {}, "TOOL_NOT_FOUND")

    def test_underlying_failure_result_is_preserved(self) -> None:
        result = ExecutionResult(False, "Action unavailable", error_id="ACCESS_DENIED")
        self.operations["system.get_cpu_info"].return_value = result
        self.assertIs(executor.execute_tool("system.get_cpu_info", {}), result)

    def test_internal_exception_is_sanitized(self) -> None:
        self.operations["system.get_cpu_info"].side_effect = RuntimeError("private-path secret")
        result = executor.execute_tool("system.get_cpu_info", {})
        self.assertEqual(result, ExecutionResult(False, "The operation could not be completed.", error_id="TOOL_EXECUTION_FAILED"))

    def test_lookup_and_validator_exceptions_are_sanitized(self) -> None:
        with patch.object(self.gateway, "_registry") as registry:
            registry.get.side_effect = RuntimeError("private-registry-detail")
            self.assert_rejected("system.get_cpu_info", {}, "TOOL_EXECUTION_FAILED")
        with patch.object(_execution, "validate_arguments", side_effect=RuntimeError("private-validator-detail")):
            self.assert_rejected("system.get_cpu_info", {}, "TOOL_EXECUTION_FAILED")

    def test_non_result_returns_are_rejected_without_representation(self) -> None:
        class SecretObject:
            def __repr__(self):
                raise AssertionError("must not inspect returned object")

        for value in (None, True, "secret-result", {"secret": "value"}, SecretObject()):
            self.operations["system.get_cpu_info"].return_value = value
            result = executor.execute_tool("system.get_cpu_info", {})
            self.assertFalse(result.success)
            self.assertEqual(result.error_id, "TOOL_EXECUTION_FAILED")
            self.assertIsNone(result.data)
            self.assertNotIn("secret", result.message)

    def test_unsupported_schema_fails_closed_even_for_omitted_property(self) -> None:
        tool = REGISTRY.get("system.list_processes")
        tool.metadata.arguments_schema["properties"]["limit"]["multipleOf"] = 2
        registry = ToolRegistry((RegisteredTool(tool.metadata, self.operations[tool.metadata.name]),))
        with patch.object(self.gateway, "_registry", registry):
            self.assert_rejected(tool.metadata.name, {}, "TOOL_EXECUTION_FAILED")

    def test_risk_metadata_now_requires_confirmation_for_medium_and_high(self) -> None:
        tool = REGISTRY.get("system.get_cpu_info")
        for risk in RiskLevel:
            operation = Mock(return_value=self.result)
            registry = ToolRegistry((RegisteredTool(replace(tool.metadata, risk_level=risk), operation),))
            with patch.object(self.gateway, "_registry", registry):
                result = executor.execute_tool(tool.metadata.name, {})
                if risk in (RiskLevel.MEDIUM, RiskLevel.HIGH):
                    self.assertEqual(result.error_id, "CONFIRMATION_REQUIRED")
                    operation.assert_not_called()
                    result = gateway.confirm_execution(result.data["confirmation_id"])
                self.assertIs(result, self.result)
                operation.assert_called_once_with()

    def test_logs_do_not_include_requests_or_internal_failures(self) -> None:
        with self.assertLogs("jarvis.tools.executor", level="DEBUG") as logs:
            executor.execute_tool("private-tool-name", {})
            executor.execute_tool("browser.open_url", {"url": "https://example.com/private-secret"})
            executor.execute_tool("browser.search_web", {"query": "private-secret"})
            executor.execute_tool("file.open_path", {"path": "private-secret.txt"})
            executor.execute_tool("system.list_processes", {"limit": "private-secret"})
            self.operations["system.get_cpu_info"].side_effect = RuntimeError("private-secret")
            executor.execute_tool("system.get_cpu_info", {})
        output = "\n".join(logs.output)
        self.assertNotIn("private", output)
        self.assertNotIn("https://", output)
        self.assertNotIn("Traceback", output)
        self.assertIn("INVALID_TOOL_ARGUMENTS", output)
        self.assertIn("execution completed", output)

    def test_logging_failure_is_sanitized(self) -> None:
        with patch.object(_execution, "get_logger", side_effect=RuntimeError("private-log-path")):
            self.assert_rejected("unknown", {}, "TOOL_EXECUTION_FAILED")


class RealToolBoundaryTests(unittest.TestCase):
    def test_real_zero_argument_tool_with_mocked_measurement(self) -> None:
        with patch("tools.system_tools.psutil.cpu_count", side_effect=[2, 4]) as count:
            result = executor.execute_tool("system.get_cpu_info", {})
        self.assertTrue(result.success)
        self.assertEqual(result.data, {"physical_cores": 2, "logical_cpus": 4})
        self.assertEqual(count.call_count, 2)

    def test_default_disk_path_is_left_to_python(self) -> None:
        disk = SimpleNamespace(total=10, used=4, free=6, percent=40.0)
        with patch("tools.system_tools.psutil.disk_usage", return_value=disk) as usage:
            result = executor.execute_tool("system.get_disk_info", {})
        self.assertTrue(result.success)
        usage.assert_called_once_with(str(PROJECT_ROOT.resolve()))

    def test_real_optional_search_arguments_work_in_temporary_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            result = executor.execute_tool("file.find_files", {"root": temporary})
        self.assertTrue(result.success)
        self.assertEqual(result.data["files"], [])

    def test_stage_2_path_and_url_checks_still_apply(self) -> None:
        with patch("tools.browser_tools.webbrowser.open") as browser:
            result = executor.execute_tool("browser.open_url", {"url": "javascript:private"})
        self.assertEqual(result.error_id, "UNSUPPORTED_URL_SCHEME")
        browser.assert_not_called()
        with patch("tools.file_tools.os.startfile", create=True) as launch:
            result = executor.execute_tool("file.open_path", {"path": "../private"})
        self.assertEqual(result.error_id, "INVALID_PATH")
        launch.assert_not_called()

    def test_stage_2_safe_result_still_sanitizes_operational_errors(self) -> None:
        with patch("tools.system_tools.psutil.cpu_count", side_effect=RuntimeError("private-details")):
            result = executor.execute_tool("system.get_cpu_info", {})
        self.assertEqual(result.error_id, "TOOL_EXECUTION_FAILED")
        self.assertNotIn("private", result.message)
