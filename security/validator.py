"""Stage 2 input checks, not a sandbox or an active permission engine.

Checks cannot eliminate races with concurrent filesystem changes. Call tools only
on trusted local trees. Stage 4 must establish authorization and stronger boundaries.
"""

import ctypes
import ipaddress
import os
import re
import stat
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit, urlunsplit

from config.settings import PROJECT_ROOT


class ValidationError(ValueError):
    """Internal rejection carrying a stable identifier, never caller input."""

    def __init__(self, error_id: str) -> None:
        self.error_id = error_id
        super().__init__(error_id)


def is_reparse_point(info: os.stat_result) -> bool:
    """Recognize symlinks and Windows junctions/other reparse-point types."""
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _require_local_drive(path: Path) -> None:
    if os.name == "nt":
        get_drive_type = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        # Only removable, fixed, optical, and RAM drives; reject unknown/network.
        if get_drive_type(path.anchor) not in {2, 3, 5, 6}:
            raise ValidationError("UNSAFE_PATH")


def validate_name(name: str) -> str:
    """Require one ordinary Windows filename, with no path/ADS/device syntax."""
    if (
        not isinstance(name, str) or not name or name in {".", ".."}
        or name[-1:] in {" ", "."}
        or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
        or name.split(".")[0].rstrip(" ").upper() in {
            "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
            *(f"{prefix}{digit}" for prefix in ("COM", "LPT")
              for digit in "123456789¹²³"),
        }
    ):
        raise ValidationError("INVALID_PATH")
    return name


def validate_local_path(
    value: str | Path, *, must_exist: bool = True, directory: bool = False,
) -> Path:
    """Resolve local paths relative to the project, rejecting ambiguous syntax.

    Reject parent traversal, UNC/device/drive-relative paths, alternate streams,
    reserved names, and any existing symlink/reparse-point component before resolve.
    """
    if not isinstance(value, (str, Path)):
        raise ValidationError("INVALID_PATH")
    text = str(value)
    if not text.strip() or any(ord(char) < 32 for char in text):
        raise ValidationError("INVALID_PATH")
    windows = PureWindowsPath(text)
    if text.startswith(("\\", "//")) or (windows.drive and not windows.root):
        raise ValidationError("INVALID_PATH")
    if os.name != "nt" and (windows.drive or "\\" in text):
        raise ValidationError("INVALID_PATH")
    path = Path(text)
    for part in path.parts:
        if part != path.anchor:
            validate_name(part)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    _require_local_drive(path)
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if is_reparse_point(info):
            raise ValidationError("UNSAFE_PATH")
    resolved = path.resolve(strict=must_exist)
    if directory and not resolved.is_dir():
        raise ValidationError("NOT_A_DIRECTORY")
    return resolved


def validate_url(value: str) -> str:
    """Validate HTTP(S) structure without DNS lookup, fetching, or redirect checks."""
    if (
        not isinstance(value, str) or not value or len(value) > 8192
        or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        or "\\" in value or re.search(r"%(?![0-9a-fA-F]{2})", value)
    ):
        raise ValidationError("INVALID_URL")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"}:
            raise ValidationError("UNSUPPORTED_URL_SCHEME")
        if not parts.netloc or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValidationError("INVALID_URL")
        host = parts.hostname
        port = parts.port  # Evaluating also validates the numeric port range.
        if parts.netloc.endswith(":") or (port is not None and port == 0):
            raise ValidationError("INVALID_URL")
        if ":" in host:
            if not re.fullmatch(r"\[[^\]]+\](?::[0-9]+)?", parts.netloc):
                raise ValueError
            ipaddress.IPv6Address(host)
            if "%" in host:
                raise ValueError
            host = f"[{host}]"
        else:
            host = host.encode("idna").decode("ascii")
            if len(host) > 253 or any(
                not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in (host[:-1] if host.endswith(".") else host).split(".")
            ):
                raise ValueError
            if re.fullmatch(r"[0-9.]+", host):
                ipaddress.IPv4Address(host)
        authority = host if port is None else f"{host}:{port}"
        return urlunsplit((parts.scheme.lower(), authority, parts.path, parts.query, parts.fragment))
    except (ValueError, UnicodeError) as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError("INVALID_URL") from None
