"""Phase 4A preliminary readiness diagnostics tests.

Validates:
  - Interarrival timing math (sorted, non-null, fewer-than-two edge cases)
  - Partitioned manifest path handling
  - Paired overlap computation using exchange timestamps
  - Per-attempt threshold compatible with campaign design (1800s, not 3600s)
  - Distinct readiness flags: structural / preliminary / final-composite
  - Ineligible dataset rejection
  - Missing trade file raises ResearchError
  - Optional missing BBO is allowed (warning, not error)
  - Duplicate timestamp counting excludes nulls
  - Report written under dataset_root/diagnostics/
  - All accepted attempts receive diagnostics
  - Threshold is sourced from campaign config (1800s)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from cross_venue.research.exceptions import ResearchError
from cross_venue.research.preliminary_diagnostics import (
    MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT,
    MINIMUM_TOTAL_OVERLAP_SECONDS,
    PreliminaryReadinessReport,
    analyze_preliminary_readiness,
    compute_interarrivals,
)

# ---------------------------------------------------------------------------
# Interarrival math
# ---------------------------------------------------------------------------


def test_compute_interarrivals_basic() -> None:
    """3 timestamps 1 s apart → median interarrival is 1000 ms."""
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 1, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 2, tzinfo=UTC),
            ]
        }
    )
    val = compute_interarrivals(df, "exchange_timestamp_utc")
    assert val == pytest.approx(1000.0)


def test_compute_interarrivals_mixed_gaps() -> None:
    """Gaps of 1 s and 2 s → median is 1500 ms."""
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 1, tzinfo=UTC),  # +1000 ms
                datetime(2026, 1, 1, 10, 0, 3, tzinfo=UTC),  # +2000 ms
            ]
        }
    )
    val = compute_interarrivals(df, "exchange_timestamp_utc")
    assert val == pytest.approx(1500.0)


def test_compute_interarrivals_single_row() -> None:
    """Fewer than two rows → None."""
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
            ]
        }
    )
    assert compute_interarrivals(df, "exchange_timestamp_utc") is None


def test_compute_interarrivals_zero_rows() -> None:
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": pl.Series(
                [], dtype=pl.Datetime(time_unit="us", time_zone="UTC")
            )
        }
    )
    assert compute_interarrivals(df, "exchange_timestamp_utc") is None


def test_compute_interarrivals_ignores_nulls() -> None:
    """Null values must be excluded before counting."""
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                None,
                datetime(2026, 1, 1, 10, 0, 2, tzinfo=UTC),
            ]
        }
    )
    # Only two non-null → one interarrival of 2000 ms
    val = compute_interarrivals(df, "exchange_timestamp_utc")
    assert val == pytest.approx(2000.0)


def test_compute_interarrivals_sorts_before_diff() -> None:
    """Out-of-order timestamps must be sorted before computing interarrivals."""
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                datetime(2026, 1, 1, 10, 0, 2, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 10, 0, 1, tzinfo=UTC),
            ]
        }
    )
    val = compute_interarrivals(df, "exchange_timestamp_utc")
    assert val == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Threshold compliance with campaign design
# ---------------------------------------------------------------------------


def test_minimum_overlap_threshold_is_campaign_compatible() -> None:
    """Per-attempt threshold must be <= requested_duration_seconds (1860 s)."""
    assert MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT <= 1860.0, (
        f"Threshold {MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT}s exceeds "
        "the 1860s requested slot duration — no slot could ever pass"
    )
    assert MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT == 1800.0, (
        "Threshold must match configs/campaigns/phase_3b_btc_usd.toml: "
        "minimum_overlap_seconds_per_accepted_session = 1800"
    )


def test_minimum_total_overlap_is_campaign_compatible() -> None:
    assert MINIMUM_TOTAL_OVERLAP_SECONDS == 18_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_validation_report(
    dataset_root: Path,
    *,
    eligibility: str = "ELIGIBLE",
    disposition: str = "VALID",
    final_composite: str = "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED",
    report_id: str = "test-report-id",
) -> Path:
    report: dict[str, Any] = {
        "validation_schema_version": "3c-normalized-validation.1",
        "validation_report_id": report_id,
        "source_snapshot_id": "snap-1",
        "source_snapshot_content_hash": "snap-hash",
        "source_catalog_id": "cat-1",
        "source_catalog_content_hash": "cat-hash",
        "validation_timestamp": "2026-08-01T00:00:00Z",
        "validation_code_identity": "c0mm1t",
        "normalization_code_identity": "c0mm1t",
        "normalized_manifest_hash": "abc",
        "attempt_count": 7,
        "venue_session_count": 14,
        "trade_counts_by_venue": {},
        "bbo_counts_by_venue": {},
        "missingness_counts": {},
        "duplicate_counts": {},
        "locked_and_crossed_counts": {},
        "diagnostic_counts": {},
        "timestamp_diagnostics": {},
        "manifest_verification_results": {},
        "source_immutability_result": "VERIFIED_UNCHANGED",
        "snapshot_immutability_result": "VERIFIED_UNCHANGED",
        "normalized_output_immutability_result": "VERIFIED_UNCHANGED",
        "output_artifact_hashes": {},
        "per_attempt_validation_results": {"P01": "VALID"},
        "per_venue_session_validation_results": {},
        "errors": [],
        "warnings": [],
        "aggregate_disposition": disposition,
        "preliminary_analysis_eligibility": eligibility,
        "final_composite_status": final_composite,
    }
    path = dataset_root / "validation_report.json"
    path.write_text(json.dumps(report))
    return path


def _write_trade_parquet(path: Path, start: datetime, end: datetime, n: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    delta = (end - start) / max(n - 1, 1)
    timestamps = [start + delta * i for i in range(n)]
    df = pl.DataFrame(
        {
            "exchange_timestamp_utc": pl.Series(timestamps).cast(
                pl.Datetime(time_unit="us", time_zone="UTC")
            )
        }
    )
    df.write_parquet(path)


# ---------------------------------------------------------------------------
# Full analysis with partitioned paths
# ---------------------------------------------------------------------------


def test_analyze_preliminary_readiness_one_valid_attempt(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/date=2026-01-01/session=coinbase-1/part-00000.parquet"
    kr_rel = "trades/venue=kraken/date=2026-01-01/session=kraken-1/part-00000.parquet"

    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)  # 1860 s gap > 1800 s threshold

    _write_trade_parquet(dataset_root / cb_rel, start, end)
    _write_trade_parquet(dataset_root / kr_rel, start, end)

    manifest: dict[str, Any] = {
        "trade_files": [
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
            {"relative_path": kr_rel, "session_id": "kraken-1", "venue": "kraken"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {
                "campaign_attempt_id": "P01",
                "venue_session_ids": ["coinbase-1", "kraken-1"],
            }
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    report = analyze_preliminary_readiness(dataset_root, val_path)

    assert isinstance(report, PreliminaryReadinessReport)
    assert report.structural_readiness == "STRUCTURALLY_VALID"
    assert report.preliminary_analysis_readiness == "PRELIMINARY_READY"
    assert report.final_composite_readiness == "FINAL_COMPOSITE_UNSATISFIED"
    assert report.valid_attempt_count == 1
    assert report.total_attempt_count == 1
    assert len(report.paired_overlaps) == 1
    assert report.paired_overlaps[0].is_valid_for_preliminary_analysis is True
    assert report.paired_overlaps[0].overlap_duration_seconds >= 1800.0
    assert report.paired_overlaps[0].per_attempt_threshold_seconds == 1800.0
    assert "phase_3b_btc_usd.toml" in report.paired_overlaps[0].threshold_source

    # Two sessions diagnosed
    assert len(report.session_diagnostics) == 2
    assert report.session_diagnostics[0].trade_count == 2

    # Report persisted inside dataset_root/diagnostics
    diag_path = dataset_root / "diagnostics" / "preliminary_readiness_report.json"
    assert diag_path.exists()


def test_analyze_preliminary_readiness_zero_overlap(tmp_path: Path) -> None:
    """Non-overlapping sessions → overlap < threshold → PRELIMINARY_NOT_READY."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/session=coinbase-1/part-00000.parquet"
    kr_rel = "trades/venue=kraken/session=kraken-1/part-00000.parquet"

    cb_start = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
    cb_end = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    kr_start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    kr_end = datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC)

    _write_trade_parquet(dataset_root / cb_rel, cb_start, cb_end)
    _write_trade_parquet(dataset_root / kr_rel, kr_start, kr_end)

    manifest: dict[str, Any] = {
        "trade_files": [
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
            {"relative_path": kr_rel, "session_id": "kraken-1", "venue": "kraken"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {
                "campaign_attempt_id": "P01",
                "venue_session_ids": ["coinbase-1", "kraken-1"],
            }
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    report = analyze_preliminary_readiness(dataset_root, val_path)
    assert report.preliminary_analysis_readiness == "PRELIMINARY_NOT_READY"
    assert report.paired_overlaps[0].overlap_duration_seconds == 0.0
    assert report.paired_overlaps[0].is_valid_for_preliminary_analysis is False


def test_analyze_preliminary_readiness_optional_bbo_missing(tmp_path: Path) -> None:
    """Missing BBO file produces a warning but does not fail."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/session=coinbase-1/part-00000.parquet"
    kr_rel = "trades/venue=kraken/session=kraken-1/part-00000.parquet"

    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)
    _write_trade_parquet(dataset_root / cb_rel, start, end)
    _write_trade_parquet(dataset_root / kr_rel, start, end)

    # No BBO files in manifest — must not raise
    manifest: dict[str, Any] = {
        "trade_files": [
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
            {"relative_path": kr_rel, "session_id": "kraken-1", "venue": "kraken"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {
                "campaign_attempt_id": "P01",
                "venue_session_ids": ["coinbase-1", "kraken-1"],
            }
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    report = analyze_preliminary_readiness(dataset_root, val_path)
    assert report.preliminary_analysis_readiness == "PRELIMINARY_READY"
    assert all(s.bbo_count == 0 for s in report.session_diagnostics)


def test_analyze_preliminary_readiness_missing_trade_raises_error(tmp_path: Path) -> None:
    """Missing required trade file raises ResearchError (not silently skipped)."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/session=coinbase-1/part-00000.parquet"

    # Only create Coinbase file — Kraken is missing from trade_files mapping
    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)
    _write_trade_parquet(dataset_root / cb_rel, start, end)

    manifest: dict[str, Any] = {
        "trade_files": [
            # Kraken trade_files entry absent → no mapping for kraken-1
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {
                "campaign_attempt_id": "P01",
                "venue_session_ids": ["coinbase-1", "kraken-1"],
            }
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ResearchError, match="Missing trade file mapping"):
        analyze_preliminary_readiness(dataset_root, val_path)


def test_analyze_preliminary_readiness_all_attempts_covered(tmp_path: Path) -> None:
    """All seven attempt entries must appear in paired_overlaps."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    n_attempts = 7
    trade_files = []
    session_entries = []
    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)

    for i in range(1, n_attempts + 1):
        cb_sess = f"coinbase-{i}"
        kr_sess = f"kraken-{i}"
        cb_rel = f"trades/venue=coinbase/session={cb_sess}/part-00000.parquet"
        kr_rel = f"trades/venue=kraken/session={kr_sess}/part-00000.parquet"
        _write_trade_parquet(dataset_root / cb_rel, start, end)
        _write_trade_parquet(dataset_root / kr_rel, start, end)
        trade_files.append({"relative_path": cb_rel, "session_id": cb_sess, "venue": "coinbase"})
        trade_files.append({"relative_path": kr_rel, "session_id": kr_sess, "venue": "kraken"})
        session_entries.append(
            {
                "campaign_attempt_id": f"P{i:02d}",
                "venue_session_ids": [cb_sess, kr_sess],
            }
        )

    manifest: dict[str, Any] = {
        "trade_files": trade_files,
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": session_entries,
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    report = analyze_preliminary_readiness(dataset_root, val_path)
    assert report.total_attempt_count == n_attempts
    assert len(report.paired_overlaps) == n_attempts
    assert len(report.session_diagnostics) == n_attempts * 2


def test_analyze_preliminary_readiness_report_path_inside_dataset_root(
    tmp_path: Path,
) -> None:
    """Report must be written to dataset_root/diagnostics/preliminary_readiness_report.json."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(dataset_root)

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/session=coinbase-1/part-00000.parquet"
    kr_rel = "trades/venue=kraken/session=kraken-1/part-00000.parquet"
    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)
    _write_trade_parquet(dataset_root / cb_rel, start, end)
    _write_trade_parquet(dataset_root / kr_rel, start, end)

    manifest: dict[str, Any] = {
        "trade_files": [
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
            {"relative_path": kr_rel, "session_id": "kraken-1", "venue": "kraken"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {"campaign_attempt_id": "P01", "venue_session_ids": ["coinbase-1", "kraken-1"]}
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    analyze_preliminary_readiness(dataset_root, val_path)
    expected = dataset_root / "diagnostics" / "preliminary_readiness_report.json"
    assert expected.exists(), f"Report must be at {expected}"
    # Must NOT be written outside dataset_root
    parent_report = dataset_root.parent / "diagnostics" / "preliminary_readiness_report.json"
    assert not parent_report.exists()


# ---------------------------------------------------------------------------
# Ineligible dataset
# ---------------------------------------------------------------------------


def test_analyze_preliminary_readiness_ineligible(tmp_path: Path) -> None:
    dataset_root = tmp_path / "ds"
    dataset_root.mkdir()
    val_path = dataset_root / "val.json"
    val_path.write_text(
        json.dumps(
            {
                "preliminary_analysis_eligibility": "INELIGIBLE",
                "aggregate_disposition": "INVALID",
            }
        )
    )

    with pytest.raises(
        ResearchError,
        match="Dataset is not eligible for preliminary analysis",
    ):
        analyze_preliminary_readiness(dataset_root, val_path)


def test_analyze_preliminary_readiness_malformed_eligible_report(tmp_path: Path) -> None:
    """A report that says ELIGIBLE but is otherwise malformed must be rejected."""
    dataset_root = tmp_path / "ds"
    dataset_root.mkdir()
    val_path = dataset_root / "val.json"
    # Minimal report that passes the eligibility check but fails full Pydantic parse
    val_path.write_text(
        json.dumps(
            {
                "preliminary_analysis_eligibility": "ELIGIBLE",
                # Missing all required fields
            }
        )
    )

    with pytest.raises(ResearchError, match="Validation report is malformed"):
        analyze_preliminary_readiness(dataset_root, val_path)


def test_analyze_preliminary_readiness_missing_report_raises_error(tmp_path: Path) -> None:
    with pytest.raises(ResearchError, match="Validation report not found"):
        analyze_preliminary_readiness(tmp_path, tmp_path / "nonexistent.json")


def test_distinguish_preliminary_vs_final_composite_readiness(tmp_path: Path) -> None:
    """Structurally valid + at least one passing attempt = PRELIMINARY_READY.
    But final-composite is FINAL_COMPOSITE_UNSATISFIED with < 10 sessions."""
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    val_path = _make_validation_report(
        dataset_root, final_composite="FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
    )

    manifests = dataset_root / "manifests"
    manifests.mkdir()

    cb_rel = "trades/venue=coinbase/session=coinbase-1/part-00000.parquet"
    kr_rel = "trades/venue=kraken/session=kraken-1/part-00000.parquet"
    start = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)
    _write_trade_parquet(dataset_root / cb_rel, start, end)
    _write_trade_parquet(dataset_root / kr_rel, start, end)

    manifest: dict[str, Any] = {
        "trade_files": [
            {"relative_path": cb_rel, "session_id": "coinbase-1", "venue": "coinbase"},
            {"relative_path": kr_rel, "session_id": "kraken-1", "venue": "kraken"},
        ],
        "top_of_book_files": [],
        "per_session_normalization_manifest_files": [
            {"campaign_attempt_id": "P01", "venue_session_ids": ["coinbase-1", "kraken-1"]}
        ],
    }
    (manifests / "normalized_snapshot_manifest.json").write_text(json.dumps(manifest))

    report = analyze_preliminary_readiness(dataset_root, val_path)
    assert report.structural_readiness == "STRUCTURALLY_VALID"
    assert report.preliminary_analysis_readiness == "PRELIMINARY_READY"
    assert report.final_composite_readiness == "FINAL_COMPOSITE_UNSATISFIED"
    assert "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED" in str(report.readiness_reasons)
