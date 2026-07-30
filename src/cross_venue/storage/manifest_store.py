"""Atomic persistent session manifests for raw archives."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.schemas import Exchange
from cross_venue.storage.exceptions import ManifestPersistenceError


class ShardMetadata(BaseModel):
    """Metadata for one finalized or partial raw shard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1)
    byte_size: int = Field(ge=0)
    record_count: int = Field(ge=0)
    first_record_index: int | None = Field(default=None, ge=0)
    last_record_index: int | None = Field(default=None, ge=0)
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    rotation_reason: str = Field(min_length=1)
    finalization_time: datetime | None = None
    is_partial: bool = False

    @field_validator("first_local_receipt_ts", "last_local_receipt_ts", "finalization_time")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("shard timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def record_index_range_must_be_ordered(self) -> ShardMetadata:
        if (
            self.first_record_index is not None
            and self.last_record_index is not None
            and self.last_record_index < self.first_record_index
        ):
            raise ValueError("last record index must not precede first record index")
        return self


class PersistentSessionManifest(BaseModel):
    """Persistent Phase 2C session manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    configured_channels: tuple[str, ...] = Field(min_length=1)
    collector_version: str = Field(min_length=1)
    git_commit: str = Field(min_length=1)
    archive_schema_version: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    final_state: CollectorState
    stop_reason: str = Field(min_length=1)
    failure_reason: str | None = None
    frames_received: int = Field(ge=0)
    records_enqueued: int = Field(ge=0)
    records_written: int = Field(ge=0)
    records_failed: int = Field(ge=0)
    trade_events: int = Field(ge=0)
    top_of_book_events: int = Field(ge=0)
    control_messages: int = Field(ge=0)
    unsupported_messages: int = Field(ge=0)
    exchange_errors: int = Field(ge=0)
    parse_errors: int = Field(ge=0)
    reconnect_attempts: int = Field(ge=0)
    connections_opened: int = Field(ge=0)
    subscription_requests: int = Field(ge=0)
    subscription_acknowledgements: int = Field(ge=0)
    heartbeat_messages: int = Field(ge=0)
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None
    first_exchange_ts: datetime | None = None
    last_exchange_ts: datetime | None = None
    maximum_writer_queue_depth: int = Field(ge=0)
    shards: tuple[ShardMetadata, ...] = ()
    total_archive_bytes: int = Field(ge=0)
    checksum_status: Literal["not_applicable", "passed", "failed"]
    recovery_status: Literal["not_needed", "needed", "recovered", "failed"]

    @field_validator(
        "started_at",
        "ended_at",
        "first_local_receipt_ts",
        "last_local_receipt_ts",
        "first_exchange_ts",
        "last_exchange_ts",
    )
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("manifest timestamps must be timezone-aware")
        return value


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    """Atomically replace ``path`` with pretty JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2, sort_keys=True)
            file_handle.write("\n")
            file_handle.flush()
            os.fsync(file_handle.fileno())
        temporary.replace(path)
        _fsync_parent(path.parent)
    except OSError as exc:
        raise ManifestPersistenceError(f"could not persist {path.name}") from exc


def persist_manifest(path: Path, manifest: PersistentSessionManifest) -> None:
    """Persist a session manifest atomically."""

    atomic_write_json(path, manifest.model_dump(mode="json"))


def load_manifest(path: Path) -> PersistentSessionManifest:
    """Load and validate a persistent session manifest."""

    return PersistentSessionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _fsync_parent(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
