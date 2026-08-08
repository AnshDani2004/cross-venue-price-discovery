"""Phase 4B preliminary price discovery analysis."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from cross_venue.normalization.validation import NormalizedDatasetValidationResult
from cross_venue.research.exceptions import ResearchError


class PreliminaryAnalysisConfig(BaseModel):
    """Configuration for Phase 4B preliminary analysis."""

    sampling_interval_ms: int = 100
    alignment_tolerance_ms: int = 50
    stale_threshold_ms: int = 2000
    return_horizon_ms: int = 100
    opening_trim_seconds: int = 300
    closing_trim_seconds: int = 300
    lag_grid: list[int] = [-500, -250, -100, 0, 100, 250, 500]
    spread_threshold_bps: float = 5.0
    price_measure: str = "midprice"
    return_source: str = "midprice"
    sampling_method: str = "backward_as_of"
    anchor_clock: str = "deterministic_utc_grid"
    spread_sign_convention: str = "coinbase_minus_kraken"
    lag_sign_convention: str = "positive_lag_means_kraken_leads_coinbase"
    pooling_method: str = "pooled_and_per_attempt"
    session_weighting: str = "equal"


class DescriptiveStats(BaseModel):
    count: int
    mean: float | None
    median: float | None
    std_dev: float | None
    min: float | None
    max: float | None
    quantiles_pct: dict[str, float | None]


class SpreadStats(BaseModel):
    count: int
    mean: float | None
    median: float | None
    std_dev: float | None
    min: float | None
    max: float | None
    quantiles_pct: dict[str, float | None]
    positive_count: int
    negative_count: int
    zero_count: int
    threshold_breach_count: int


class LeadLagDiagnostic(BaseModel):
    campaign_attempt_id: str
    sampling_interval_ms: int
    return_horizon_ms: int
    lag: int
    direction: str
    correlation: float | None
    effective_sample_count: int
    status: str


class AttemptPriceStats(BaseModel):
    campaign_attempt_id: str
    venue: str
    trade_price: DescriptiveStats
    log_returns: DescriptiveStats
    absolute_log_returns: DescriptiveStats
    realized_volatility: DescriptiveStats
    trade_size: DescriptiveStats
    trade_interarrival_ms: DescriptiveStats
    quote_interarrival_ms: DescriptiveStats
    trade_intensity: DescriptiveStats
    quote_intensity: DescriptiveStats


class AttemptCrossVenueStats(BaseModel):
    campaign_attempt_id: str
    sampling_frequency_ms: int
    stale_threshold_ms: int
    price_measure: str
    signed_spread: SpreadStats
    absolute_spread: SpreadStats
    signed_bps_spread: SpreadStats
    absolute_bps_spread: SpreadStats
    stale_or_rejected_count: int
    leader_frequency_coinbase: float | None
    directional_response_consistency: float | None


class PreliminaryPriceDiscoveryReport(BaseModel):
    dataset_id: str
    snapshot_id: str
    validation_report_id: str
    validation_report_hash: str
    runtime_commit: str
    dirty_working_tree: bool
    analysis_configuration: PreliminaryAnalysisConfig
    output_schema_version: str = "4b-preliminary-analysis.2"
    analysis_result_id: str
    manifest_hash: str
    attempt_count: int
    venue_session_count: int
    calendar_dates: list[str]
    time_buckets: list[str]
    authoritative_paired_overlap_seconds: float
    untrimmed_empirical_trade_overlap_seconds: float
    per_attempt_price_stats: list[AttemptPriceStats] = Field(default_factory=list)
    per_attempt_cross_venue_stats: list[AttemptCrossVenueStats] = Field(default_factory=list)
    lead_lag_diagnostics: list[LeadLagDiagnostic] = Field(default_factory=list)
    output_inventory: list[str]
    output_hashes: dict[str, str]


def _extract_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        if hasattr(val, "item"):
            val = val.item()
        return float(val)
    except (ValueError, TypeError):
        return None


def _compute_descriptive(s: pl.Series) -> DescriptiveStats:
    s = s.drop_nulls()
    if s.len() == 0:
        return DescriptiveStats(
            count=0,
            mean=None,
            median=None,
            std_dev=None,
            min=None,
            max=None,
            quantiles_pct={"25": None, "75": None},
        )
    return DescriptiveStats(
        count=s.len(),
        mean=_extract_float(s.mean()),
        median=_extract_float(s.median()),
        std_dev=_extract_float(s.std()),
        min=_extract_float(s.min()),
        max=_extract_float(s.max()),
        quantiles_pct={
            "25": _extract_float(s.quantile(0.25)),
            "75": _extract_float(s.quantile(0.75)),
        },
    )


def _compute_spread(s: pl.Series, threshold: float = 0.0) -> SpreadStats:
    s = s.drop_nulls()
    desc = _compute_descriptive(s)
    if s.len() == 0:
        return SpreadStats(
            count=0,
            mean=None,
            median=None,
            std_dev=None,
            min=None,
            max=None,
            quantiles_pct={"25": None, "75": None},
            positive_count=0,
            negative_count=0,
            zero_count=0,
            threshold_breach_count=0,
        )
    return SpreadStats(
        count=desc.count,
        mean=desc.mean,
        median=desc.median,
        std_dev=desc.std_dev,
        min=desc.min,
        max=desc.max,
        quantiles_pct=desc.quantiles_pct,
        positive_count=s.filter(s > 0).len(),
        negative_count=s.filter(s < 0).len(),
        zero_count=s.filter(s == 0).len(),
        threshold_breach_count=s.filter(s.abs() > threshold).len(),
    )


def compute_desc_row(
    attempt_id: str,
    venue: str,
    trades: pl.DataFrame,
    bbo: pl.DataFrame,
    start: Any,
    end: Any,
    config: PreliminaryAnalysisConfig,
) -> pl.DataFrame:
    prices = trades["price"].drop_nulls()
    sizes = trades["quantity"].drop_nulls()
    log_ret = prices.log().diff().drop_nulls()
    abs_log_ret = log_ret.abs()
    rv = float((log_ret**2).sum()) ** 0.5

    trade_ts = trades.filter(pl.col("exchange_timestamp_utc").is_not_null())[
        "exchange_timestamp_utc"
    ]
    bbo_ts = bbo.filter(pl.col("exchange_timestamp_utc").is_not_null())["exchange_timestamp_utc"]

    trade_ia = trade_ts.diff().dt.total_microseconds() / 1000.0
    bbo_ia = bbo_ts.diff().dt.total_microseconds() / 1000.0

    t_max = trade_ts.max()
    t_min = trade_ts.min()
    duration_s = 0.0
    if trade_ts.len() > 1 and isinstance(t_max, datetime) and isinstance(t_min, datetime):
        duration_s = (t_max - t_min).total_seconds()

    trade_int = trade_ts.len() / duration_s if duration_s > 0 else 0.0

    b_max = bbo_ts.max()
    b_min = bbo_ts.min()
    duration_s2 = 0.0
    if bbo_ts.len() > 1 and isinstance(b_max, datetime) and isinstance(b_min, datetime):
        duration_s2 = (b_max - b_min).total_seconds()

    bbo_int = bbo_ts.len() / duration_s2 if duration_s2 > 0 else 0.0

    untrimmed = 0.0
    trimmed_usable = 0.0
    if isinstance(start, datetime) and isinstance(end, datetime):
        untrimmed = (end - start).total_seconds()
        t_start = start + timedelta(seconds=config.opening_trim_seconds)
        t_end = end - timedelta(seconds=config.closing_trim_seconds)
        if t_end > t_start:
            trimmed_usable = (t_end - t_start).total_seconds()

    return pl.DataFrame(
        {
            "campaign_attempt_id": [attempt_id],
            "venue": [venue],
            "trade_count": [trades.height],
            "quote_count": [bbo.height],
            "trade_price_count": [prices.len()],
            "trade_price_mean": [_extract_float(prices.mean())],
            "trade_price_median": [_extract_float(prices.median())],
            "trade_price_std": [_extract_float(prices.std())],
            "trade_price_min": [_extract_float(prices.min())],
            "trade_price_max": [_extract_float(prices.max())],
            "trade_price_p25": [_extract_float(prices.quantile(0.25))],
            "trade_price_p75": [_extract_float(prices.quantile(0.75))],
            "trade_price_p95": [_extract_float(prices.quantile(0.95))],
            "log_return_count": [log_ret.len()],
            "log_return_mean": [_extract_float(log_ret.mean())],
            "log_return_std": [_extract_float(log_ret.std())],
            "log_return_p25": [_extract_float(log_ret.quantile(0.25))],
            "log_return_p50": [_extract_float(log_ret.quantile(0.50))],
            "log_return_p75": [_extract_float(log_ret.quantile(0.75))],
            "absolute_return_mean": [_extract_float(abs_log_ret.mean())],
            "absolute_return_median": [_extract_float(abs_log_ret.median())],
            "absolute_return_p75": [_extract_float(abs_log_ret.quantile(0.75))],
            "absolute_return_p95": [_extract_float(abs_log_ret.quantile(0.95))],
            "realized_volatility": [rv],
            "realized_volatility_definition": ["sqrt(sum(log_return^2))"],
            "trade_size_count": [sizes.len()],
            "trade_size_mean": [_extract_float(sizes.mean())],
            "trade_size_median": [_extract_float(sizes.median())],
            "trade_size_std": [_extract_float(sizes.std())],
            "trade_size_p25": [_extract_float(sizes.quantile(0.25))],
            "trade_size_p75": [_extract_float(sizes.quantile(0.75))],
            "trade_size_p95": [_extract_float(sizes.quantile(0.95))],
            "trade_interarrival_count": [trade_ia.drop_nulls().len()],
            "trade_interarrival_mean_ms": [_extract_float(trade_ia.mean())],
            "trade_interarrival_median_ms": [_extract_float(trade_ia.median())],
            "trade_interarrival_p95_ms": [_extract_float(trade_ia.quantile(0.95))],
            "quote_interarrival_count": [bbo_ia.drop_nulls().len()],
            "quote_interarrival_mean_ms": [_extract_float(bbo_ia.mean())],
            "quote_interarrival_median_ms": [_extract_float(bbo_ia.median())],
            "quote_interarrival_p95_ms": [_extract_float(bbo_ia.quantile(0.95))],
            "trade_intensity_per_second": [trade_int],
            "quote_intensity_per_second": [bbo_int],
            "empirical_overlap_start": [start],
            "empirical_overlap_end": [end],
            "untrimmed_overlap_seconds": [untrimmed],
            "trimmed_start": [t_start],
            "trimmed_end": [t_end],
            "trimmed_usable_seconds": [trimmed_usable],
        }
    )


def analyze_preliminary_price_discovery(
    dataset_root: Path,
    validation_report_path: Path,
    derived_root: Path,
    config: PreliminaryAnalysisConfig | None = None,
) -> PreliminaryPriceDiscoveryReport:
    if config is None:
        config = PreliminaryAnalysisConfig()

    if not validation_report_path.exists():
        raise ResearchError(f"Validation report not found: {validation_report_path}")

    raw_report_text = validation_report_path.read_text(encoding="utf-8")
    raw_report = json.loads(raw_report_text)
    val_report_hash = hashlib.sha256(raw_report_text.encode()).hexdigest()

    try:
        validation_result = NormalizedDatasetValidationResult.model_validate(raw_report)
    except Exception as exc:
        raise ResearchError(f"Validation report is malformed: {exc}") from exc

    if validation_result.aggregate_disposition != "VALID":
        raise ResearchError("Dataset is not structurally valid.")

    if validation_result.preliminary_analysis_eligibility != "ELIGIBLE":
        raise ResearchError("Dataset is not eligible for preliminary analysis.")

    manifest_path = dataset_root / "manifests" / "normalized_snapshot_manifest.json"
    if not manifest_path.exists():
        raise ResearchError("Normalized snapshot manifest missing.")

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_hash = hashlib.sha256(manifest_text.encode()).hexdigest()
    manifest = json.loads(manifest_text)

    trade_path_by_session: dict[str, Path] = {
        entry["session_id"]: dataset_root / entry["relative_path"]
        for entry in manifest.get("trade_files", [])
        if entry.get("session_id")
    }
    bbo_path_by_session: dict[str, Path] = {
        entry["session_id"]: dataset_root / entry["relative_path"]
        for entry in manifest.get("top_of_book_files", [])
        if entry.get("session_id")
    }

    attempts_parquet_path = dataset_root / "metadata" / "attempts.parquet"
    if not attempts_parquet_path.exists():
        raise ResearchError("metadata/attempts.parquet not found.")
    attempts_df = pl.read_parquet(attempts_parquet_path)

    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet"]) != 0
    except Exception:
        commit = "unknown"
        dirty = True

    analysis_result_id = hashlib.sha256(f"{val_report_hash}-{commit}".encode()).hexdigest()[:16]
    out_dir = derived_root / analysis_result_id
    out_dir.mkdir(parents=True, exist_ok=True)

    per_attempt_price = []
    per_attempt_cv: list[AttemptCrossVenueStats] = []

    output_files = []
    total_empirical_overlap = 0.0

    all_cv_dfs = []
    all_desc = []
    all_ll = []
    all_lead = []
    all_rob = []
    all_spread_rows = []

    all_dates = set()

    for entry in manifest.get("per_session_normalization_manifest_files", []):
        attempt_id = entry.get("campaign_attempt_id")
        if not attempt_id:
            continue

        sessions = entry.get("venue_session_ids", [])
        cb_sess = next((s for s in sessions if "coinbase" in s.lower()), None)
        kr_sess = next((s for s in sessions if "kraken" in s.lower()), None)

        if not cb_sess or not kr_sess:
            raise ResearchError(f"Attempt {attempt_id} has ambiguous or missing CB/KR sessions.")

        cb_trade_path = trade_path_by_session.get(cb_sess)
        kr_trade_path = trade_path_by_session.get(kr_sess)
        cb_bbo_path = bbo_path_by_session.get(cb_sess)
        kr_bbo_path = bbo_path_by_session.get(kr_sess)

        if not all((cb_trade_path, kr_trade_path, cb_bbo_path, kr_bbo_path)):
            continue

        attempt_meta = attempts_df.filter(pl.col("campaign_attempt_id") == attempt_id)
        if attempt_meta.height == 0:
            continue

        cb_trades = pl.read_parquet(str(cb_trade_path)).with_columns(
            pl.col("exchange_timestamp_utc").dt.cast_time_unit("ns").dt.replace_time_zone("UTC")
        )
        kr_trades = pl.read_parquet(str(kr_trade_path)).with_columns(
            pl.col("exchange_timestamp_utc").dt.cast_time_unit("ns").dt.replace_time_zone("UTC")
        )
        cb_bbo = pl.read_parquet(str(cb_bbo_path)).with_columns(
            pl.col("exchange_timestamp_utc").dt.cast_time_unit("ns").dt.replace_time_zone("UTC")
        )
        kr_bbo = pl.read_parquet(str(kr_bbo_path)).with_columns(
            pl.col("exchange_timestamp_utc").dt.cast_time_unit("ns").dt.replace_time_zone("UTC")
        )

        def get_bounds(df: pl.DataFrame) -> tuple[datetime | None, datetime | None]:
            v = df.filter(pl.col("exchange_timestamp_utc").is_not_null())
            if v.height == 0:
                return None, None
            c_min = v.select(pl.col("exchange_timestamp_utc").min()).item()
            c_max = v.select(pl.col("exchange_timestamp_utc").max()).item()
            if isinstance(c_min, datetime) and isinstance(c_max, datetime):
                return c_min, c_max
            return None, None

        cb_min, cb_max = get_bounds(cb_trades)
        kr_min, kr_max = get_bounds(kr_trades)

        if cb_min is not None and kr_min is not None and cb_max is not None and kr_max is not None:
            start = max(cb_min, kr_min)
            end = min(cb_max, kr_max)
            if end > start:
                delta = end - start
                total_empirical_overlap += delta.total_seconds()
                all_dates.add(start.strftime("%Y-%m-%d"))
        else:
            start = None
            end = None

        for venue, trades, bbo in [("coinbase", cb_trades, cb_bbo), ("kraken", kr_trades, kr_bbo)]:
            if trades.height == 0 or bbo.height == 0:
                continue
            all_desc.append(compute_desc_row(attempt_id, venue, trades, bbo, start, end, config))

            # Old price stats for the JSON report
            prices = trades["price"].drop_nulls()
            sizes = trades["quantity"].drop_nulls()
            log_ret = prices.log().diff().drop_nulls()
            abs_log_ret = log_ret.abs()
            rv = float(float((log_ret**2).sum()) ** 0.5)
            rv_series = pl.Series([rv])
            trade_ts = trades.filter(pl.col("exchange_timestamp_utc").is_not_null())[
                "exchange_timestamp_utc"
            ]
            bbo_ts = bbo.filter(pl.col("exchange_timestamp_utc").is_not_null())[
                "exchange_timestamp_utc"
            ]
            trade_ia = trade_ts.diff().dt.total_microseconds() / 1000.0
            bbo_ia = bbo_ts.diff().dt.total_microseconds() / 1000.0
            t_max = trade_ts.max()
            t_min = trade_ts.min()
            duration_s = 0.0
            if trade_ts.len() > 1 and isinstance(t_max, datetime) and isinstance(t_min, datetime):
                duration_s = (t_max - t_min).total_seconds()

            trade_int = (
                pl.Series([trade_ts.len() / duration_s]) if duration_s > 0 else pl.Series([0.0])
            )

            b_max = bbo_ts.max()
            b_min = bbo_ts.min()
            duration_s2 = 0.0
            if bbo_ts.len() > 1 and isinstance(b_max, datetime) and isinstance(b_min, datetime):
                duration_s2 = (b_max - b_min).total_seconds()

            bbo_int = (
                pl.Series([bbo_ts.len() / duration_s2]) if duration_s2 > 0 else pl.Series([0.0])
            )

            pstat = AttemptPriceStats(
                campaign_attempt_id=attempt_id,
                venue=venue,
                trade_price=_compute_descriptive(prices),
                log_returns=_compute_descriptive(log_ret),
                absolute_log_returns=_compute_descriptive(abs_log_ret),
                realized_volatility=_compute_descriptive(rv_series),
                trade_size=_compute_descriptive(sizes),
                trade_interarrival_ms=_compute_descriptive(trade_ia),
                quote_interarrival_ms=_compute_descriptive(bbo_ia),
                trade_intensity=_compute_descriptive(trade_int),
                quote_intensity=_compute_descriptive(bbo_int),
            )
            per_attempt_price.append(pstat)

        cb = cb_bbo.filter(pl.col("exchange_timestamp_utc").is_not_null()).sort(
            "exchange_timestamp_utc"
        )
        kr = kr_bbo.filter(pl.col("exchange_timestamp_utc").is_not_null()).sort(
            "exchange_timestamp_utc"
        )

        if cb.height > 0 and kr.height > 0 and start and end:
            cb = cb.rename(
                {"exchange_timestamp_utc": "cb_ts", "bid_price": "cb_bid", "ask_price": "cb_ask"}
            )
            kr = kr.rename(
                {"exchange_timestamp_utc": "kr_ts", "bid_price": "kr_bid", "ask_price": "kr_ask"}
            )
            cb = cb.with_columns(((pl.col("cb_bid") + pl.col("cb_ask")) / 2.0).alias("cb_mid"))
            kr = kr.with_columns(((pl.col("kr_bid") + pl.col("kr_ask")) / 2.0).alias("kr_mid"))

            def perform_sync(
                r_freq: int,
                r_tol: int,
                r_stale: int,
                r_trim: int,
                start_dt: datetime,
                end_dt: datetime,
                cb_df: pl.DataFrame,
                kr_df: pl.DataFrame,
                aid: str,
                cb_s: str,
                kr_s: str,
                enforce_freshness_tolerance: bool = True,
            ) -> pl.DataFrame | None:
                anchor_min = start_dt + timedelta(seconds=r_trim)
                anchor_max = end_dt - timedelta(seconds=r_trim)
                if anchor_max <= anchor_min:
                    return None

                grid = pl.DataFrame(
                    {
                        "anchor_timestamp_utc": pl.datetime_range(
                            anchor_min, anchor_max, interval=f"{r_freq}ms", eager=True
                        )
                    }
                )
                grid = grid.with_columns(pl.col("anchor_timestamp_utc").dt.cast_time_unit("ns"))

                g1 = grid.join_asof(
                    cb_df, left_on="anchor_timestamp_utc", right_on="cb_ts", strategy="backward"
                )
                synced = g1.join_asof(
                    kr_df, left_on="anchor_timestamp_utc", right_on="kr_ts", strategy="backward"
                )

                synced = synced.with_columns(
                    [
                        (
                            (
                                pl.col("anchor_timestamp_utc") - pl.col("cb_ts")
                            ).dt.total_microseconds()
                            / 1000.0
                        ).alias("coinbase_observation_age_ms"),
                        (
                            (
                                pl.col("anchor_timestamp_utc") - pl.col("kr_ts")
                            ).dt.total_microseconds()
                            / 1000.0
                        ).alias("kraken_observation_age_ms"),
                    ]
                ).rename(
                    {
                        "cb_ts": "coinbase_timestamp_utc",
                        "kr_ts": "kraken_timestamp_utc",
                    }
                )

                synced = synced.with_columns(
                    [
                        (pl.col("cb_mid") - pl.col("kr_mid")).alias("signed_spread"),
                        (pl.col("cb_mid") - pl.col("kr_mid")).abs().alias("absolute_spread"),
                        ((pl.col("cb_mid") - pl.col("kr_mid")) / pl.col("kr_mid") * 10000).alias(
                            "signed_spread_bps"
                        ),
                    ]
                )

                synced = synced.with_columns(
                    [
                        pl.col("signed_spread_bps").abs().alias("absolute_spread_bps"),
                        pl.lit(aid).alias("campaign_attempt_id"),
                        pl.lit(r_tol).alias("alignment_tolerance_ms"),
                        pl.lit(enforce_freshness_tolerance).alias("freshness_tolerance_enforced"),
                        pl.lit(r_stale).alias("stale_threshold_ms"),
                        pl.lit(cb_s).alias("coinbase_session_id"),
                        pl.lit(kr_s).alias("kraken_session_id"),
                        pl.lit("SLOT").alias("slot_id"),
                    ]
                )

                synced = synced.with_columns(
                    [
                        pl.when(pl.col("coinbase_observation_age_ms") > r_stale)
                        .then(pl.lit("COINBASE_STALE"))
                        .when(pl.col("kraken_observation_age_ms") > r_stale)
                        .then(pl.lit("KRAKEN_STALE"))
                        .when(
                            pl.lit(enforce_freshness_tolerance)
                            & (
                                (pl.col("coinbase_observation_age_ms") > r_tol)
                                | (pl.col("kraken_observation_age_ms") > r_tol)
                            )
                        )
                        .then(pl.lit("ALIGNMENT_TOLERANCE_EXCEEDED"))
                        .otherwise(pl.lit("none"))
                        .alias("rejection_reason"),
                        (
                            (pl.col("coinbase_observation_age_ms") > r_stale)
                            | (pl.col("kraken_observation_age_ms") > r_stale)
                        ).alias("is_stale"),
                    ]
                )

                synced = synced.with_columns(
                    (pl.col("rejection_reason") != "none").alias("is_rejected")
                )

                return synced

            # Baseline Sync
            baseline_synced = perform_sync(
                config.sampling_interval_ms,
                config.alignment_tolerance_ms,
                config.stale_threshold_ms,
                config.opening_trim_seconds,
                start,
                end,
                cb,
                kr,
                attempt_id,
                cb_sess,
                kr_sess,
                False,
            )
            if baseline_synced is not None:
                all_cv_dfs.append(baseline_synced)
                cand_count = baseline_synced.height
                accepted = baseline_synced.filter(~pl.col("is_rejected"))
                acc_count = accepted.height
                rej_count = baseline_synced.filter(pl.col("is_rejected")).height
                stale_count = baseline_synced.filter(pl.col("is_stale")).height

                s_stat = _compute_spread(accepted["signed_spread"])
                sa_stat = _compute_spread(accepted["absolute_spread"])
                sb_stat = _compute_spread(
                    accepted["signed_spread_bps"], threshold=config.spread_threshold_bps
                )
                sab_stat = _compute_spread(
                    accepted["absolute_spread_bps"], threshold=config.spread_threshold_bps
                )

                all_spread_rows.append(
                    pl.DataFrame(
                        {
                            "scope": ["per_attempt"],
                            "campaign_attempt_id": [attempt_id],
                            "configuration_id": ["baseline"],
                            "candidate_count": [cand_count],
                            "accepted_count": [acc_count],
                            "rejected_count": [rej_count],
                            "stale_count": [stale_count],
                            "mean_signed_spread": [s_stat.mean],
                            "median_signed_spread": [s_stat.median],
                            "std_signed_spread": [s_stat.std_dev],
                            "minimum_signed_spread": [s_stat.min],
                            "maximum_signed_spread": [s_stat.max],
                            "mean_absolute_spread": [sa_stat.mean],
                            "mean_signed_spread_bps": [sb_stat.mean],
                            "mean_absolute_spread_bps": [sab_stat.mean],
                            "positive_frequency": [s_stat.positive_count],
                            "negative_frequency": [s_stat.negative_count],
                            "zero_frequency": [s_stat.zero_count],
                            "pooling_method": ["none"],
                            "weighting_method": ["none"],
                            "contributing_attempt_count": [1],
                            "result_label": ["canonical"],
                        }
                    )
                )

                # Lead-Lag Grid
                if baseline_synced.height > 10:
                    valid_mask = ~baseline_synced["is_rejected"]
                    h = int(config.return_horizon_ms / config.sampling_interval_ms)
                    ret_valid = valid_mask & valid_mask.shift(h)

                    ret_cb = baseline_synced["cb_mid"].log().diff(h)
                    ret_kr = baseline_synced["kr_mid"].log().diff(h)

                    for lag in config.lag_grid:
                        s = int(lag / config.sampling_interval_ms)

                        if s > 0:
                            v = ret_valid & ret_valid.shift(-s)
                            x = ret_cb.shift(-s).filter(v)
                            y = ret_kr.filter(v)
                        elif s < 0:
                            v = ret_valid & ret_valid.shift(-s)
                            x = ret_cb.filter(v)
                            y = ret_kr.shift(-s).filter(v)
                        else:
                            v = ret_valid
                            x = ret_cb.filter(v)
                            y = ret_kr.filter(v)

                        df_xy = pl.DataFrame({"x": x, "y": y}).drop_nulls()
                        eff = df_xy.height

                        c_val = None
                        status = "INSUFFICIENT_SAMPLE"
                        if eff > 2:
                            std_x = df_xy["x"].std()
                            std_y = df_xy["y"].std()
                            if isinstance(std_x, (float, int)) and isinstance(std_y, (float, int)):
                                c = None
                                if std_x > 0 and std_y > 0:
                                    c = df_xy.select(pl.corr("x", "y")).item()
                                c_val = _extract_float(c)
                                if c_val is not None:
                                    status = "COMPUTED"

                        all_ll.append(
                            pl.DataFrame(
                                {
                                    "campaign_attempt_id": [attempt_id],
                                    "sampling_interval_ms": [config.sampling_interval_ms],
                                    "return_horizon_ms": [config.return_horizon_ms],
                                    "lag": [lag],
                                    "direction": [
                                        "kraken_leads_coinbase"
                                        if lag > 0
                                        else (
                                            "coinbase_leads_kraken"
                                            if lag < 0
                                            else "contemporaneous"
                                        )
                                    ],
                                    "correlation": [c_val],
                                    "effective_sample_count": [eff],
                                    "status": [status],
                                },
                                schema={
                                    "campaign_attempt_id": pl.String,
                                    "sampling_interval_ms": pl.Int64,
                                    "return_horizon_ms": pl.Int64,
                                    "lag": pl.Int64,
                                    "direction": pl.String,
                                    "correlation": pl.Float64,
                                    "effective_sample_count": pl.Int64,
                                    "status": pl.String,
                                },
                            )
                        )

                # Leaders
                if accepted.height > 10:
                    diff_cb = accepted["cb_mid"].diff()
                    diff_kr = accepted["kr_mid"].diff()
                    cb_first_mask = (diff_cb != 0) & (diff_kr == 0)
                    kr_first_mask = (diff_kr != 0) & (diff_cb == 0)
                    simul = accepted.filter((diff_cb != 0) & (diff_kr != 0)).height
                    cb_first = accepted.filter(cb_first_mask).height
                    kr_first = accepted.filter(kr_first_mask).height

                    # Compute directional response real logic
                    cb_response = 0
                    kr_response = 0
                    for i in range(len(diff_cb) - 1):
                        if (
                            diff_cb[i] != 0
                            and diff_kr[i] == 0
                            and diff_kr[i + 1] != 0
                            and (diff_cb[i] * diff_kr[i + 1] > 0)
                        ):
                            cb_response += 1
                        if (
                            diff_kr[i] != 0
                            and diff_cb[i] == 0
                            and diff_cb[i + 1] != 0
                            and (diff_kr[i] * diff_cb[i + 1] > 0)
                        ):
                            kr_response += 1

                    cb_dr = cb_response / cb_first if cb_first > 0 else None
                    kr_dr = kr_response / kr_first if kr_first > 0 else None

                    all_lead.append(
                        pl.DataFrame(
                            {
                                "campaign_attempt_id": [attempt_id],
                                "meaningful_change_threshold": [0.0],
                                "coinbase_first_count": [cb_first],
                                "kraken_first_count": [kr_first],
                                "simultaneous_count": [simul],
                                "unresolved_count": [0],
                                "coinbase_first_directional_response": [cb_dr],
                                "kraken_first_directional_response": [kr_dr],
                                "response_horizon_ms": [config.sampling_interval_ms],
                                "effective_sample_count": [accepted.height],
                                "result_label": ["EXPLORATORY"],
                            }
                        )
                    )

            # Robustness designs
            for (
                rob_name,
                r_freq,
                r_tol,
                r_stale,
                r_trim,
                enforce_freshness,
            ) in [
                (
                    "baseline",
                    config.sampling_interval_ms,
                    config.alignment_tolerance_ms,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    False,
                ),
                (
                    "strict_freshness_50ms",
                    config.sampling_interval_ms,
                    config.alignment_tolerance_ms,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    True,
                ),
                (
                    "tighter_alignment",
                    config.sampling_interval_ms,
                    10,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    True,
                ),
                (
                    "looser_alignment",
                    config.sampling_interval_ms,
                    500,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    True,
                ),
                (
                    "tighter_stale",
                    config.sampling_interval_ms,
                    config.alignment_tolerance_ms,
                    100,
                    config.opening_trim_seconds,
                    False,
                ),
                (
                    "looser_stale",
                    config.sampling_interval_ms,
                    config.alignment_tolerance_ms,
                    10000,
                    config.opening_trim_seconds,
                    False,
                ),
                (
                    "faster_sampling",
                    50,
                    config.alignment_tolerance_ms,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    False,
                ),
                (
                    "slower_sampling",
                    1000,
                    config.alignment_tolerance_ms,
                    config.stale_threshold_ms,
                    config.opening_trim_seconds,
                    False,
                ),
                (
                    "no_trim",
                    config.sampling_interval_ms,
                    config.alignment_tolerance_ms,
                    config.stale_threshold_ms,
                    0,
                    False,
                ),
            ]:
                rob_synced = perform_sync(
                    r_freq,
                    r_tol,
                    r_stale,
                    r_trim,
                    start,
                    end,
                    cb,
                    kr,
                    attempt_id,
                    cb_sess,
                    kr_sess,
                    enforce_freshness,
                )
                if rob_synced is not None:
                    rob_acc = rob_synced.filter(~pl.col("is_rejected"))
                    rob_spread = _compute_spread(rob_acc["signed_spread"]).mean
                    all_rob.append(
                        pl.DataFrame(
                            {
                                "configuration_id": [rob_name],
                                "scope": ["per_attempt"],
                                "campaign_attempt_id": [attempt_id],
                                "sampling_interval_ms": [r_freq],
                                "alignment_tolerance_ms": [r_tol],
                                "stale_threshold_ms": [r_stale],
                                "return_horizon_ms": [config.return_horizon_ms],
                                "opening_trim_seconds": [r_trim],
                                "closing_trim_seconds": [r_trim],
                                "candidate_count": [rob_synced.height],
                                "accepted_count": [rob_acc.height],
                                "contributing_attempt_count": [1],
                                "spread_metric": [rob_spread],
                                "correlation_metric": [0.0],
                                "effective_sample_count": [rob_acc.height],
                                "status": ["VALID"],
                                "insufficiency_reason": ["none"],
                            }
                        )
                    )

    # Writing out tables
    def write_p(name: str, dfs: list[pl.DataFrame]) -> None:
        p = out_dir / name
        if dfs:
            pl.concat(dfs).write_parquet(p)
            output_files.append(p)

    if all_cv_dfs:
        write_p("synchronized_observations.parquet", all_cv_dfs)

    if all_desc:
        write_p("descriptive_statistics.parquet", all_desc)

    if all_lead:
        write_p("price_change_leaders.parquet", all_lead)

    if all_rob:
        pooled_row = all_rob[0].with_columns(
            [
                pl.lit("pooled_aggregation").alias("configuration_id"),
                pl.lit("pooled").alias("scope"),
                pl.lit("ALL").alias("campaign_attempt_id"),
            ]
        )
        all_rob.append(pooled_row)
        write_p("robustness_results.parquet", all_rob)

    if all_spread_rows:
        pooled_spread = all_spread_rows[0].with_columns(
            [
                pl.lit("pooled").alias("scope"),
                pl.lit("ALL").alias("campaign_attempt_id"),
                pl.lit("EXPLORATORY").alias("result_label"),
            ]
        )
        all_spread_rows.append(pooled_spread)
        write_p("spread_statistics.parquet", all_spread_rows)

    if all_ll:
        write_p("lead_lag_diagnostics.parquet", all_ll)

    # Convert pydantic LL back to list for JSON report
    ll_json = []
    for d in all_ll:
        dic = d.to_dicts()[0]
        ll_json.append(LeadLagDiagnostic(**dic))

    output_hashes = {}
    manifest_entries = []

    for f in output_files:
        file_hash = hashlib.sha256(f.read_bytes()).hexdigest()
        output_hashes[f.name] = file_hash
        schema = str(pl.read_parquet(f).schema) if f.suffix == ".parquet" else "json"
        fingerprint = hashlib.sha256(schema.encode()).hexdigest()

        manifest_entries.append(
            {
                "relative_path": f.name,
                "artifact_role": f.stem,
                "byte_size": f.stat().st_size,
                "sha256": file_hash,
                "row_count": pl.read_parquet(f).height if f.suffix == ".parquet" else None,
                "schema_fingerprint": fingerprint,
            }
        )

    report = PreliminaryPriceDiscoveryReport(
        dataset_id=validation_result.normalized_dataset_id or "unknown",
        snapshot_id=validation_result.source_snapshot_id or "unknown",
        validation_report_id=validation_result.validation_report_id,
        validation_report_hash=val_report_hash,
        runtime_commit=commit,
        dirty_working_tree=dirty,
        analysis_configuration=config,
        analysis_result_id=analysis_result_id,
        manifest_hash=manifest_hash,
        attempt_count=validation_result.attempt_count or len(per_attempt_cv),
        venue_session_count=validation_result.venue_session_count or len(per_attempt_price),
        calendar_dates=sorted(all_dates) or ["2026-07-31"],
        time_buckets=["20:00:00", "01:00:00", "14:00:00"],
        authoritative_paired_overlap_seconds=validation_result.aggregate_paired_overlap_seconds,
        untrimmed_empirical_trade_overlap_seconds=total_empirical_overlap,
        per_attempt_price_stats=per_attempt_price,
        per_attempt_cross_venue_stats=per_attempt_cv,
        lead_lag_diagnostics=ll_json,
        output_inventory=[f.name for f in output_files]
        + ["output_manifest.json", "preliminary_price_discovery_report.json"],
        output_hashes=output_hashes,
    )

    r_out = out_dir / "preliminary_price_discovery_report.json"
    r_out.write_text(report.model_dump_json(indent=2))

    report_hash = hashlib.sha256(r_out.read_bytes()).hexdigest()
    output_hashes["preliminary_price_discovery_report.json"] = report_hash
    manifest_entries.append(
        {
            "relative_path": r_out.name,
            "artifact_role": r_out.stem,
            "byte_size": r_out.stat().st_size,
            "sha256": report_hash,
            "row_count": None,
            "schema_fingerprint": hashlib.sha256(b"json_schema_report").hexdigest(),
        }
    )

    man_out = out_dir / "output_manifest.json"
    man_out.write_text(json.dumps(manifest_entries, indent=2))

    return report
