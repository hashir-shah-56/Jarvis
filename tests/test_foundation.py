"""Configuration, runtime, and provider-independent model tests."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent.permissions import PermissionDecision
from config.settings import ConfigurationError, PROJECT_ROOT, load_settings
from core import __version__, get_version
from core.models import ExecutionResult, RiskLevel
from core.runtime import initialize_directories
from tools.base import ToolMetadata


class ConfigurationTests(unittest.TestCase):
    def test_defaults_and_no_filesystem_side_effects(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = load_settings({}, base_dir=root)
            self.assertEqual(settings.environment, "development")
            self.assertEqual(settings.log_level, "INFO")
            self.assertEqual(settings.data_dir, root / "data")
            self.assertEqual(settings.log_dir, root / "logs")
            self.assertEqual(list(root.iterdir()), [])

    def test_relative_defaults_use_project_root(self) -> None:
        settings = load_settings({})
        self.assertEqual(settings.data_dir, PROJECT_ROOT / "data")
        self.assertEqual(settings.log_dir, PROJECT_ROOT / "logs")

    def test_environment_overrides_and_absolute_paths(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {
                "JARVIS_ENV": " production ",
                "JARVIS_LOG_LEVEL": "debug",
                "JARVIS_DATA_DIR": "custom/data",
                "JARVIS_LOG_DIR": str(root / "absolute_logs"),
            }
            with patch.dict(os.environ, values, clear=True):
                settings = load_settings(base_dir=root)
            self.assertEqual(settings.environment, "production")
            self.assertEqual(settings.log_level, "DEBUG")
            self.assertEqual(settings.data_dir, root / "custom" / "data")
            self.assertEqual(settings.log_dir, root / "absolute_logs")

    def test_invalid_values_are_rejected_without_echoing_them(self) -> None:
        for key in ("JARVIS_ENV", "JARVIS_LOG_LEVEL"):
            with self.subTest(key=key):
                with self.assertRaises(ConfigurationError) as error:
                    load_settings({key: "private-invalid-value"})
                self.assertNotIn("private-invalid-value", str(error.exception))
        for key in ("JARVIS_DATA_DIR", "JARVIS_LOG_DIR"):
            for value in ("", "  ", "bad\x00path"):
                with self.subTest(key=key, value=repr(value)):
                    with self.assertRaises(ConfigurationError):
                        load_settings({key: value})


class RuntimeTests(unittest.TestCase):
    def test_creation_is_idempotent_and_preserves_contents(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            initialize_directories(settings)
            marker = settings.data_dir / "existing.txt"
            marker.write_text("keep me", encoding="utf-8")
            initialize_directories(settings)
            self.assertTrue(settings.log_dir.is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")

    def test_existing_file_is_not_overwritten(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            settings.log_dir.write_text("keep me", encoding="utf-8")
            with self.assertRaises(NotADirectoryError):
                initialize_directories(settings)
            self.assertEqual(settings.log_dir.read_text(encoding="utf-8"), "keep me")
            self.assertFalse(settings.data_dir.exists())

    def test_nested_directories(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings(
                {"JARVIS_DATA_DIR": "nested/runtime/data"},
                base_dir=Path(temporary),
            )
            initialize_directories(settings)
            self.assertTrue(settings.data_dir.is_dir())


class ModelTests(unittest.TestCase):
    def test_version_retrieval(self) -> None:
        self.assertEqual(get_version(), __version__)
        self.assertRegex(get_version(), r"^\d+\.\d+\.\d+$")

    def test_risk_levels(self) -> None:
        self.assertEqual(
            {risk.value for risk in RiskLevel},
            {"read_only", "low", "medium", "high"},
        )
        with self.assertRaises(ValueError):
            RiskLevel("unknown")

    def test_results_support_success_and_sanitized_failure(self) -> None:
        result = ExecutionResult(True, "Completed", data={"count": 2})
        self.assertTrue(result.success)
        self.assertEqual(result.data, {"count": 2})
        self.assertIsNone(result.error_id)
        failure = ExecutionResult(False, "Action unavailable", error_id="UNAVAILABLE")
        self.assertFalse(failure.success)
        self.assertIsNone(failure.data)
        self.assertEqual(failure.error_id, "UNAVAILABLE")

    def test_tool_metadata_has_no_execution_behavior(self) -> None:
        metadata = ToolMetadata(
            name="example.read",
            description="Contract example only",
            risk_level=RiskLevel.READ_ONLY,
            arguments_schema={"type": "object", "properties": {}},
        )
        self.assertEqual(metadata.risk_level, RiskLevel.READ_ONLY)
        self.assertEqual(metadata.arguments_schema["type"], "object")
        self.assertFalse(hasattr(metadata, "execute"))

    def test_permission_vocabulary(self) -> None:
        self.assertEqual(
            {decision.value for decision in PermissionDecision},
            {"allow", "require_confirmation", "deny"},
        )
