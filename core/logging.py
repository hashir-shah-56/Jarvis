"""Reusable JSON-line logging for the jarvis logger namespace."""

import json
import logging
from datetime import datetime, timezone

from config.settings import Settings


class JsonFormatter(logging.Formatter):
    """Emit UTC timestamps and component names without raw exception details."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(
                    record.created, timezone.utc
                ).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "component": record.name,
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


def get_logger(component: str) -> logging.Logger:
    """Get a child logger; callers must never include secrets in messages."""
    return logging.getLogger(f"jarvis.{component}")


def initialize_logging(settings: Settings) -> logging.Logger:
    """Configure console/stderr and append-only UTF-8 file logging.

    Runtime directories must already exist. Repeated initialization replaces
    Jarvis handlers without altering the root logger or duplicating output.
    """
    file_handler = logging.FileHandler(
        settings.log_dir / "jarvis.log", mode="a", encoding="utf-8"
    )
    console_handler = logging.StreamHandler()
    formatter = JsonFormatter()
    for handler in (console_handler, file_handler):
        handler.setFormatter(formatter)

    shutdown_logging()
    logger = logging.getLogger("jarvis")
    logger.setLevel(settings.log_level)
    logger.propagate = False
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return get_logger("main")


def shutdown_logging() -> None:
    """Flush and close Jarvis handlers, leaving unrelated logging untouched."""
    logger = logging.getLogger("jarvis")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
