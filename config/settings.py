"""Explicit environment configuration; startup and optional AI settings are separate."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
ENVIRONMENTS = frozenset({"development", "testing", "production"})
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_AI_TIMEOUT_SECONDS = 30


class ConfigurationError(ValueError):
    """A configuration value is invalid; messages never include its value."""


@dataclass(frozen=True)
class Settings:
    """Validated application settings; paths are absolute after loading."""

    environment: str
    log_level: str
    data_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class GeminiSettings:
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: int


def load_gemini_settings(environ: Mapping[str, str] | None = None) -> GeminiSettings:
    """Explicit opt-in loading, independent of safe, quota-free startup."""
    values = os.environ if environ is None else environ
    key = values.get("GEMINI_API_KEY", "")
    model = values.get("JARVIS_GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    timeout = values.get("JARVIS_AI_TIMEOUT_SECONDS", str(DEFAULT_AI_TIMEOUT_SECONDS))
    if type(key) is not str or not key.strip():
        raise ConfigurationError("AI_NOT_CONFIGURED")
    if key != key.strip() or any(char.isspace() or ord(char) < 32 for char in key):
        raise ConfigurationError("AI_INVALID_CONFIGURATION")
    if type(model) is not str or not re.fullmatch(r"gemini-[A-Za-z0-9][A-Za-z0-9._-]{0,119}", model):
        raise ConfigurationError("AI_INVALID_CONFIGURATION")
    if type(timeout) is not str or not re.fullmatch(r"[0-9]{1,3}", timeout) or not 1 <= int(timeout) <= 120:
        raise ConfigurationError("AI_INVALID_CONFIGURATION")
    return GeminiSettings(key, model, int(timeout))


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
