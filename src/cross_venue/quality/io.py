"""Portable persistence helpers for Phase 2D quality artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cross_venue.storage.manifest_store import atomic_write_json
from cross_venue.storage.paths import resolve_under_root


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""

    return datetime.now(UTC)


def current_git_commit() -> str:
    """Return current Git commit or ``unknown`` when unavailable."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def sha256_bytes(data: bytes) -> str:
    """Return SHA-256 hex digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return SHA-256 hex digest for text."""

    return sha256_bytes(text.encode("utf-8"))


def model_sha256(model: BaseModel) -> str:
    """Return deterministic SHA-256 for a Pydantic model JSON payload."""

    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256_text(payload)


def persist_model_json(path: Path, model: BaseModel) -> None:
    """Persist a Pydantic model as pretty JSON atomically."""

    atomic_write_json(path, model.model_dump(mode="json"))


def load_json_model(path: Path, model_type: type[BaseModel]) -> BaseModel:
    """Load a Pydantic model from JSON."""

    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def portable_relative_path(root: Path, path: Path) -> str:
    """Return POSIX relative path below root after symlink-safe resolution."""

    resolved = resolve_under_root(root, path)
    return resolved.relative_to(root.resolve()).as_posix()


def jsonable(value: Any) -> Any:
    """Convert BaseModel-like values to JSON-compatible containers."""

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value
