"""Native application launch boundaries are always mocked."""

import os
import unittest
from pathlib import Path
from subprocess import list2cmdline
from tempfile import TemporaryDirectory
from unittest.mock import patch

from config.tool_settings import APPLICATION_LOCATIONS
from tools import app_tools as apps


@unittest.skipUnless(os.name == "nt", "Windows launch contracts")
class ApplicationToolTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        launcher = patch("os.startfile")
        self.launch = launcher.start()
        self.addCleanup(launcher.stop)

    def test_all_allowed_aliases_use_fixed_executable(self) -> None:
        for alias, locations in APPLICATION_LOCATIONS.items():
            variable, relative = locations[0]
            executable = self.root / relative
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"not an executable; launch is mocked")
            with self.subTest(alias=alias), patch.dict(os.environ, {variable: str(self.root)}, clear=True):
                result = apps.open_application(alias)
                self.assertTrue(result.success, result)
                self.assertEqual(result.data, {"alias": alias, "launch_requested": True})
                self.launch.assert_called_with(str(executable.resolve()), "open")

    def test_unknown_aliases_fail_before_discovery(self) -> None:
        with patch.object(apps, "_find_application") as find:
            for alias in ("powershell", "cmd.exe", r"C:\evil.exe", "notepad & calc", "", [], None):
                self.assertEqual(apps.open_application(alias).error_id, "APP_NOT_ALLOWED")
        find.assert_not_called()
        self.launch.assert_not_called()

    def test_missing_application(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(apps.open_application("vscode").error_id, "APP_NOT_FOUND")
        self.launch.assert_not_called()

    def test_relative_install_root_is_not_used(self) -> None:
        with patch.dict(os.environ, {"SystemRoot": "."}, clear=True):
            self.assertEqual(apps.open_application("notepad").error_id, "APP_NOT_FOUND")
        self.launch.assert_not_called()

    def test_launch_access_denied_is_sanitized(self) -> None:
        with patch.object(apps, "_find_application", return_value=self.root / "notepad.exe"):
            self.launch.side_effect = PermissionError("sensitive")
            result = apps.open_application("notepad")
        self.assertEqual(result.error_id, "ACCESS_DENIED")
        self.assertNotIn("sensitive", result.message)

    def test_project_open_quotes_path_and_uses_no_shell(self) -> None:
        project = self.root / "project & with spaces"
        project.mkdir()
        executable = self.root / "Code.exe"
        with patch.object(apps, "_find_application", return_value=executable) as find:
            result = apps.open_project_in_vscode(project)
        self.assertTrue(result.success)
        find.assert_called_once_with("vscode")
        self.launch.assert_called_once_with(str(executable), "open", arguments=list2cmdline([
            "--new-window", "--disable-extensions", str(project.resolve()),
        ]))

    def test_project_invalid_or_file(self) -> None:
        file = self.root / "file.txt"
        file.write_text("example", encoding="utf-8")
        self.assertEqual(apps.open_project_in_vscode(self.root / "missing").error_id, "PATH_NOT_FOUND")
        self.assertEqual(apps.open_project_in_vscode(file).error_id, "NOT_A_DIRECTORY")
        self.launch.assert_not_called()

    def test_vscode_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(apps.open_project_in_vscode(self.root).error_id, "APP_NOT_FOUND")
        self.launch.assert_not_called()
