"""Stable identifiers and semantic hashes for normalized rows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def stable_event_id(components: Sequence[str | int]) -> str:
    """Return a SHA-256 identifier from an unambiguous canonical component list."""

    payload = json.dumps(list(components), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_source_event_id(
    *,
    venue: str,
    session_id: str,
    source_shard_relative_path: str,
    source_raw_record_index: int,
    normalized_event_type: str,
    normalized_child_index: int,
) -> str:
    """Return a dataset-independent event ID from immutable source lineage."""

    return stable_event_id(
        [
            venue,
            session_id,
            source_shard_relative_path,
            source_raw_record_index,
            normalized_event_type,
            normalized_child_index,
        ]
    )


def semantic_row_hash(row: Mapping[str, Any], columns: Sequence[str]) -> str:
    """Hash one row using stable ordered JSON-compatible values."""

    encoded = [_canonical_value(row.get(column)) for column in columns]
    payload = json.dumps(encoded, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_table_hash(rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> str:
    """Hash ordered row hashes for one table."""

    digest = hashlib.sha256()
    for row in rows:
        digest.update(semantic_row_hash(row, columns).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def combine_hashes(parts: Sequence[str]) -> str:
    """Combine already-computed hashes deterministically."""

    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    return value
