"""Metadata completeness and direct-call boundaries, without a runtime registry."""

import ast
import inspect
import json
import unittest
from pathlib import Path

from core.models import RiskLevel
from tools import app_tools, browser_tools, file_tools, system_tools
from tools.base import ToolMetadata


class ToolContractTests(unittest.TestCase):
    def test_every_public_operation_has_unique_metadata_and_matching_schema(self) -> None:
        names = set()
        for module in (system_tools, app_tools, file_tools, browser_tools):
            operations = {
                name: operation for name, operation in vars(module).items()
                if inspect.isfunction(operation) and operation.__module__ == module.__name__
                and not name.startswith("_")
            }
            metadata = {
                name: item for name, item in vars(module).items() if isinstance(item, ToolMetadata)
            }
            self.assertEqual(len(operations), len(metadata))
            for name, operation in operations.items():
                with self.subTest(operation=name):
                    item = metadata[name.upper() + "_METADATA"]
                    self.assertNotIn(item.name, names)
                    names.add(item.name)
                    self.assertEqual(item.name.split(".")[-1], name)
                    self.assertTrue(item.description)
                    schema = item.arguments_schema
                    json.dumps(schema)  # No provider objects or non-JSON values.
                    self.assertEqual(schema["type"], "object")
                    self.assertFalse(schema["additionalProperties"])
                    signature = inspect.signature(operation)
                    self.assertEqual(set(schema["properties"]), set(signature.parameters))
                    required = {key for key, param in signature.parameters.items() if param.default is inspect.Parameter.empty}
                    self.assertEqual(set(schema["required"]), required)
                    for definition in schema["properties"].values():
                        self.assertIn(definition["type"], {"string", "integer"})
                        if "minimum" in definition:
                            self.assertLessEqual(definition["minimum"], definition["maximum"])
        self.assertEqual(len(names), 16)

    def test_risk_levels_match_operations(self) -> None:
        for module in (system_tools, app_tools, file_tools, browser_tools):
            for item in vars(module).values():
                if not isinstance(item, ToolMetadata):
                    continue
                operation = item.name.split(".")[-1]
                if operation in {"create_directory", "rename_path", "move_path"}:
                    expected = RiskLevel.MEDIUM
                elif module is system_tools or operation in {"list_directory", "find_files"}:
                    expected = RiskLevel.READ_ONLY
                else:
                    expected = RiskLevel.LOW
                self.assertEqual(item.risk_level, expected, item.name)

    def test_no_shell_or_dynamic_code_execution_in_tool_source(self) -> None:
        source_root = Path(__file__).resolve().parent.parent
        for folder in ("tools", "security"):
            for file in (source_root / folder).glob("*.py"):
                tree = ast.parse(file.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {"eval", "exec", "compile"}, str(file))
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                            self.assertNotIn(node.func.attr, {"system", "popen"}, str(file))
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                            self.assertEqual(node.func.attr, "list2cmdline", str(file))
                    for keyword in node.keywords:
                        if keyword.arg == "shell":
                            self.assertIsInstance(keyword.value, ast.Constant)
                            self.assertIs(keyword.value.value, False)

    def test_python_311_syntax_compatibility(self) -> None:
        source_root = Path(__file__).resolve().parent.parent
        for folder in ("tools", "security", "config", "core"):
            for file in (source_root / folder).glob("*.py"):
                ast.parse(file.read_text(encoding="utf-8"), feature_version=(3, 11))
