"""Jarvis composition entry point and development CLI startup."""

import sys

from config.settings import load_settings
from core import get_version
from core.logging import initialize_logging, shutdown_logging
from core.runtime import initialize_directories
from interface.cli import run_cli


def main() -> int:
    """Initialize without API calls; development mode opens the text CLI."""
    logger = None
    try:
        settings = load_settings()
        initialize_directories(settings)
        logger = initialize_logging(settings)
        logger.info("Application started")
        print(
            f"JARVIS\nVersion: {get_version()}\n"
            f"Environment: {settings.environment}\nStatus: Ready"
        )
        if settings.environment == "development":
            from agent.brain import Brain
            from ai.gemini import GeminiProvider
            from config.memory_settings import load_memory_settings
            from memory.repository import MemoryRepository
            from security.validator import ValidationError
            from tools.memory_tools import _set_repository
            repository = MemoryRepository(settings.data_dir / "memory.sqlite3",
                                          settings=load_memory_settings())
            try:
                repository.initialize()
                _set_repository(repository)
            except ValidationError as error:
                # Fixed identifiers only; other tools remain available.
                logger.warning("Memory unavailable (%s)", error.error_id)
                _set_repository(None)
            return run_cli(Brain(GeminiProvider()))
        return 0
    except KeyboardInterrupt:
        print("Jarvis interrupted. Shutting down.", file=sys.stderr)
        return 130
    except Exception:
        # Raw exception text can contain sensitive paths or configuration values.
        if logger is not None:
            logger.error("Application failed (STARTUP_FAILED)")
        print(
            "Jarvis could not start (STARTUP_FAILED). Check configuration and "
            "runtime directory access.",
            file=sys.stderr,
        )
        return 1
    finally:
        from tools.memory_tools import _set_repository
        _set_repository(None)
        if logger is not None:
            logger.info("Application stopped")
            shutdown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
