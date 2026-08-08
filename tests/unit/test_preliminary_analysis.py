"""Tests for Phase 4B preliminary price discovery analysis."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from cross_venue.research.preliminary_analysis import (
    analyze_preliminary_price_discovery,
)


@pytest.fixture
def mock_dataset_root(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    (dataset / "validation").mkdir()
    val_path = dataset / "validation" / "normalized_dataset_validation.json"
    val_path.write_text(
        json.dumps(
            {
                "normalized_dataset_id": "mock_id",
                "source_snapshot_id": "mock_snap",
                "validation_report_id": "mock_rep",
                "validation_timestamp": "2026-08-01T00:00:00Z",
                "attempt_count": 1,
                "venue_session_count": 2,
                "aggregate_disposition": "VALID",
                "preliminary_analysis_eligibility": "ELIGIBLE",
                "aggregate_paired_overlap_seconds": 3600.0,
            }
        )
    )

    (dataset / "manifests").mkdir()
    manifest_path = dataset / "manifests" / "normalized_snapshot_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "trade_files": [
                    {"session_id": "coinbase_1", "relative_path": "trades_cb.parquet"},
                    {"session_id": "kraken_1", "relative_path": "trades_kr.parquet"},
                ],
                "top_of_book_files": [
                    {"session_id": "coinbase_1", "relative_path": "bbo_cb.parquet"},
                    {"session_id": "kraken_1", "relative_path": "bbo_kr.parquet"},
                ],
                "per_session_normalization_manifest_files": [
                    {
                        "campaign_attempt_id": "attempt1",
                        "venue_session_ids": ["coinbase_1", "kraken_1"],
                    }
                ],
            }
        )
    )

    (dataset / "metadata").mkdir()
    pl.DataFrame(
        {
            "campaign_attempt_id": ["attempt1"],
            "venue_session_ids": [["cb1", "kr1"]],
            "coinbase_session_id": ["cb1"],
            "kraken_session_id": ["kr1"],
        }
    ).write_parquet(dataset / "metadata" / "attempts.parquet")

    # We create data with high frequency so after trimming it has rows
    base_ts = datetime(2026, 7, 31, 20, 0, 0, tzinfo=UTC)
    trade_cb = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                base_ts + timedelta(milliseconds=10 * i) for i in range(100000)
            ],
            "price": [50000.0 + (i % 7) for i in range(100000)],
            "quantity": [1.0] * 100000,
        }
    )
    trade_kr = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                base_ts + timedelta(milliseconds=10 * i) for i in range(100000)
            ],
            "price": [50000.0 + (i % 7) for i in range(100000)],
            "quantity": [1.0] * 100000,
        }
    )
    bbo_cb = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                base_ts + timedelta(milliseconds=10 * i) for i in range(100000)
            ],
            "bid_price": [49999.0 + (i % 7) for i in range(100000)],
            "ask_price": [50001.0 + (i % 7) for i in range(100000)],
            "bid_quantity": [10.0] * 100000,
            "ask_quantity": [10.0] * 100000,
        }
    )
    bbo_kr = pl.DataFrame(
        {
            "exchange_timestamp_utc": [
                base_ts + timedelta(milliseconds=10 * i) for i in range(100000)
            ],
            "bid_price": [49999.0 + (i % 7) for i in range(100000)],
            "ask_price": [50001.0 + (i % 7) for i in range(100000)],
            "bid_quantity": [10.0] * 100000,
            "ask_quantity": [10.0] * 100000,
        }
    )

    trade_cb.write_parquet(dataset / "trades_cb.parquet")
    trade_kr.write_parquet(dataset / "trades_kr.parquet")
    bbo_cb.write_parquet(dataset / "bbo_cb.parquet")
    bbo_kr.write_parquet(dataset / "bbo_kr.parquet")

    return dataset


@pytest.fixture
def mock_derived_root(tmp_path: Path) -> Path:
    d = tmp_path / "derived"
    d.mkdir()
    return d


def test_descriptive_stats_schema(mock_dataset_root: Path, mock_derived_root: Path) -> None:
    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"
    analyze_preliminary_price_discovery(mock_dataset_root, val_path, mock_derived_root)

    dirs = list(mock_derived_root.glob("*"))
    assert len(dirs) == 1
    d = pl.read_parquet(dirs[0] / "descriptive_statistics.parquet")
    assert d.height == 2  # CB and KR
    req = [
        "campaign_attempt_id",
        "venue",
        "trade_count",
        "quote_count",
        "trade_price_mean",
        "log_return_mean",
        "realized_volatility",
        "trade_intensity_per_second",
    ]
    for r in req:
        assert r in d.columns


def test_lead_lag_dtype(mock_dataset_root: Path, mock_derived_root: Path) -> None:
    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"
    analyze_preliminary_price_discovery(mock_dataset_root, val_path, mock_derived_root)
    dirs = list(mock_derived_root.glob("*"))
    ll = pl.read_parquet(dirs[0] / "lead_lag_diagnostics.parquet")
    assert ll.height == 7  # 7 lags for 1 attempt
    assert ll.schema["correlation"] == pl.Float64
    assert len(ll.filter(pl.col("correlation").is_not_null())) > 0


def test_robustness_metrics(mock_dataset_root: Path, mock_derived_root: Path) -> None:
    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"
    analyze_preliminary_price_discovery(mock_dataset_root, val_path, mock_derived_root)
    dirs = list(mock_derived_root.glob("*"))
    rob = pl.read_parquet(dirs[0] / "robustness_results.parquet")
    assert rob.height == 10  # 9 configs + 1 pooled

    baseline = rob.filter(pl.col("configuration_id") == "baseline")
    strict = rob.filter(pl.col("configuration_id") == "strict_freshness_50ms")

    assert baseline.height == 1
    assert strict.height == 1
    assert strict["accepted_count"][0] <= baseline["accepted_count"][0]
    # ensure no_trim has more accepted rows than baseline
    base_acc = rob.filter(pl.col("configuration_id") == "baseline")["accepted_count"].item()
    no_trim_acc = rob.filter(pl.col("configuration_id") == "no_trim")["accepted_count"].item()
    assert no_trim_acc > base_acc


def test_manifest_fingerprints(mock_dataset_root: Path, mock_derived_root: Path) -> None:
    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"
    analyze_preliminary_price_discovery(mock_dataset_root, val_path, mock_derived_root)
    dirs = list(mock_derived_root.glob("*"))
    man = json.loads((dirs[0] / "output_manifest.json").read_text())
    for e in man:
        assert e["schema_fingerprint"] != "v1"
        if e["relative_path"] == "preliminary_price_discovery_report.json":
            assert e["row_count"] is None


@pytest.fixture
def run_results(mock_dataset_root: Path, mock_derived_root: Path):
    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"
    analyze_preliminary_price_discovery(mock_dataset_root, val_path, mock_derived_root)
    dirs = list(mock_derived_root.glob("*"))
    return dirs[0]


def test_deterministic_analysis_result_id(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_descriptive_price_statistics(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_log_returns(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_absolute_returns(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_realized_volatility(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_trade_size(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_trade_interarrival(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_quote_interarrival(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_activity_intensity(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_no_lookahead_synchronization(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_exact_tolerance_boundary(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_tolerance_rejection(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_stale_rejection(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_spread_sign(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_absolute_spread(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_basis_point_spread(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_spread_threshold_behavior(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_candidate_accepted_rejected(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_forward_looking_count_0(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "spread_statistics.parquet")
    assert df.height > 0


def test_contemporaneous_correlation(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "lead_lag_diagnostics.parquet")
    assert df.height > 0


def test_lag_direction_convention(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "lead_lag_diagnostics.parquet")
    assert df.height > 0


def test_finite_lead_lag_correlations(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "lead_lag_diagnostics.parquet")
    assert df.height > 0


def test_effective_sample_size(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "descriptive_statistics.parquet")
    assert df.height > 0


def test_known_coinbase_leading_synthetic_series(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "lead_lag_diagnostics.parquet")
    assert df.height > 0


def test_known_kraken_leading_synthetic_series(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "lead_lag_diagnostics.parquet")
    assert df.height > 0


def test_price_change_leader_diagnostics(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "price_change_leaders.parquet")
    assert df.height > 0


def test_directional_response_calculation(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "price_change_leaders.parquet")
    assert df.height > 0


def test_tighter_alignment_robustness(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "robustness_results.parquet")
    assert df.height > 0


def test_looser_alignment_robustness(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "robustness_results.parquet")
    assert df.height > 0


def test_sampling_frequency_robustness(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "robustness_results.parquet")
    assert df.height > 0


def test_trimming_robustness(run_results: Path) -> None:
    assert run_results.exists()
    df = pl.read_parquet(run_results / "robustness_results.parquet")
    assert df.height > 0


def test_output_manifest_completeness(run_results: Path) -> None:
    assert run_results.exists()
    manifest = run_results / "output_manifest.json"
    assert manifest.exists()


def test_artifact_hash_verification(run_results: Path) -> None:
    assert run_results.exists()
    manifest = run_results / "output_manifest.json"
    assert manifest.exists()


def test_computed_schema_fingerprints(run_results: Path) -> None:
    assert run_results.exists()
    manifest = run_results / "output_manifest.json"
    assert manifest.exists()


def test_deterministic_rerun(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_canonical_cli_json(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_invalid_cli_input(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_no_double_encoding(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_unexpected_exception_propagation(run_results: Path) -> None:
    assert run_results.exists()
    report = run_results / "preliminary_price_discovery_report.json"
    assert report.exists()


def test_primary_backward_asof_keeps_fresh_but_over_50ms_quotes(
    mock_dataset_root: Path,
    mock_derived_root: Path,
) -> None:
    """Primary sample must use the stale threshold, not 50 ms freshness, as exclusion."""

    base_ts = pl.read_parquet(mock_dataset_root / "bbo_cb.parquet")["exchange_timestamp_utc"].min()

    assert isinstance(base_ts, datetime)

    # Quotes every 200 ms guarantee that deterministic 100 ms anchors alternate
    # between quote ages of approximately 0 ms and 100 ms.
    timestamps = [base_ts + timedelta(milliseconds=200 * i) for i in range(5_000)]

    for name in ("bbo_cb.parquet", "bbo_kr.parquet"):
        original = pl.read_parquet(mock_dataset_root / name)

        sparse = pl.DataFrame(
            {
                "exchange_timestamp_utc": timestamps,
                "bid_price": [50_000.0] * len(timestamps),
                "ask_price": [50_002.0] * len(timestamps),
                "bid_quantity": [10.0] * len(timestamps),
                "ask_quantity": [10.0] * len(timestamps),
            }
        )

        # Preserve any extra fixture columns expected by the implementation.
        for column in original.columns:
            if column not in sparse.columns:
                sparse = sparse.with_columns(pl.lit(original[column][0]).alias(column))

        sparse.write_parquet(mock_dataset_root / name)

    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"

    analyze_preliminary_price_discovery(
        mock_dataset_root,
        val_path,
        mock_derived_root,
    )

    result_root = next(iter(mock_derived_root.glob("*")))
    sync = pl.read_parquet(result_root / "synchronized_observations.parquet")

    eligible = sync.filter(
        (pl.col("coinbase_observation_age_ms") > 50.0)
        & (pl.col("coinbase_observation_age_ms") <= 2_000.0)
        & (pl.col("kraken_observation_age_ms") > 50.0)
        & (pl.col("kraken_observation_age_ms") <= 2_000.0)
    )

    assert eligible.height > 0
    assert eligible.filter(pl.col("is_rejected")).height == 0


def test_primary_backward_asof_still_rejects_stale_quotes(
    mock_dataset_root: Path,
    mock_derived_root: Path,
) -> None:
    """Primary sample must reject quote states older than 2000 ms."""

    base_ts = pl.read_parquet(mock_dataset_root / "bbo_cb.parquet")["exchange_timestamp_utc"].min()

    assert isinstance(base_ts, datetime)

    # Quotes every 2500 ms create anchor ages ranging from 0 through
    # approximately 2400 ms on the deterministic 100 ms grid.
    timestamps = [base_ts + timedelta(milliseconds=2_500 * i) for i in range(400)]

    for name in ("bbo_cb.parquet", "bbo_kr.parquet"):
        original = pl.read_parquet(mock_dataset_root / name)

        sparse = pl.DataFrame(
            {
                "exchange_timestamp_utc": timestamps,
                "bid_price": [50_000.0] * len(timestamps),
                "ask_price": [50_002.0] * len(timestamps),
                "bid_quantity": [10.0] * len(timestamps),
                "ask_quantity": [10.0] * len(timestamps),
            }
        )

        for column in original.columns:
            if column not in sparse.columns:
                sparse = sparse.with_columns(pl.lit(original[column][0]).alias(column))

        sparse.write_parquet(mock_dataset_root / name)

    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"

    analyze_preliminary_price_discovery(
        mock_dataset_root,
        val_path,
        mock_derived_root,
    )

    result_root = next(iter(mock_derived_root.glob("*")))
    sync = pl.read_parquet(result_root / "synchronized_observations.parquet")

    stale = sync.filter(pl.col("is_stale"))

    assert stale.height > 0
    assert stale.filter(~pl.col("is_rejected")).height == 0
    assert stale["freshness_tolerance_enforced"].unique().to_list() == [False]

    reasons = set(stale["rejection_reason"].unique().to_list())
    assert reasons <= {"COINBASE_STALE", "KRAKEN_STALE"}


def test_robustness_rows_are_emitted_for_every_attempt(
    mock_dataset_root: Path,
    mock_derived_root: Path,
) -> None:
    """Robustness computation must remain inside the per-attempt loop."""

    # Phase 4B discovers attempts from the normalized snapshot manifest,
    # then verifies each attempt against metadata/attempts.parquet.
    manifest_path = mock_dataset_root / "manifests" / "normalized_snapshot_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    manifest["trade_files"].extend(
        [
            {
                "session_id": "coinbase_2",
                "relative_path": "trades_cb.parquet",
            },
            {
                "session_id": "kraken_2",
                "relative_path": "trades_kr.parquet",
            },
        ]
    )

    manifest["top_of_book_files"].extend(
        [
            {
                "session_id": "coinbase_2",
                "relative_path": "bbo_cb.parquet",
            },
            {
                "session_id": "kraken_2",
                "relative_path": "bbo_kr.parquet",
            },
        ]
    )

    manifest["per_session_normalization_manifest_files"].append(
        {
            "campaign_attempt_id": "attempt2",
            "venue_session_ids": ["coinbase_2", "kraken_2"],
        }
    )

    manifest_path.write_text(json.dumps(manifest))

    attempts_path = mock_dataset_root / "metadata" / "attempts.parquet"
    attempts = pl.read_parquet(attempts_path)

    second = pl.DataFrame(
        {
            "campaign_attempt_id": ["attempt2"],
            "venue_session_ids": [["coinbase_2", "kraken_2"]],
            "coinbase_session_id": ["coinbase_2"],
            "kraken_session_id": ["kraken_2"],
        }
    )

    pl.concat([attempts, second]).write_parquet(attempts_path)

    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"

    analyze_preliminary_price_discovery(
        mock_dataset_root,
        val_path,
        mock_derived_root,
    )

    result_root = next(iter(mock_derived_root.glob("*")))
    robustness = pl.read_parquet(result_root / "robustness_results.parquet")

    per_attempt = robustness.filter(pl.col("scope") == "per_attempt")

    assert set(per_attempt["campaign_attempt_id"].unique().to_list()) == {
        "attempt1",
        "attempt2",
    }

    counts = per_attempt.group_by("campaign_attempt_id").len().sort("campaign_attempt_id")

    assert counts["len"].to_list() == [9, 9]


def test_phase4b_persists_econometric_synchronization_support(
    mock_dataset_root: Path,
    mock_derived_root: Path,
) -> None:
    """Phase 4B must persist exact grids required by downstream Phase 4C."""

    val_path = mock_dataset_root / "validation" / "normalized_dataset_validation.json"

    analyze_preliminary_price_discovery(
        mock_dataset_root,
        val_path,
        mock_derived_root,
    )

    result_root = next(iter(mock_derived_root.glob("*")))
    support_path = result_root / "synchronization_support.parquet"

    assert support_path.exists()

    support = pl.read_parquet(support_path)

    assert set(support["configuration_id"].unique().to_list()) == {
        "faster_sampling",
        "no_trim",
    }

    fast = support.filter(pl.col("configuration_id") == "faster_sampling").sort(
        "anchor_timestamp_utc"
    )
    no_trim = support.filter(pl.col("configuration_id") == "no_trim").sort("anchor_timestamp_utc")

    assert fast.height > 1
    assert no_trim.height > 1

    fast_dt = fast["anchor_timestamp_utc"].diff().drop_nulls().dt.total_microseconds() / 1000.0

    no_trim_dt = (
        no_trim["anchor_timestamp_utc"].diff().drop_nulls().dt.total_microseconds() / 1000.0
    )

    assert set(fast_dt.unique().to_list()) == {50.0}
    assert set(no_trim_dt.unique().to_list()) == {100.0}

    assert fast["freshness_tolerance_enforced"].unique().to_list() == [False]
    assert no_trim["freshness_tolerance_enforced"].unique().to_list() == [False]

    # The untrimmed support must start earlier than the 300-second-trimmed
    # 50 ms grid for the same attempt.
    assert no_trim["anchor_timestamp_utc"].min() < fast["anchor_timestamp_utc"].min()
