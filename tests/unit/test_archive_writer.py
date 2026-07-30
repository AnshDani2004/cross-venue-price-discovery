from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cross_venue.config import StorageConfig
from cross_venue.schemas import Exchange
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.archive_writer import ArchiveSessionContext, RotatingRawArchiveWriter
from cross_venue.storage.checksum import verify_sha256_sidecar


def _storage_config(tmp_path: Path, *, rotate_max_records: int = 100) -> StorageConfig:
    return StorageConfig(
        archive_root=tmp_path,
        archive_schema_version="0.1.0",
        writer_queue_capacity=10,
        writer_enqueue_timeout_seconds=1,
        flush_every_records=1,
        flush_interval_seconds=1,
        fsync_on_flush=False,
        rotate_max_records=rotate_max_records,
        rotate_max_uncompressed_bytes=1_000_000,
        rotate_max_seconds=900,
        manifest_checkpoint_every_records=100,
        manifest_checkpoint_interval_seconds=10,
        partial_file_suffix=".partial",
    )


@pytest.mark.asyncio
async def test_archive_writer_rotates_and_finalizes_checksum_sidecars(tmp_path: Path) -> None:
    writer = RotatingRawArchiveWriter(
        storage_config=_storage_config(tmp_path, rotate_max_records=2)
    )
    started = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    await writer.start(
        ArchiveSessionContext(
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            session_id="session-1",
            started_at=started,
            archive_schema_version="0.1.0",
        )
    )

    for index in range(3):
        record = writer.make_record(
            f'{{"type":"synthetic","index":{index}}}',
            local_receipt_ts=started + timedelta(seconds=index),
        )
        await writer.append(record)

    summary = await writer.close()

    assert summary.records_enqueued == 3
    assert summary.records_written == 3
    assert len(summary.shards) == 2
    assert summary.partial_files_remaining == 0
    assert summary.checksum_status == "passed"
    assert [shard.record_count for shard in summary.shards] == [2, 1]
    for shard in summary.shards:
        shard_path = summary.session_paths.session_root / shard.relative_path
        assert verify_sha256_sidecar(shard_path)


@pytest.mark.asyncio
async def test_archive_writer_records_are_in_receipt_order(tmp_path: Path) -> None:
    writer = RotatingRawArchiveWriter(storage_config=_storage_config(tmp_path))
    started = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    await writer.start(
        ArchiveSessionContext(
            venue=Exchange.KRAKEN,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC/USD",
            session_id="session-2",
            started_at=started,
            archive_schema_version="0.1.0",
        )
    )

    first = writer.make_record("first", local_receipt_ts=started)
    second = writer.make_record(b"second", local_receipt_ts=started + timedelta(milliseconds=1))
    await writer.append(first)
    await writer.append(second)
    summary = await writer.close()

    shard_path = summary.session_paths.session_root / summary.shards[0].relative_path
    records = [
        RawArchiveRecord.from_json_line(line)
        for line in shard_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record.record_index for record in records] == [0, 1]
    assert records[0].raw_frame == "first"
    assert records[1].frame_bytes() == b"second"
