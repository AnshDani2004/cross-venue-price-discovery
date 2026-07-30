"""Bounded rotating raw archive writer."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TextIO

from cross_venue.config import StorageConfig
from cross_venue.schemas import Exchange
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import write_sha256_sidecar
from cross_venue.storage.exceptions import (
    ArchiveBackpressureError,
    ArchiveRotationError,
    ArchiveWriterError,
)
from cross_venue.storage.manifest_store import ShardMetadata
from cross_venue.storage.paths import SessionPaths, session_paths, shard_name


@dataclass(frozen=True, slots=True)
class ArchiveSessionContext:
    """Context needed to write one archive session."""

    venue: Exchange
    canonical_instrument: str
    venue_symbol: str
    session_id: str
    started_at: datetime
    archive_schema_version: str


@dataclass(frozen=True, slots=True)
class ArchiveSummary:
    """Raw archive writer result."""

    session_paths: SessionPaths
    shards: tuple[ShardMetadata, ...]
    records_enqueued: int
    records_written: int
    records_failed: int
    total_archive_bytes: int
    maximum_queue_depth: int
    partial_files_remaining: int
    checksum_status: Literal["not_applicable", "passed", "failed"]


@dataclass(slots=True)
class _ActiveShard:
    index: int
    partial_path: Path
    final_path: Path
    started_at: datetime
    file_handle: TextIO
    record_count: int = 0
    byte_count: int = 0
    first_record_index: int | None = None
    last_record_index: int | None = None
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None


@dataclass(slots=True)
class RotatingRawArchiveWriter:
    """Append-only JSONL raw writer with bounded enqueue."""

    storage_config: StorageConfig
    archive_root: Path | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    _context: ArchiveSessionContext | None = None
    _paths: SessionPaths | None = None
    _queue: asyncio.Queue[RawArchiveRecord | None] | None = None
    _worker_task: asyncio.Task[None] | None = None
    _active: _ActiveShard | None = None
    _shards: list[ShardMetadata] = field(default_factory=list)
    _next_record_index: int = 0
    records_enqueued: int = 0
    records_written: int = 0
    records_failed: int = 0
    total_archive_bytes: int = 0
    maximum_queue_depth: int = 0
    _failure: BaseException | None = None
    _closed: bool = False

    async def start(self, context: ArchiveSessionContext) -> None:
        """Start the writer and create session directories."""

        if self._queue is not None:
            raise ArchiveWriterError("archive writer already started")
        root = self.archive_root or self.storage_config.archive_root
        self._context = context
        self._paths = session_paths(
            archive_root=root,
            venue=context.venue,
            canonical_instrument=context.canonical_instrument,
            session_id=context.session_id,
            started_at=context.started_at,
        )
        self._paths.raw_dir.mkdir(parents=True, exist_ok=True)
        self._paths.manifest_dir.mkdir(parents=True, exist_ok=True)
        self._paths.quality_dir.mkdir(parents=True, exist_ok=True)
        self._queue = asyncio.Queue(maxsize=self.storage_config.writer_queue_capacity)
        self._worker_task = asyncio.create_task(self._worker())

    def make_record(self, frame: str | bytes, *, local_receipt_ts: datetime) -> RawArchiveRecord:
        """Build a sequential archive record for an exact frame."""

        context = self._require_context()
        record = RawArchiveRecord.from_frame(
            frame,
            archive_schema_version=context.archive_schema_version,
            record_index=self._next_record_index,
            collector_session_id=context.session_id,
            venue=context.venue,
            canonical_instrument=context.canonical_instrument,
            venue_symbol=context.venue_symbol,
            local_receipt_ts=local_receipt_ts,
        )
        self._next_record_index += 1
        return record

    async def append(self, record: RawArchiveRecord) -> None:
        """Enqueue one raw archive record or fail visibly."""

        self._raise_failure_if_any()
        if self._closed:
            raise ArchiveWriterError("archive writer is closed")
        queue = self._require_queue()
        try:
            await asyncio.wait_for(
                queue.put(record),
                timeout=self.storage_config.writer_enqueue_timeout_seconds,
            )
        except TimeoutError as exc:
            self.records_failed += 1
            raise ArchiveBackpressureError("archive writer queue enqueue timeout") from exc
        self.records_enqueued += 1
        self.maximum_queue_depth = max(self.maximum_queue_depth, queue.qsize())
        self._raise_failure_if_any()

    async def close(self, *, rotation_reason: str = "session_close") -> ArchiveSummary:
        """Drain queue and finalize active shard. Idempotent after first close."""

        if self._closed:
            return self.summary()
        self._raise_failure_if_any()
        queue = self._require_queue()
        try:
            await asyncio.wait_for(
                queue.put(None),
                timeout=self.storage_config.writer_enqueue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ArchiveBackpressureError("archive writer queue close timeout") from exc
        await queue.join()
        if self._worker_task is not None:
            await self._worker_task
        if self._active is not None:
            self._finalize_active(rotation_reason)
        self._closed = True
        self._raise_failure_if_any()
        return self.summary()

    def summary(self) -> ArchiveSummary:
        """Return current writer summary."""

        paths = self._require_paths()
        partial_count = len(list(paths.raw_dir.glob(f"*{self.storage_config.partial_file_suffix}")))
        checksum_status: Literal["not_applicable", "passed", "failed"] = (
            "passed" if self._shards else "not_applicable"
        )
        return ArchiveSummary(
            session_paths=paths,
            shards=tuple(self._shards),
            records_enqueued=self.records_enqueued,
            records_written=self.records_written,
            records_failed=self.records_failed,
            total_archive_bytes=self.total_archive_bytes,
            maximum_queue_depth=self.maximum_queue_depth,
            partial_files_remaining=partial_count,
            checksum_status=checksum_status,
        )

    async def _worker(self) -> None:
        queue = self._require_queue()
        try:
            while True:
                record = await queue.get()
                try:
                    if record is None:
                        return
                    self._write_record(record)
                finally:
                    queue.task_done()
        except BaseException as exc:
            self._failure = exc
            raise

    def _write_record(self, record: RawArchiveRecord) -> None:
        try:
            line = record.to_json_line()
            line_bytes = line.encode("utf-8")
            active = self._ensure_active(record.local_receipt_ts)
            if self._should_rotate(active, record, len(line_bytes)):
                self._finalize_active("rotation_limit")
                active = self._ensure_active(record.local_receipt_ts)
            active.file_handle.write(line)
            active.record_count += 1
            active.byte_count += len(line_bytes)
            active.first_record_index = (
                record.record_index
                if active.first_record_index is None
                else active.first_record_index
            )
            active.last_record_index = record.record_index
            active.first_local_receipt_ts = (
                record.local_receipt_ts
                if active.first_local_receipt_ts is None
                else active.first_local_receipt_ts
            )
            active.last_local_receipt_ts = record.local_receipt_ts
            self.records_written += 1
            self.total_archive_bytes += len(line_bytes)
            if active.record_count % self.storage_config.flush_every_records == 0:
                self._flush_active(active)
        except OSError as exc:
            self.records_failed += 1
            raise ArchiveWriterError("raw archive write failed") from exc

    def _ensure_active(self, receipt_ts: datetime) -> _ActiveShard:
        if self._active is not None:
            return self._active
        paths = self._require_paths()
        index = len(self._shards)
        final_path = paths.raw_dir / shard_name(index)
        partial_path = final_path.with_name(
            f"{final_path.name}{self.storage_config.partial_file_suffix}"
        )
        try:
            file_handle = partial_path.open("a", encoding="utf-8", newline="")
        except OSError as exc:
            raise ArchiveRotationError("could not open partial raw shard") from exc
        self._active = _ActiveShard(
            index=index,
            partial_path=partial_path,
            final_path=final_path,
            started_at=receipt_ts,
            file_handle=file_handle,
        )
        return self._active

    def _should_rotate(
        self,
        active: _ActiveShard,
        record: RawArchiveRecord,
        next_line_bytes: int,
    ) -> bool:
        if active.record_count == 0:
            return False
        if active.record_count >= self.storage_config.rotate_max_records:
            return True
        if active.byte_count + next_line_bytes > self.storage_config.rotate_max_uncompressed_bytes:
            return True
        age = record.local_receipt_ts.timestamp() - active.started_at.timestamp()
        return age >= self.storage_config.rotate_max_seconds

    def _finalize_active(self, rotation_reason: str) -> None:
        active = self._active
        if active is None:
            return
        if active.record_count == 0:
            active.file_handle.close()
            active.partial_path.unlink(missing_ok=True)
            self._active = None
            return
        self._flush_active(active)
        active.file_handle.close()
        try:
            active.partial_path.replace(active.final_path)
        except OSError as exc:
            raise ArchiveRotationError("could not finalize raw shard") from exc
        digest = write_sha256_sidecar(active.final_path)
        metadata = ShardMetadata(
            relative_path=f"raw/{active.final_path.name}",
            byte_size=active.final_path.stat().st_size,
            record_count=active.record_count,
            first_record_index=active.first_record_index,
            last_record_index=active.last_record_index,
            first_local_receipt_ts=active.first_local_receipt_ts,
            last_local_receipt_ts=active.last_local_receipt_ts,
            sha256=digest,
            rotation_reason=rotation_reason,
            finalization_time=self.now(),
            is_partial=False,
        )
        self._shards.append(metadata)
        self._active = None

    def _flush_active(self, active: _ActiveShard) -> None:
        active.file_handle.flush()
        if self.storage_config.fsync_on_flush:
            os.fsync(active.file_handle.fileno())

    def _require_context(self) -> ArchiveSessionContext:
        if self._context is None:
            raise ArchiveWriterError("archive writer has not started")
        return self._context

    def _require_queue(self) -> asyncio.Queue[RawArchiveRecord | None]:
        if self._queue is None:
            raise ArchiveWriterError("archive writer has not started")
        return self._queue

    def _require_paths(self) -> SessionPaths:
        if self._paths is None:
            raise ArchiveWriterError("archive writer has not started")
        return self._paths

    def _raise_failure_if_any(self) -> None:
        if self._failure is not None:
            raise ArchiveWriterError("archive writer worker failed") from self._failure
