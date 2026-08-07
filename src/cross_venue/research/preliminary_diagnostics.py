"""Phase 4A preliminary readiness diagnostics.

Analyzes a validated normalized dataset's empirical suitability for
preliminary cross-venue price-discovery research.

Does *not* perform final causal inference.  Quantifies per-session data
density, timestamp quality, and cross-venue paired overlap to determine
whether the dataset is structurally ready for exploratory lead-lag analysis.

Readiness thresholds are sourced from the authoritative campaign
configuration (``configs/campaigns/phase_3b_btc_usd.toml``):

  - ``minimum_overlap_seconds_per_accepted_session = 1800``
    Each accepted paired slot must deliver at least 1800 seconds of
    cross-venue overlap to be considered individually usable.

  - ``minimum_total_accepted_overlap_seconds = 18000``
    The aggregate over all accepted sessions must reach 18000 seconds for
    the final ten-session composite to be satisfied.

The seven-session snapshot has ~13 005 seconds total overlap (7 x ~1858 s),
which is structurally valid for preliminary diagnostics even though it does
not yet meet the final 18 000-second composite.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pydantic import BaseModel, Field

from cross_venue.normalization.validation import NormalizedDatasetValidationResult
from cross_venue.research.exceptions import ResearchError

# ---------------------------------------------------------------------------
# Authoritative thresholds
# (sourced from configs/campaigns/phase_3b_btc_usd.toml)
# ---------------------------------------------------------------------------

#: Minimum cross-venue overlap seconds for a single accepted slot to be
#: individually usable for preliminary analysis.
#: Source: ``minimum_overlap_seconds_per_accepted_session = 1800``
MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT: float = 1800.0

#: Minimum aggregate overlap for the final composite to be satisfied.
#: Source: ``minimum_total_accepted_overlap_seconds = 18000``
MINIMUM_TOTAL_OVERLAP_SECONDS: float = 18_000.0

#: Minimum accepted sessions for final composite.
#: Source: ``minimum_accepted_sessions = 10``
MINIMUM_ACCEPTED_SESSIONS: int = 10


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SessionDiagnostics(BaseModel):
    """Per-venue-session diagnostic summary."""

    venue_session_id: str
    trade_count: int
    bbo_count: int
    min_trade_timestamp: str | None = None
    max_trade_timestamp: str | None = None
    median_trade_interarrival_ms: float | None = None
    median_bbo_interarrival_ms: float | None = None
    duplicate_exchange_ts_count: int = 0
    missing_exchange_ts_count: int = 0


class PairedOverlapDiagnostics(BaseModel):
    """Cross-venue overlap diagnostics for one accepted paired attempt."""

    campaign_attempt_id: str
    coinbase_session_id: str
    kraken_session_id: str
    overlap_duration_seconds: float
    per_attempt_threshold_seconds: float
    threshold_source: str
    is_valid_for_preliminary_analysis: bool
    failure_reason: str | None = None


class PreliminaryReadinessReport(BaseModel):
    """Phase 4A aggregate readiness report.

    Distinguishes:
      - ``structural_readiness`` — normalized outputs are valid and parseable.
      - ``preliminary_analysis_readiness`` — at least one accepted attempt
        meets the per-attempt overlap threshold.
      - ``final_composite_readiness`` — all final-composite requirements
        (10 sessions, 18 000 s total overlap, 3 dates, 3 time buckets) are met.
    """

    dataset_validation_id: str
    generated_at: str
    session_diagnostics: list[SessionDiagnostics] = Field(default_factory=list)
    paired_overlaps: list[PairedOverlapDiagnostics] = Field(default_factory=list)

    # Granular readiness flags
    structural_readiness: str
    preliminary_analysis_readiness: str
    final_composite_readiness: str

    # Human-readable explanations
    readiness_reasons: list[str] = Field(default_factory=list)
    blocking_conditions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Aggregate counts
    aggregate_overlap_seconds: float = 0.0
    aggregate_paired_overlap_seconds: float = 0.0
    valid_attempt_count: int = 0
    total_attempt_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_interarrivals(df: pl.DataFrame, time_col: str) -> float | None:
    """Median interarrival time in milliseconds for non-null timestamps.

    Sorts timestamps before computing differences to handle out-of-order rows.
    Returns None when fewer than two valid observations exist.
    """
    valid = df.filter(pl.col(time_col).is_not_null())
    if valid.height < 2:
        return None

    diffs = (
        valid.sort(time_col)
        .select(pl.col(time_col).diff().dt.total_nanoseconds() / 1_000_000.0)
        .drop_nulls()
    )

    if diffs.height == 0:
        return None

    val = diffs.median()
    if val is None:
        return None
    item = val.item()
    return float(item) if item is not None else None


def _diagnose_session(
    session_id: str,
    trade_path: Path | None,
    bbo_path: Path | None,
) -> SessionDiagnostics:
    """Compute diagnostic statistics for one venue session.

    Loads only the columns needed to avoid pulling large payloads into memory.
    """
    trade_count = 0
    bbo_count = 0
    min_ts: str | None = None
    max_ts: str | None = None
    median_trade_ia: float | None = None
    median_bbo_ia: float | None = None
    missing_ts = 0
    dup_ts = 0

    if trade_path is not None and trade_path.exists():
        trades = pl.read_parquet(trade_path, columns=["exchange_timestamp_utc"])
        trade_count = trades.height

        null_mask = pl.col("exchange_timestamp_utc").is_null()
        missing_ts += trades.select(null_mask.sum()).item()

        non_null = trades.filter(pl.col("exchange_timestamp_utc").is_not_null())
        if non_null.height > 0:
            n_unique = non_null.select(pl.col("exchange_timestamp_utc")).n_unique()
            dup_ts += non_null.height - n_unique

            # Min / max timestamps for overlap computation
            ts_min = non_null.select(pl.col("exchange_timestamp_utc").min()).item()
            ts_max = non_null.select(pl.col("exchange_timestamp_utc").max()).item()
            if ts_min is not None:
                min_ts = str(ts_min)
            if ts_max is not None:
                max_ts = str(ts_max)

        median_trade_ia = compute_interarrivals(trades, "exchange_timestamp_utc")

    if bbo_path is not None and bbo_path.exists():
        bbos = pl.read_parquet(bbo_path, columns=["exchange_timestamp_utc"])
        bbo_count = bbos.height

        null_mask = pl.col("exchange_timestamp_utc").is_null()
        missing_ts += bbos.select(null_mask.sum()).item()

        non_null = bbos.filter(pl.col("exchange_timestamp_utc").is_not_null())
        if non_null.height > 0:
            n_unique = non_null.select(pl.col("exchange_timestamp_utc")).n_unique()
            dup_ts += non_null.height - n_unique

        median_bbo_ia = compute_interarrivals(bbos, "exchange_timestamp_utc")

    return SessionDiagnostics(
        venue_session_id=session_id,
        trade_count=trade_count,
        bbo_count=bbo_count,
        min_trade_timestamp=min_ts,
        max_trade_timestamp=max_ts,
        median_trade_interarrival_ms=median_trade_ia,
        median_bbo_interarrival_ms=median_bbo_ia,
        duplicate_exchange_ts_count=dup_ts,
        missing_exchange_ts_count=missing_ts,
    )


def _compute_overlap_seconds(
    cb_trade_path: Path,
    kr_trade_path: Path,
) -> float:
    """Compute cross-venue overlap duration in seconds using trade timestamps.

    overlap = max(0, min(cb_max, kr_max) - max(cb_min, kr_min))
    """
    ts_col = "exchange_timestamp_utc"

    def _bounds(path: Path) -> tuple[Any, Any]:
        df = pl.read_parquet(path, columns=[ts_col])
        non_null = df.filter(pl.col(ts_col).is_not_null())
        if non_null.height == 0:
            return None, None
        return (
            non_null.select(pl.col(ts_col).min()).item(),
            non_null.select(pl.col(ts_col).max()).item(),
        )

    cb_min, cb_max = _bounds(cb_trade_path)
    kr_min, kr_max = _bounds(kr_trade_path)

    if None in (cb_min, cb_max, kr_min, kr_max):
        return 0.0

    start = max(cb_min, kr_min)
    end = min(cb_max, kr_max)

    if end <= start:
        return 0.0

    delta = end - start
    # Polars timedelta -> total_seconds
    if hasattr(delta, "total_seconds"):
        return float(delta.total_seconds())
    # datetime.timedelta
    if hasattr(delta, "total_seconds"):
        return float(delta.total_seconds())
    # Polars Duration -> microseconds
    try:
        return float(delta) / 1_000_000.0
    except (TypeError, ValueError):
        return float(delta.total_microseconds()) / 1_000_000.0


def _atomic_write_json_diagnostic(path: Path, data: str) -> None:
    """Atomically write diagnostic JSON report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = data.encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        written = 0
        while written < len(encoded):
            n = os.write(fd, encoded[written:])
            if n == 0:
                raise OSError("os.write returned 0 bytes")
            written += n
        os.fsync(fd)
        os.close(fd)
        Path(tmp).replace(path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_preliminary_readiness(
    dataset_root: Path,
    validation_report_path: Path,
) -> PreliminaryReadinessReport:
    """Analyze the validated dataset for Phase 4A preliminary readiness.

    Raises ``ResearchError`` if the dataset is ineligible or the validation
    report is missing or malformed.
    """
    if not validation_report_path.exists():
        raise ResearchError(f"Validation report not found: {validation_report_path}")

    # 1. Read raw JSON first — check eligibility before full parse
    raw_report = json.loads(validation_report_path.read_text(encoding="utf-8"))
    eligibility = raw_report.get("preliminary_analysis_eligibility")
    if eligibility is not None and eligibility != "ELIGIBLE":
        agg = raw_report.get("aggregate_disposition", "UNKNOWN")
        raise ResearchError(
            f"Dataset is not eligible for preliminary analysis. aggregate_disposition={agg!r}"
        )

    # 2. Validate complete Pydantic schema
    try:
        validation_result = NormalizedDatasetValidationResult.model_validate(raw_report)
    except Exception as exc:
        raise ResearchError(f"Validation report is malformed: {exc}") from exc

    # 3. Load normalization manifest for file path mappings
    manifest_path = dataset_root / "manifests" / "normalized_snapshot_manifest.json"
    if not manifest_path.exists():
        raise ResearchError("Normalized snapshot manifest missing.")

    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    # 4. Build session -> path maps from manifest entries
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

    session_diagnostics: list[SessionDiagnostics] = []
    paired_overlaps: list[PairedOverlapDiagnostics] = []
    warnings_list: list[str] = []
    blocking: list[str] = []
    reasons: list[str] = []

    total_overlap = 0.0
    valid_attempt_count = 0
    total_attempt_count = 0

    for entry in manifest.get("per_session_normalization_manifest_files", []):
        attempt_id = entry.get("campaign_attempt_id")
        if not attempt_id:
            continue

        sessions = entry.get("venue_session_ids", [])
        coinbase_sess = next((s for s in sessions if "coinbase" in s.lower()), None)
        kraken_sess = next((s for s in sessions if "kraken" in s.lower()), None)
        if not coinbase_sess or not kraken_sess:
            warnings_list.append(
                f"Attempt {attempt_id}: could not identify Coinbase and Kraken sessions"
            )
            continue

        total_attempt_count += 1

        cb_trade_path = trade_path_by_session.get(coinbase_sess)
        kr_trade_path = trade_path_by_session.get(kraken_sess)

        if cb_trade_path is None:
            raise ResearchError(
                f"Missing trade file mapping for Coinbase session {coinbase_sess!r} "
                f"in attempt {attempt_id!r}"
            )
        if kr_trade_path is None:
            raise ResearchError(
                f"Missing trade file mapping for Kraken session {kraken_sess!r} "
                f"in attempt {attempt_id!r}"
            )

        cb_bbo_path = bbo_path_by_session.get(coinbase_sess)
        kr_bbo_path = bbo_path_by_session.get(kraken_sess)

        if cb_bbo_path is None:
            warnings_list.append(f"No BBO file mapped for Coinbase session {coinbase_sess!r}")
        if kr_bbo_path is None:
            warnings_list.append(f"No BBO file mapped for Kraken session {kraken_sess!r}")

        cb_diag = _diagnose_session(coinbase_sess, cb_trade_path, cb_bbo_path)
        kr_diag = _diagnose_session(kraken_sess, kr_trade_path, kr_bbo_path)
        session_diagnostics.extend([cb_diag, kr_diag])

        # Compute overlap
        overlap_secs = 0.0
        failure_reason: str | None = None
        if cb_trade_path.exists() and kr_trade_path.exists():
            try:
                overlap_secs = _compute_overlap_seconds(cb_trade_path, kr_trade_path)
            except Exception as exc:
                warnings_list.append(f"Overlap computation failed for {attempt_id}: {exc}")
                failure_reason = f"computation error: {exc}"
        else:
            failure_reason = "trade file(s) missing"

        total_overlap += overlap_secs
        is_valid = overlap_secs >= MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT

        if not is_valid and failure_reason is None:
            failure_reason = (
                f"overlap {overlap_secs:.1f}s < threshold "
                f"{MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT:.0f}s"
            )

        if is_valid:
            valid_attempt_count += 1

        paired_overlaps.append(
            PairedOverlapDiagnostics(
                campaign_attempt_id=attempt_id,
                coinbase_session_id=coinbase_sess,
                kraken_session_id=kraken_sess,
                overlap_duration_seconds=round(overlap_secs, 6),
                per_attempt_threshold_seconds=MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT,
                threshold_source="configs/campaigns/phase_3b_btc_usd.toml:"
                "minimum_overlap_seconds_per_accepted_session",
                is_valid_for_preliminary_analysis=is_valid,
                failure_reason=failure_reason,
            )
        )

    # 5. Determine readiness flags
    structural_readiness = (
        "STRUCTURALLY_VALID"
        if validation_result.aggregate_disposition == "VALID"
        else "STRUCTURALLY_INVALID"
    )

    preliminary_readiness = (
        "PRELIMINARY_READY" if valid_attempt_count > 0 else "PRELIMINARY_NOT_READY"
    )

    final_composite_readiness = (
        "FINAL_COMPOSITE_SATISFIED"
        if validation_result.final_composite_status == "SATISFIED"
        else "FINAL_COMPOSITE_UNSATISFIED"
    )

    # Build human-readable explanations
    reasons.append(
        f"{structural_readiness}: normalized dataset has "
        f"aggregate_disposition={validation_result.aggregate_disposition!r}"
    )
    reasons.append(
        f"{preliminary_readiness}: {valid_attempt_count}/{total_attempt_count} "
        f"accepted attempts meet the {MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT:.0f}s "
        f"per-attempt overlap threshold"
    )
    reasons.append(
        f"Total overlap across all {total_attempt_count} attempts: "
        f"{total_overlap:.1f}s "
        f"(final composite requires {MINIMUM_TOTAL_OVERLAP_SECONDS:.0f}s "
        f"over {MINIMUM_ACCEPTED_SESSIONS} sessions)"
    )
    reasons.append(f"final_composite_status={validation_result.final_composite_status!r}")

    if preliminary_readiness == "PRELIMINARY_NOT_READY":
        blocking.append(
            "No accepted attempt meets the per-attempt overlap threshold of "
            f"{MINIMUM_OVERLAP_SECONDS_PER_ATTEMPT:.0f}s. "
            "This dataset is structurally valid but individual session overlaps "
            "are shorter than the analysis minimum."
        )

    if final_composite_readiness == "FINAL_COMPOSITE_UNSATISFIED":
        reasons.append(
            "NOTE: The seven-session dataset is eligible for preliminary "
            "exploratory diagnostics. Final empirical conclusions remain "
            "deferred pending the ten-session composite."
        )

    report = PreliminaryReadinessReport(
        dataset_validation_id=validation_result.validation_report_id,
        generated_at=datetime.now(UTC).isoformat(),
        session_diagnostics=session_diagnostics,
        paired_overlaps=paired_overlaps,
        structural_readiness=structural_readiness,
        preliminary_analysis_readiness=preliminary_readiness,
        final_composite_readiness=final_composite_readiness,
        readiness_reasons=reasons,
        blocking_conditions=blocking,
        warnings=warnings_list,
        aggregate_overlap_seconds=round(total_overlap, 6),
        aggregate_paired_overlap_seconds=round(
            validation_result.aggregate_paired_overlap_seconds, 6
        ),
        valid_attempt_count=valid_attempt_count,
        total_attempt_count=total_attempt_count,
    )

    report_path = dataset_root / "diagnostics" / "preliminary_readiness_report.json"
    _atomic_write_json_diagnostic(report_path, report.model_dump_json(indent=2))

    return report
