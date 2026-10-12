"""Entry point tests without subprocesses, external services, or real secrets."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main
from config.settings import load_settings
from core import get_version


class EntryPointTests(unittest.TestCase):
    def test_testing_and_production_do_not_enter_cli(self) -> None:
        for environment in ("testing", "production"):
            with TemporaryDirectory() as temporary:
                settings = load_settings({"JARVIS_ENV": environment}, base_dir=Path(temporary))
                with patch("main.load_settings", return_value=settings), patch("main.run_cli") as cli, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main.main(), 0)
                    cli.assert_not_called()

    def test_startup_and_clean_shutdown(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            output = io.StringIO()
            with (
                patch("main.load_settings", return_value=settings),
                patch("main.run_cli", return_value=0) as cli,
                redirect_stdout(output),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main.main(), 0)
                cli.assert_called_once()
            self.assertEqual(
                output.getvalue(),
                f"JARVIS\nVersion: {get_version()}\nEnvironment: development\nStatus: Ready\n",
            )
            records = [
                json.loads(line)
                for line in (settings.log_dir / "jarvis.log")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [record["message"] for record in records],
                ["Application started", "Application stopped"],
            )

    def test_unexpected_error_is_sanitized(self) -> None:
        errors = io.StringIO()
        with (
            patch("main.load_settings", side_effect=RuntimeError("sensitive-detail")),
            redirect_stderr(errors),
        ):
            self.assertEqual(main.main(), 1)
        self.assertIn("STARTUP_FAILED", errors.getvalue())
        self.assertNotIn("sensitive-detail", errors.getvalue())

    def test_interrupt_is_handled(self) -> None:
        with (
            patch("main.load_settings", side_effect=KeyboardInterrupt),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main.main(), 130)

    def test_logging_failure_is_handled(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            with (
                patch("main.load_settings", return_value=settings),
                patch("main.initialize_logging", side_effect=PermissionError("private-path")),
                redirect_stderr(io.StringIO()) as errors,
            ):
                self.assertEqual(main.main(), 1)
            self.assertNotIn("private-path", errors.getvalue())

    def test_corrupt_memory_does_not_disable_existing_cli(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            settings.data_dir.mkdir()
            path = settings.data_dir / "memory.sqlite3"
            contents = b"corrupt-private-database-contents"
            path.write_bytes(contents)
            with patch("main.load_settings", return_value=settings), patch("main.run_cli", return_value=0) as cli, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main.main(), 0)
                cli.assert_called_once()
            self.assertEqual(path.read_bytes(), contents)
            self.assertIn("MEMORY_DATABASE_CORRUPT", errors.getvalue())
            self.assertNotIn(contents.decode(), errors.getvalue())
