"""Bounded local filesystem primitives for direct, controlled invocation only.

No permissions/confirmation are enforced here. Modifications never overwrite or
delete. Windows rename semantics enforce no replacement at the OS call boundary.
"""

import fnmatch
import os
import stat
from collections import deque
from pathlib import Path

from config.tool_settings import (
    DEFAULT_RESULTS, MAX_RESULTS, MAX_SEARCH_DEPTH, MAX_SEARCH_ENTRIES,
    OPEN_FILE_EXTENSIONS,
)
from core.models import ExecutionResult, RiskLevel
from security.validator import (
    ValidationError, is_reparse_point, validate_local_path, validate_name,
)
from tools._support import _limit, _metadata, _safe_result

_PATH = {"type": "string", "minLength": 1}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": DEFAULT_RESULTS}
LIST_DIRECTORY_METADATA = _metadata("file.list_directory", "List bounded immediate entries without following links.", RiskLevel.READ_ONLY, {"path": _PATH, "limit": _LIMIT}, ("path",))
FIND_FILES_METADATA = _metadata("file.find_files", "Search filenames under a local root with result, entry, and depth limits; skip links.", RiskLevel.READ_ONLY, {
    "root": _PATH, "pattern": {"type": "string", "minLength": 1, "maxLength": 255, "default": "*"},
    "limit": _LIMIT,
    "max_depth": {"type": "integer", "minimum": 0, "maximum": MAX_SEARCH_DEPTH, "default": 5},
    "max_entries": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_ENTRIES, "default": MAX_SEARCH_ENTRIES},
}, ("root",))
OPEN_PATH_METADATA = _metadata("file.open_path", "Open a local directory or allowlisted document/image type using Windows association.", RiskLevel.LOW, {"path": _PATH}, ("path",))
CREATE_DIRECTORY_METADATA = _metadata("file.create_directory", "Create one new directory under an existing local parent; never overwrite.", RiskLevel.MEDIUM, {"path": _PATH}, ("path",))
RENAME_PATH_METADATA = _metadata("file.rename_path", "Rename a local file/directory to a new sibling name without replacement.", RiskLevel.MEDIUM, {"path": _PATH, "new_name": _PATH}, ("path", "new_name"))
MOVE_PATH_METADATA = _metadata("file.move_path", "Move to an exact new local path on the same volume without replacement.", RiskLevel.MEDIUM, {"source": _PATH, "destination": _PATH}, ("source", "destination"))


@_safe_result
def list_directory(path: str | Path, limit: int = DEFAULT_RESULTS) -> ExecutionResult:
    _limit(limit, MAX_RESULTS)
    root = validate_local_path(path, directory=True)
    entries = []
    skipped = 0
    limited = False
    with os.scandir(root) as iterator:
        for index, entry in enumerate(iterator):
            if index >= limit:
                limited = True
                break
            try:
                info = entry.stat(follow_symlinks=False)
                kind = (
                    "link_or_reparse_point" if is_reparse_point(info)
                    else "directory" if stat.S_ISDIR(info.st_mode)
                    else "file" if stat.S_ISREG(info.st_mode) else "other"
                )
                entries.append({"name": entry.name, "type": kind})
            except OSError:
                skipped += 1
    entries.sort(key=lambda entry: entry["name"].casefold())
    return ExecutionResult(True, "Directory summary retrieved.", {
        "entries": entries, "limit_reached": limited, "skipped": skipped,
    })


@_safe_result
def find_files(
    root: str | Path, pattern: str = "*", limit: int = DEFAULT_RESULTS,
    max_depth: int = 5, max_entries: int = MAX_SEARCH_ENTRIES,
) -> ExecutionResult:
    """Case-insensitive filename glob; depth 0 examines only the root directory."""
    _limit(limit, MAX_RESULTS)
    _limit(max_entries, MAX_SEARCH_ENTRIES)
    if type(max_depth) is not int or not 0 <= max_depth <= MAX_SEARCH_DEPTH:
        raise ValidationError("INVALID_ARGUMENT")
    if (
        not isinstance(pattern, str) or not pattern or len(pattern) > 255
        or any(char in pattern for char in "/\\:")
        or any(ord(char) < 32 for char in pattern)
    ):
        raise ValidationError("INVALID_ARGUMENT")
    base = validate_local_path(root, directory=True)
    pending = deque([(base, 0)])
    found: list[str] = []
    scanned = skipped = 0
    limited = depth_limited = False
    while pending and not limited:
        current, depth = pending.popleft()
        try:
            current = validate_local_path(current, directory=True)
            with os.scandir(current) as iterator:
                for entry in iterator:
                    if scanned >= max_entries:
                        limited = True
                        break
                    scanned += 1
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if is_reparse_point(info):
                            skipped += 1
                        elif stat.S_ISDIR(info.st_mode):
                            if depth < max_depth:
                                pending.append((Path(entry.path), depth + 1))
                            else:
                                depth_limited = True
                        elif stat.S_ISREG(info.st_mode) and fnmatch.fnmatchcase(entry.name.casefold(), pattern.casefold()):
                            found.append(str(Path(entry.path).relative_to(base)))
                            if len(found) >= limit:
                                limited = True
                                break
                    except OSError:
                        skipped += 1
        except (OSError, ValidationError):
            if current == base:
                raise
            skipped += 1
    found.sort(key=str.casefold)
    return ExecutionResult(True, "Bounded filename search completed.", {
        "files": found, "scanned_entries": scanned, "skipped": skipped,
        "limit_reached": limited, "depth_limited": depth_limited,
    })


@_safe_result
def open_path(path: str | Path) -> ExecutionResult:
    local = validate_local_path(path)
    if not local.is_dir() and (
        not local.is_file() or local.suffix.lower() not in OPEN_FILE_EXTENSIONS
    ):
        raise ValidationError("UNSUPPORTED_FILE_TYPE")
    if os.name != "nt":
        raise ValidationError("UNSUPPORTED_PLATFORM")
    os.startfile(str(local), "open")
    return ExecutionResult(True, "Associated application launch requested; readiness is not verified.", {
        "launch_requested": True,
    })


def _new_destination(path: str | Path) -> Path:
    destination = validate_local_path(path, must_exist=False)
    if destination.exists():
        raise ValidationError("DESTINATION_EXISTS")
    validate_local_path(destination.parent, directory=True)
    return destination


@_safe_result
def create_directory(path: str | Path) -> ExecutionResult:
    destination = _new_destination(path)
    destination.mkdir()  # Exactly one directory, fail if another actor creates it.
    return ExecutionResult(True, "Directory created.")


def _move_without_replacement(source: Path, destination: Path) -> ExecutionResult:
    if os.name != "nt":
        # POSIX rename can replace existing files; never silently weaken safety.
        raise ValidationError("UNSUPPORTED_PLATFORM")
    if source == Path(source.anchor) or destination.is_relative_to(source):
        raise ValidationError("INVALID_PATH")
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise ValidationError("CROSS_DEVICE_MOVE")
    # Windows os.rename fails if destination exists, even if it appeared after
    # prevalidation. No replace(), shutil.move(), cross-drive copy, or deletion.
    os.rename(source, destination)
    return ExecutionResult(True, "Path moved without replacement.")


@_safe_result
def rename_path(path: str | Path, new_name: str) -> ExecutionResult:
    source = validate_local_path(path)
    name = validate_name(new_name)
    destination = _new_destination(source.with_name(name))
    return _move_without_replacement(source, destination)


@_safe_result
def move_path(source: str | Path, destination: str | Path) -> ExecutionResult:
    original = validate_local_path(source)
    target = _new_destination(destination)
    return _move_without_replacement(original, target)
