from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from quality_helpers import make_session

from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import _build_findings, analyze_session_quality
from cross_venue.quality.calibration import reanalyze_calibrated_pair
from cross_venue.quality.exceptions import QualityError
from cross_venue.quality.io import persist_model_json
from cross_venue.quality.models import (
    ContinuityMetrics,
    CoverageMetrics,
    DuplicateMetrics,
    QualitySeverity,
    QuoteMetrics,
    SessionQualityMetrics,
    TimestampMetrics,
)
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.schemas import Exchange


def test_reanalyze_calibrated_pair_writes_before_after(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)

    result = reanalyze_calibrated_pair(
        paired_path,
        storage_config=storage_config,
        quality_config=quality_config,
        require_clean=False,
    )

    assert result.paired_report.quality_policy_version == "2d.2"
    assert result.comparison_json_path.exists()
    assert result.comparison["old_policy_version"] == "2d.1"
    assert result.comparison["new_policy_version"] == "2d.2"
    assert result.promotion_dry_run_path.exists()


def test_reanalyze_calibrated_pair_rejects_dirty_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)
    monkeypatch.setattr("cross_venue.quality.calibration._working_tree_clean", lambda: False)

    with pytest.raises(QualityError, match="clean working tree"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
        )


def test_reanalyze_calibrated_pair_rejects_wrong_expected_commit(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)

    with pytest.raises(QualityError, match="expected commit"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
            require_clean=False,
            expected_commit="not-the-current-commit",
        )


def test_reanalyze_calibrated_pair_rejects_changed_manifest_hash(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)
    manifest_path = next(storage_config.archive_root.rglob("session_manifest.json"))
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "coinbase-calibration",
            "coinbase-calibration-mutated",
        ),
        encoding="utf-8",
    )

    with pytest.raises(QualityError, match="source manifest changed"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
            require_clean=False,
        )


def test_low_variance_negative_offset_is_info_under_2d2(tmp_path: Path) -> None:
    _paired_path, _storage_config, quality_config = _paired_fixture(tmp_path)
    metrics = _minimal_metrics_with_delta_pattern()

    findings = _build_findings(
        venue=Exchange.KRAKEN,
        archive_valid=True,
        archive_errors=(),
        manifest_records=100,
        quality_summary_writer_failures=0,
        metrics=metrics,
        quality_config=quality_config,
    )

    delta_finding = next(item for item in findings if "DELTA_PATTERN" in item.finding_id)
    assert delta_finding.observed_value == "LOW_VARIANCE_OFFSET"
    assert delta_finding.severity == QualitySeverity.INFO


def _paired_fixture(tmp_path: Path) -> tuple[Path, StorageConfig, DataQualityConfig]:
    coinbase_session, storage_config, original_policy = asyncio.run(
        make_session(tmp_path, venue=Exchange.COINBASE, session_id="coinbase-calibration")
    )
    original_policy = original_policy.model_copy(update={"policy_version": "2d.1"})
    kraken_session, _, _ = asyncio.run(
        make_session(tmp_path, venue=Exchange.KRAKEN, session_id="kraken-calibration")
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=original_policy,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=original_policy,
    )
    paired_report = build_paired_quality_report(
        paired_collection_id="calibration-fixture",
        requested_duration_seconds=2,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=original_policy,
    )
    paired_path = original_policy.report_root / "paired" / "calibration-fixture" / "paired.json"
    persist_model_json(paired_path, paired_report)
    calibrated_policy = original_policy.model_copy(update={"policy_version": "2d.2"})
    return paired_path, storage_config, calibrated_policy


def _minimal_metrics_with_delta_pattern() -> SessionQualityMetrics:
    return SessionQualityMetrics(
        duplicates=DuplicateMetrics(
            exact_raw_duplicate_count=0,
            exact_raw_duplicate_rate=0,
            consecutive_duplicate_count=0,
            maximum_duplicate_run=0,
            first_duplicate_record_indices=(),
            duplicate_trade_id_count=0,
            duplicate_trade_id_rate=0,
            conflicting_duplicate_trade_count=0,
            exact_duplicate_trade_count=0,
            repeated_quote_state_count=0,
        ),
        continuity=ContinuityMetrics(
            coinbase_sequence_observations=0,
            coinbase_missing_sequence_count=0,
            coinbase_duplicate_sequence_count=0,
            coinbase_nonmonotonic_sequence_count=0,
            coinbase_sequence_discontinuity_count=0,
            kraken_trade_id_observations=10,
            kraken_duplicate_trade_id_count=0,
            kraken_nonmonotonic_trade_id_count=0,
            kraken_ticker_sequence_checks_skipped=True,
            reconnect_boundaries=0,
        ),
        timestamps=TimestampMetrics(
            missing_receipt_timestamps=0,
            nonmonotonic_receipt_timestamps=0,
            equal_receipt_timestamps=0,
            min_interarrival_ms=1,
            median_interarrival_ms=1,
            p95_interarrival_ms=1,
            p99_interarrival_ms=1,
            max_interarrival_ms=1,
            missing_exchange_timestamps=0,
            missing_exchange_timestamp_rate=0,
            nonmonotonic_exchange_timestamps=0,
            equal_exchange_timestamps=0,
            observed_exchange_receipt_delta_count=100,
            observed_exchange_receipt_delta_min_ms=-7,
            observed_exchange_receipt_delta_median_ms=-2,
            observed_exchange_receipt_delta_p95_ms=54,
            observed_exchange_receipt_delta_p99_ms=85,
            observed_exchange_receipt_delta_max_ms=1557,
            negative_observed_exchange_receipt_delta_count=61,
        ),
        quotes=QuoteMetrics(
            valid_quote_count=10,
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
            session_duration_seconds=120,
            frames_received=100,
            raw_records=100,
            trades=1,
            top_of_book_events=10,
            control_messages=0,
            unsupported_messages=0,
            parse_errors=0,
            exchange_errors=0,
            reconnects=0,
            connections_opened=1,
            subscription_acknowledgements=1,
            frames_per_second=1,
            trades_per_second=0.1,
            top_of_book_events_per_second=0.1,
            archive_bytes=1000,
            shard_count=1,
        ),
    )
