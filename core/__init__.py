"""Shared infrastructure and the canonical application version."""

__version__ = "0.6.1"


def get_version() -> str:
    """Return the version from its single executable source."""
    return __version__
