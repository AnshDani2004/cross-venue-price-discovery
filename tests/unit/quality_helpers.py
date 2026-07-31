from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.collectors.runtime import CollectorRunSummary, SessionStatistics
from cross_venue.config import (
    DataQualityConfig,
    QualityConfigSections,
    QualityCoverageConfig,
    QualityDecisionConfig,
    QualityDuplicateConfig,
    QualityIntegrityConfig,
    QualityParsingConfig,
    QualityTimestampConfig,
    StorageConfig,
)
from cross_venue.schemas import Exchange
from cross_venue.storage.archive_writer import ArchiveSessionContext, RotatingRawArchiveWriter
from cross_venue.storage.manifest_store import persist_manifest
from cross_venue.storage.quality_store import persist_quality_summary
from cross_venue.storage.session import build_manifest, build_quality_summary


def storage_config(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        archive_root=tmp_path / "raw",
        archive_schema_version="0.1.0",
        writer_queue_capacity=100,
        writer_enqueue_timeout_seconds=1,
        flush_every_records=1,
        flush_interval_seconds=1,
        fsync_on_flush=False,
        rotate_max_records=1000,
        rotate_max_uncompressed_bytes=1_000_000,
        rotate_max_seconds=900,
        manifest_checkpoint_every_records=100,
        manifest_checkpoint_interval_seconds=10,
        partial_file_suffix=".partial",
    )


def quality_config(tmp_path: Path, *, min_duration: float = 2) -> DataQualityConfig:
    return DataQualityConfig(
        policy_version="test-policy",
        effective_date=datetime(2026, 7, 30, tzinfo=UTC).date(),
        report_root=tmp_path / "quality",
        validated_manifest_root=tmp_path / "validated",
        default_controlled_duration_seconds=min_duration,
        max_controlled_duration_seconds=300,
        max_messages_per_venue=20_000,
        quality=QualityConfigSections(
            integrity=QualityIntegrityConfig(
                require_archive_validation=True,
                require_all_checksums=True,
                allow_partial_shards=False,
                allow_writer_errors=False,
                allow_missing_manifest=False,
                allow_missing_quality_summary=False,
            ),
            parsing=QualityParsingConfig(
                max_parse_error_rate=0.01,
                max_unsupported_message_rate=0.5,
                max_wrong_symbol_messages=0,
            ),
            timestamps=QualityTimestampConfig(
                max_nonmonotonic_receipt_events=0,
                max_missing_exchange_timestamp_rate=0.05,
                stale_quote_threshold_ms=2_000,
            ),
            coverage=QualityCoverageConfig(
                minimum_session_duration_seconds=min_duration,
                minimum_frames_per_venue=2,
                minimum_trades_per_venue=1,
                minimum_top_of_book_events_per_venue=1,
                minimum_cross_venue_overlap_seconds=min_duration / 2,
                maximum_start_skew_seconds=15,
            ),
            duplicates=QualityDuplicateConfig(
                max_exact_raw_duplicate_rate=0.25,
                max_duplicate_trade_id_rate=0.25,
            ),
            decisions=QualityDecisionConfig(
                quarantine_on_sequence_anomaly=True,
                quarantine_on_timestamp_outlier=True,
                quarantine_on_duplicate_warning=True,
                quarantine_on_stale_quote_warning=True,
            ),
        ),
    )


def coinbase_trade(sequence: int, trade_id: int, receipt_second: int) -> str:
    return (
        '{"type":"match","trade_id":'
        f'{trade_id},"sequence":{sequence},"product_id":"BTC-USD",'
        '"side":"buy","price":"100.00","size":"0.10",'
        f'"time":"2026-07-30T21:00:{receipt_second:02d}Z"'
        "}"
    )


def coinbase_ticker(
    sequence: int, receipt_second: int, *, bid: str = "100.00", ask: str = "100.10"
) -> str:
    return (
        '{"type":"ticker","sequence":'
        f'{sequence},"product_id":"BTC-USD","best_bid":"{bid}",'
        f'"best_bid_size":"1.0","best_ask":"{ask}","best_ask_size":"2.0",'
        f'"time":"2026-07-30T21:00:{receipt_second:02d}Z"'
        "}"
    )


def kraken_trade(trade_id: int, receipt_second: int) -> str:
    return (
        '{"channel":"trade","type":"update","data":[{"symbol":"BTC/USD",'
        f'"side":"buy","price":"100.00","qty":"0.10","trade_id":{trade_id},'
        f'"timestamp":"2026-07-30T21:00:{receipt_second:02d}Z"'
        "}]}"
    )


def kraken_ticker(receipt_second: int, *, bid: str = "100.00", ask: str = "100.10") -> str:
    return (
        '{"channel":"ticker","type":"update","data":[{"symbol":"BTC/USD",'
        f'"bid":"{bid}","bid_qty":"1.0","ask":"{ask}","ask_qty":"2.0",'
        f'"timestamp":"2026-07-30T21:00:{receipt_second:02d}Z"'
        "}]}"
    )


async def make_session(
    tmp_path: Path,
    *,
    venue: Exchange = Exchange.COINBASE,
    frames: tuple[str, ...] | None = None,
    duration_seconds: float = 2,
    session_id: str | None = None,
) -> tuple[Path, StorageConfig, DataQualityConfig]:
    store = storage_config(tmp_path)
    policy = quality_config(tmp_path, min_duration=duration_seconds)
    started = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    venue_symbol = "BTC-USD" if venue == Exchange.COINBASE else "BTC/USD"
    channels = (
        ("matches", "ticker", "heartbeat") if venue == Exchange.COINBASE else ("trade", "ticker")
    )
    default_frames = (
        (coinbase_trade(1, 1, 0), coinbase_ticker(2, 1))
        if venue == Exchange.COINBASE
        else (kraken_trade(1, 0), kraken_ticker(1))
    )
    payloads = frames or default_frames
    writer = RotatingRawArchiveWriter(storage_config=store)
    actual_session_id = session_id or f"{venue.value}-session"
    await writer.start(
        ArchiveSessionContext(
            venue=venue,
            canonical_instrument="BTC-USD",
            venue_symbol=venue_symbol,
            session_id=actual_session_id,
            started_at=started,
            archive_schema_version="0.1.0",
        )
    )
    for index, frame in enumerate(payloads):
        await writer.append(
            writer.make_record(frame, local_receipt_ts=started + timedelta(seconds=index))
        )
    archive_summary = await writer.close()
    stats = SessionStatistics(
        venue=venue,
        canonical_instrument="BTC-USD",
        venue_symbol=venue_symbol,
        configured_channels=channels,
        session_id=actual_session_id,
        started_at=started,
        ended_at=started + timedelta(seconds=duration_seconds),
        frames_received=len(payloads),
        trade_events=sum("match" in frame or '"channel":"trade"' in frame for frame in payloads),
        top_of_book_events=sum("ticker" in frame for frame in payloads),
        archive_records_enqueued=archive_summary.records_enqueued,
        archive_records_written=archive_summary.records_written,
        archive_records_failed=archive_summary.records_failed,
        maximum_writer_queue_depth=archive_summary.maximum_queue_depth,
        final_state=CollectorState.STOPPED,
        connections_opened=1,
        subscription_acknowledgements=1,
    )
    summary = CollectorRunSummary(
        stats=stats,
        subscription_acknowledged=True,
        stop_reason="synthetic complete",
        archive_summary=archive_summary,
        data_persisted=True,
    )
    persist_manifest(
        archive_summary.session_paths.manifest_path, build_manifest(summary, git_commit="test")
    )
    persist_quality_summary(
        archive_summary.session_paths.quality_path, build_quality_summary(summary)
    )
    return archive_summary.session_paths.session_root, store, policy
