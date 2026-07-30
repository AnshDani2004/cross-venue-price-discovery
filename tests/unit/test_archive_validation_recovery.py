from datetime import UTC, datetime
from pathlib import Path

import pytest

from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.collectors.runtime import CollectorRunSummary, SessionStatistics
from cross_venue.config import StorageConfig
from cross_venue.schemas import Exchange
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.archive_writer import ArchiveSessionContext, RotatingRawArchiveWriter
from cross_venue.storage.manifest_store import persist_manifest
from cross_venue.storage.quality_store import persist_quality_summary
from cross_venue.storage.recovery import recover_session
from cross_venue.storage.session import build_manifest, build_quality_summary
from cross_venue.storage.validation import validate_archive


def _storage_config(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        archive_root=tmp_path,
        archive_schema_version="0.1.0",
        writer_queue_capacity=10,
        writer_enqueue_timeout_seconds=1,
        flush_every_records=1,
        flush_interval_seconds=1,
        fsync_on_flush=False,
        rotate_max_records=100,
        rotate_max_uncompressed_bytes=1_000_000,
        rotate_max_seconds=900,
        manifest_checkpoint_every_records=100,
        manifest_checkpoint_interval_seconds=10,
        partial_file_suffix=".partial",
    )


async def _finished_session(tmp_path: Path) -> CollectorRunSummary:
    started = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    writer = RotatingRawArchiveWriter(storage_config=_storage_config(tmp_path))
    await writer.start(
        ArchiveSessionContext(
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            session_id="session-validate",
            started_at=started,
            archive_schema_version="0.1.0",
        )
    )
    await writer.append(writer.make_record('{"type":"synthetic"}', local_receipt_ts=started))
    archive_summary = await writer.close()
    stats = SessionStatistics(
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        configured_channels=("matches", "ticker", "heartbeat"),
        session_id="session-validate",
        started_at=started,
        ended_at=started,
        frames_received=1,
        archive_records_enqueued=archive_summary.records_enqueued,
        archive_records_written=archive_summary.records_written,
        archive_records_failed=archive_summary.records_failed,
        maximum_writer_queue_depth=archive_summary.maximum_queue_depth,
        final_state=CollectorState.STOPPED,
    )
    summary = CollectorRunSummary(
        stats=stats,
        subscription_acknowledged=True,
        stop_reason="message limit reached",
        archive_summary=archive_summary,
        data_persisted=True,
    )
    persist_manifest(
        archive_summary.session_paths.manifest_path,
        build_manifest(summary, git_commit="test"),
    )
    persist_quality_summary(
        archive_summary.session_paths.quality_path,
        build_quality_summary(summary),
    )
    return summary


@pytest.mark.asyncio
async def test_archive_validation_accepts_finalized_session(tmp_path: Path) -> None:
    summary = await _finished_session(tmp_path)
    archive = summary.archive_summary
    assert archive is not None

    result = validate_archive(archive.session_paths.session_root)

    assert result.valid
    assert result.records_checked == 1
    assert result.shards_checked == 1


@pytest.mark.asyncio
async def test_archive_validation_rejects_checksum_mismatch(tmp_path: Path) -> None:
    summary = await _finished_session(tmp_path)
    archive = summary.archive_summary
    assert archive is not None
    shard_path = archive.session_paths.session_root / archive.shards[0].relative_path
    with shard_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write("\n")

    result = validate_archive(archive.session_paths.session_root)

    assert not result.valid
    assert any("checksum mismatch" in error for error in result.errors)


def test_recovery_dry_run_and_apply_preserve_valid_prefix(tmp_path: Path) -> None:
    started = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    session_path = tmp_path / "session=recover"
    raw_dir = session_path / "raw"
    raw_dir.mkdir(parents=True)
    record = RawArchiveRecord.from_frame(
        "{}",
        archive_schema_version="0.1.0",
        record_index=0,
        collector_session_id="session-recover",
        venue=Exchange.KRAKEN,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC/USD",
        local_receipt_ts=started,
    )
    partial = raw_dir / "part-00000.jsonl.partial"
    partial.write_bytes(record.to_json_line().encode("utf-8") + b'{"truncated":')

    dry_run = recover_session(session_path)
    applied = recover_session(session_path, apply=True)

    final_path = raw_dir / "part-00000.jsonl"
    assert dry_run.successful
    assert not dry_run.actions[0].applied
    assert applied.successful
    assert final_path.exists()
    assert final_path.with_name("part-00000.jsonl.sha256").exists()
    assert partial.with_name("part-00000.jsonl.partial.original").exists()
    assert not partial.exists()
    assert RawArchiveRecord.from_json_line(final_path.read_text(encoding="utf-8")) == record
