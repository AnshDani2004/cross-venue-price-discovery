"""Path helpers for normalized datasets."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from cross_venue.normalization.exceptions import NormalizationError


def require_relative_portable(path: str, *, field_name: str) -> str:
    """Require a portable relative POSIX path."""

    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise NormalizationError(f"{field_name} must be a safe relative path")
    return path


def relative_to_root(root: Path, path: Path) -> str:
    """Return a POSIX path relative to root."""

    return path.resolve().relative_to(root.resolve()).as_posix()
