"""Jarvis Stage 1 application entry point."""

import sys

from config.settings import load_settings
from core import get_version
from core.logging import initialize_logging, shutdown_logging
from core.runtime import initialize_directories


def main() -> int:
    """Initialize the foundation, report readiness, and shut down cleanly."""
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
        if logger is not None:
            logger.info("Application stopped")
            shutdown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
