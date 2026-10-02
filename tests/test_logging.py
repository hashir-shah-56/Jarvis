"""Logging lifecycle tests with temporary files and captured console output."""

import io
import json
import logging
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory

from config.settings import load_settings
from core.logging import get_logger, initialize_logging, shutdown_logging
from core.runtime import initialize_directories


class LoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        shutdown_logging()

    def test_console_file_fields_filtering_and_reinitialization(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            initialize_directories(settings)
            log_path = settings.log_dir / "jarvis.log"
            log_path.write_text("existing content\n", encoding="utf-8")
            console = io.StringIO()
            root_handlers = logging.getLogger().handlers[:]
            with redirect_stderr(console):
                initialize_logging(settings)
                initialize_logging(settings)
                logger = get_logger("tests")
                logger.debug("filtered")
                logger.info("Ready")
                shutdown_logging()
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "existing content")
            self.assertEqual(len(lines), 2)
            record = json.loads(lines[1])
            self.assertEqual(record["level"], "INFO")
            self.assertEqual(record["component"], "jarvis.tests")
            self.assertEqual(record["message"], "Ready")
            self.assertTrue(record["timestamp"].endswith("+00:00"))
            self.assertEqual(json.loads(console.getvalue()), record)
            self.assertEqual(logging.getLogger().handlers, root_handlers)
            self.assertEqual(logging.getLogger("jarvis").handlers, [])

    def test_raw_exception_details_are_omitted(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = load_settings({}, base_dir=Path(temporary))
            initialize_directories(settings)
            with redirect_stderr(io.StringIO()):
                logger = initialize_logging(settings)
                try:
                    raise ValueError("sensitive-detail")
                except ValueError:
                    logger.exception("Operation failed (TEST_ERROR)")
                shutdown_logging()
            content = (settings.log_dir / "jarvis.log").read_text(encoding="utf-8")
            self.assertNotIn("sensitive-detail", content)
            self.assertNotIn("Traceback", content)
            self.assertIn("TEST_ERROR", content)
