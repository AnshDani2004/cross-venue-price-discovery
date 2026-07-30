"""Filesystem layout helpers for Phase 2C archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cross_venue.schemas import Exchange
from cross_venue.storage.exceptions import StorageError


@dataclass(frozen=True, slots=True)
class SessionPaths:
    """Resolved session archive layout."""

    session_root: Path
    raw_dir: Path
    manifest_dir: Path
    quality_dir: Path

    @property
    def manifest_path(self) -> Path:
        return self.manifest_dir / "session_manifest.json"

    @property
    def quality_path(self) -> Path:
        return self.quality_dir / "quality_summary.json"


def safe_path_component(value: str) -> str:
    """Return a filesystem-safe path component."""

    cleaned = value.replace("/", "-").replace("\\", "-").replace(" ", "-")
    cleaned = "".join(
        character for character in cleaned if character.isalnum() or character in "._=-"
    )
    if cleaned in {"", ".", ".."}:
        raise StorageError("unsafe empty path component")
    return cleaned


def resolve_under_root(root: Path, candidate: Path) -> Path:
    """Resolve a path and require that it stays under ``root``."""

    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise StorageError("path escapes archive root") from exc
    return resolved_candidate


def session_paths(
    *,
    archive_root: Path,
    venue: Exchange,
    canonical_instrument: str,
    session_id: str,
    started_at: datetime,
) -> SessionPaths:
    """Return deterministic partitioned paths for one session."""

    started_utc = started_at.astimezone(UTC)
    session_root = (
        archive_root
        / f"venue={safe_path_component(venue.value)}"
        / f"instrument={safe_path_component(canonical_instrument)}"
        / f"date={started_utc.date().isoformat()}"
        / f"session={safe_path_component(session_id)}"
    )
    session_root = resolve_under_root(archive_root, session_root)
    return SessionPaths(
        session_root=session_root,
        raw_dir=session_root / "raw",
        manifest_dir=session_root / "manifest",
        quality_dir=session_root / "quality",
    )


def shard_name(shard_index: int, *, extension: str = "jsonl") -> str:
    """Return a zero-padded shard filename."""

    if shard_index < 0:
        raise ValueError("shard index must be nonnegative")
    return f"part-{shard_index:05d}.{extension}"
