"""Aggregate quality reports across sessions."""

from __future__ import annotations

from collections.abc import Iterable

from cross_venue.config import DataQualityConfig
from cross_venue.quality.io import utc_now
from cross_venue.quality.models import (
    AggregateQualityReport,
    QualityDisposition,
    SessionQualityReport,
)


def aggregate_quality_reports(
    reports: Iterable[SessionQualityReport],
    *,
    quality_config: DataQualityConfig,
) -> AggregateQualityReport:
    """Aggregate session-level quality reports."""

    collected = tuple(reports)
    event_rates: dict[str, float] = {}
    venue_counts: dict[str, int] = {}
    for report in collected:
        venue = report.venue.value
        event_rates[venue] = (
            event_rates.get(venue, 0.0)
            + report.metrics.coverage.trades_per_second
            + report.metrics.coverage.top_of_book_events_per_second
        )
        venue_counts[venue] = venue_counts.get(venue, 0) + 1
    averaged_rates = {
        venue: total / venue_counts[venue] for venue, total in sorted(event_rates.items())
    }
    return AggregateQualityReport(
        created_at=utc_now(),
        quality_policy_version=quality_config.policy_version,
        session_count=len(collected),
        accepted_count=sum(
            report.disposition == QualityDisposition.ACCEPTED for report in collected
        ),
        quarantined_count=sum(
            report.disposition == QualityDisposition.QUARANTINED for report in collected
        ),
        rejected_count=sum(
            report.disposition == QualityDisposition.REJECTED for report in collected
        ),
        total_duration_seconds=sum(
            report.metrics.coverage.session_duration_seconds for report in collected
        ),
        total_frames=sum(report.metrics.coverage.frames_received for report in collected),
        total_raw_bytes=sum(report.metrics.coverage.archive_bytes for report in collected),
        total_trades=sum(report.metrics.coverage.trades for report in collected),
        total_top_of_book_events=sum(
            report.metrics.coverage.top_of_book_events for report in collected
        ),
        parse_error_rates=tuple(
            _rate(report.metrics.coverage.parse_errors, report.metrics.coverage.frames_received)
            for report in collected
        ),
        unsupported_message_rates=tuple(
            _rate(
                report.metrics.coverage.unsupported_messages,
                report.metrics.coverage.frames_received,
            )
            for report in collected
        ),
        duplicate_raw_rates=tuple(
            report.metrics.duplicates.exact_raw_duplicate_rate for report in collected
        ),
        sequence_anomaly_counts=tuple(
            report.metrics.continuity.coinbase_sequence_discontinuity_count
            + report.metrics.continuity.coinbase_duplicate_sequence_count
            + report.metrics.continuity.kraken_duplicate_trade_id_count
            for report in collected
        ),
        receipt_time_anomaly_counts=tuple(
            report.metrics.timestamps.nonmonotonic_receipt_timestamps for report in collected
        ),
        stale_quote_percentages=tuple(
            report.metrics.quotes.stale_percentage_of_session for report in collected
        ),
        reconnect_counts=tuple(report.metrics.coverage.reconnects for report in collected),
        venue_event_rates=averaged_rates,
    )


def _rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))
