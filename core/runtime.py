"""Non-destructive initialization of application-owned runtime directories."""

from config.settings import Settings


def initialize_directories(settings: Settings) -> None:
    """Create missing directories, preserving existing files and directories.

    Existing files at the configured paths cause an error. No cleanup, deletion,
    or rollback of directories is attempted on failure.
    """
    paths = (settings.data_dir, settings.log_dir)
    for path in paths:
        if path.exists() and not path.is_dir():
            raise NotADirectoryError("A runtime directory path is occupied by a file")
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
