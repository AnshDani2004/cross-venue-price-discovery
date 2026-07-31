from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cross_venue.quality.models import (
    ContinuityMetrics,
    CoverageMetrics,
    CrossVenueOverlapReport,
    DuplicateMetrics,
    QualityDisposition,
    QualityFinding,
    QualitySeverity,
    QuoteMetrics,
    SessionQualityMetrics,
    SessionQualityReport,
    TimestampMetrics,
)
from cross_venue.schemas import Exchange


def _metrics() -> SessionQualityMetrics:
    return SessionQualityMetrics(
        duplicates=DuplicateMetrics(
            exact_raw_duplicate_count=0,
            exact_raw_duplicate_rate=0,
            consecutive_duplicate_count=0,
            maximum_duplicate_run=0,
            duplicate_trade_id_count=0,
            duplicate_trade_id_rate=0,
            conflicting_duplicate_trade_count=0,
            exact_duplicate_trade_count=0,
            repeated_quote_state_count=0,
        ),
        continuity=ContinuityMetrics(
            coinbase_sequence_observations=1,
            coinbase_missing_sequence_count=0,
            coinbase_duplicate_sequence_count=0,
            coinbase_nonmonotonic_sequence_count=0,
            coinbase_sequence_discontinuity_count=0,
            kraken_trade_id_observations=0,
            kraken_duplicate_trade_id_count=0,
            kraken_nonmonotonic_trade_id_count=0,
            reconnect_boundaries=0,
        ),
        timestamps=TimestampMetrics(
            missing_receipt_timestamps=0,
            nonmonotonic_receipt_timestamps=0,
            equal_receipt_timestamps=0,
            missing_exchange_timestamps=0,
            missing_exchange_timestamp_rate=0,
            nonmonotonic_exchange_timestamps=0,
            equal_exchange_timestamps=0,
            observed_exchange_receipt_delta_count=1,
            negative_observed_exchange_receipt_delta_count=0,
        ),
        quotes=QuoteMetrics(
            valid_quote_count=1,
            locked_market_count=0,
            crossed_market_count=0,
            missing_bid_count=0,
            missing_ask_count=0,
            nonpositive_price_count=0,
            negative_size_count=0,
            zero_bid_size_count=0,
            zero_ask_size_count=0,
            repeated_quote_state_count=0,
            bid_only_change_count=0,
            ask_only_change_count=0,
            both_side_change_count=0,
            timestamp_reversal_count=0,
            stale_interval_count=0,
            stale_total_duration_seconds=0,
            stale_max_duration_seconds=0,
            stale_percentage_of_session=0,
        ),
        coverage=CoverageMetrics(
            session_duration_seconds=2,
            frames_received=2,
            raw_records=2,
            trades=1,
            top_of_book_events=1,
            control_messages=0,
            unsupported_messages=0,
            parse_errors=0,
            exchange_errors=0,
            reconnects=0,
            connections_opened=1,
            subscription_acknowledgements=1,
            frames_per_second=1,
            trades_per_second=0.5,
            top_of_book_events_per_second=0.5,
            archive_bytes=100,
            shard_count=1,
        ),
    )


def test_quality_finding_requires_evidence_and_known_severity() -> None:
    finding = QualityFinding(
        finding_id="TEST",
        category="integrity",
        severity=QualitySeverity.INFO,
        metric="records",
        observed_value=1,
        message="ok",
        evidence={"record": 1},
    )
    assert finding.severity == QualitySeverity.INFO

    with pytest.raises(ValidationError):
        QualityFinding(
            finding_id="TEST",
            category="integrity",
            severity="BAD",
            metric="records",
            observed_value=1,
            message="bad",
            evidence={"record": 1},
        )
    with pytest.raises(ValidationError, match="at least 1"):
        QualityFinding(
            finding_id="TEST",
            category="integrity",
            severity=QualitySeverity.INFO,
            metric="records",
            observed_value=1,
            message="bad",
            evidence={},
        )


def test_accepted_report_cannot_contain_critical_finding() -> None:
    critical = QualityFinding(
        finding_id="CRIT",
        category="integrity",
        severity=QualitySeverity.CRITICAL,
        metric="archive",
        observed_value=False,
        threshold=True,
        message="broken",
        evidence={"archive": False},
    )

    with pytest.raises(ValidationError, match="accepted report cannot contain critical"):
        SessionQualityReport(
            report_id="r1",
            session_id="s1",
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            source_session_relative_path="venue=coinbase/session=s1",
            source_manifest_sha256="a" * 64,
            quality_policy_version="test",
            quality_code_git_commit="test",
            analysis_timestamp=datetime(2026, 7, 30, tzinfo=UTC),
            input_shard_checksums={"raw/part-00000.jsonl": "b" * 64},
            archive_validation_passed=True,
            metrics=_metrics(),
            findings=(critical,),
            disposition=QualityDisposition.ACCEPTED,
        )


def test_overlap_report_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        CrossVenueOverlapReport(
            paired_collection_id="pair",
            requested_duration_seconds=2,
            start_skew_seconds=0,
            coinbase_session_id="c",
            kraken_session_id="k",
            market_event_overlap_start=datetime(2026, 7, 30),  # noqa: DTZ001
            market_event_overlap_duration_seconds=1,
            top_of_book_overlap_duration_seconds=1,
            coinbase_overlap_coverage_rate=1,
            kraken_overlap_coverage_rate=1,
            reconnect_boundaries_during_overlap=0,
            stale_intervals_during_overlap=0,
        )
