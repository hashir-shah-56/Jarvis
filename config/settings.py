"""Load non-secret Stage 1 settings without import-time side effects."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
ENVIRONMENTS = frozenset({"development", "testing", "production"})


class ConfigurationError(ValueError):
    """A configuration value is invalid; messages never include its value."""


@dataclass(frozen=True)
class Settings:
    """Validated application settings; paths are absolute after loading."""

    environment: str
    log_level: str
    data_dir: Path
    log_dir: Path


def load_settings(
    environ: Mapping[str, str] | None = None,
    *,
    base_dir: Path | None = None,
) -> Settings:
    """Read environment variables; do not load .env or create directories.

    Relative paths resolve against the project root, not the working directory.
    Explicit mappings and base directories support isolated tests.
    """
    values = os.environ if environ is None else environ
    root = PROJECT_ROOT if base_dir is None else base_dir.resolve()
    environment = values.get("JARVIS_ENV", "development").strip().lower()
    level = values.get("JARVIS_LOG_LEVEL", "INFO").strip().upper()
    if environment not in ENVIRONMENTS:
        raise ConfigurationError("Invalid JARVIS_ENV")
    if level not in LOG_LEVELS:
        raise ConfigurationError("Invalid JARVIS_LOG_LEVEL")

    def directory(key: str, default: str) -> Path:
        value = values.get(key, default).strip()
        if not value or "\x00" in value:
            raise ConfigurationError(f"Invalid {key}")
        try:
            path = Path(value).expanduser()
            return (root / path).resolve()
        except (OSError, RuntimeError, ValueError):
            raise ConfigurationError(f"Invalid {key}") from None

    return Settings(
        environment=environment,
        log_level=level,
        data_dir=directory("JARVIS_DATA_DIR", "data"),
        log_dir=directory("JARVIS_LOG_DIR", "logs"),
    )
