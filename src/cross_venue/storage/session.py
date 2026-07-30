"""Build persistent manifest and quality summaries from collector output."""

from __future__ import annotations

from datetime import UTC

from cross_venue import __version__
from cross_venue.collectors.runtime import CollectorRunSummary
from cross_venue.storage.manifest_store import PersistentSessionManifest
from cross_venue.storage.quality_store import QualitySummary


def build_manifest(summary: CollectorRunSummary, *, git_commit: str) -> PersistentSessionManifest:
    """Build a persistent manifest from a collector run summary."""

    archive = summary.archive_summary
    shards = archive.shards if archive is not None else ()
    total_bytes = archive.total_archive_bytes if archive is not None else 0
    checksum_status = archive.checksum_status if archive is not None else "not_applicable"
    return PersistentSessionManifest(
        session_id=summary.stats.session_id,
        venue=summary.stats.venue,
        canonical_instrument=summary.stats.canonical_instrument,
        venue_symbol=summary.stats.venue_symbol,
        configured_channels=summary.stats.configured_channels,
        collector_version=__version__,
        git_commit=git_commit,
        archive_schema_version="0.1.0",
        started_at=summary.stats.started_at,
        ended_at=summary.stats.ended_at,
        final_state=summary.stats.final_state,
        stop_reason=summary.stop_reason,
        failure_reason=summary.stats.failure_reason,
        frames_received=summary.stats.frames_received,
        records_enqueued=summary.stats.archive_records_enqueued,
        records_written=summary.stats.archive_records_written,
        records_failed=summary.stats.archive_records_failed,
        trade_events=summary.stats.trade_events,
        top_of_book_events=summary.stats.top_of_book_events,
        control_messages=summary.stats.control_messages,
        unsupported_messages=summary.stats.unsupported_messages,
        exchange_errors=summary.stats.exchange_errors,
        parse_errors=summary.stats.parse_errors,
        reconnect_attempts=summary.stats.reconnect_attempts,
        connections_opened=summary.stats.connections_opened,
        subscription_requests=summary.stats.subscription_requests,
        subscription_acknowledgements=summary.stats.subscription_acknowledgements,
        heartbeat_messages=summary.stats.heartbeat_messages,
        first_local_receipt_ts=summary.stats.first_local_receipt_ts,
        last_local_receipt_ts=summary.stats.last_local_receipt_ts,
        first_exchange_ts=summary.stats.first_exchange_ts,
        last_exchange_ts=summary.stats.last_exchange_ts,
        maximum_writer_queue_depth=summary.stats.maximum_writer_queue_depth,
        shards=shards,
        total_archive_bytes=total_bytes,
        checksum_status=checksum_status,
        recovery_status="not_needed",
    )


def build_quality_summary(summary: CollectorRunSummary) -> QualitySummary:
    """Build a quality summary from a collector run summary."""

    duration = 0.0
    if summary.stats.ended_at is not None:
        duration = max(
            0.0,
            summary.stats.ended_at.astimezone(UTC).timestamp()
            - summary.stats.started_at.astimezone(UTC).timestamp(),
        )
    frame_rate = summary.stats.frames_received / duration if duration > 0 else 0.0
    trade_rate = summary.stats.trade_events / duration if duration > 0 else 0.0
    book_rate = summary.stats.top_of_book_events / duration if duration > 0 else 0.0
    return QualitySummary(
        frames_received=summary.stats.frames_received,
        json_decode_failures=0,
        parse_failures=summary.stats.parse_errors,
        unsupported_messages=summary.stats.unsupported_messages,
        wrong_symbol_messages=0,
        exchange_errors=summary.stats.exchange_errors,
        timestamp_validation_failures=0,
        nonmonotonic_local_receipt_timestamps=0,
        coinbase_sequence_observations=0,
        coinbase_sequence_gaps=0,
        kraken_trade_id_observations=0,
        duplicate_sequence_values=0,
        first_local_receipt_ts=summary.stats.first_local_receipt_ts,
        last_local_receipt_ts=summary.stats.last_local_receipt_ts,
        session_duration_seconds=duration,
        frame_rate_per_second=frame_rate,
        trade_event_rate_per_second=trade_rate,
        top_of_book_event_rate_per_second=book_rate,
        reconnect_count=summary.stats.reconnect_attempts,
        partial_shard_count=(
            summary.archive_summary.partial_files_remaining
            if summary.archive_summary is not None
            else 0
        ),
        checksum_failures=(
            0
            if (
                summary.archive_summary is None
                or summary.archive_summary.checksum_status == "passed"
            )
            else 1
        ),
        writer_failures=summary.stats.archive_records_failed,
        recovery_actions=0,
    )
