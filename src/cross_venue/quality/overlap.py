"""Cross-venue overlap and paired quality decisions."""

from __future__ import annotations

from datetime import datetime

from cross_venue.config import DataQualityConfig
from cross_venue.quality.io import current_git_commit, utc_now
from cross_venue.quality.models import (
    CrossVenueOverlapReport,
    PairedQualityReport,
    QualityDisposition,
    QualityFinding,
    QualitySeverity,
    SessionQualityReport,
)


def build_overlap_report(
    *,
    paired_collection_id: str,
    requested_duration_seconds: float,
    start_skew_seconds: float,
    coinbase_report: SessionQualityReport,
    kraken_report: SessionQualityReport,
) -> CrossVenueOverlapReport:
    """Calculate local-receipt-time overlap for paired venue sessions."""

    market_start, market_end, market_duration = _overlap(
        coinbase_report.metrics.coverage.first_market_event_ts,
        coinbase_report.metrics.coverage.last_market_event_ts,
        kraken_report.metrics.coverage.first_market_event_ts,
        kraken_report.metrics.coverage.last_market_event_ts,
    )
    book_start, book_end, book_duration = _overlap(
        coinbase_report.metrics.coverage.first_top_of_book_ts,
        coinbase_report.metrics.coverage.last_top_of_book_ts,
        kraken_report.metrics.coverage.first_top_of_book_ts,
        kraken_report.metrics.coverage.last_top_of_book_ts,
    )
    return CrossVenueOverlapReport(
        paired_collection_id=paired_collection_id,
        requested_duration_seconds=requested_duration_seconds,
        start_skew_seconds=start_skew_seconds,
        coinbase_session_id=coinbase_report.session_id,
        kraken_session_id=kraken_report.session_id,
        market_event_overlap_start=market_start,
        market_event_overlap_end=market_end,
        market_event_overlap_duration_seconds=market_duration,
        top_of_book_overlap_start=book_start,
        top_of_book_overlap_end=book_end,
        top_of_book_overlap_duration_seconds=book_duration,
        coinbase_overlap_coverage_rate=_coverage_rate(
            market_duration,
            coinbase_report.metrics.coverage.session_duration_seconds,
        ),
        kraken_overlap_coverage_rate=_coverage_rate(
            market_duration,
            kraken_report.metrics.coverage.session_duration_seconds,
        ),
        reconnect_boundaries_during_overlap=(
            coinbase_report.metrics.coverage.reconnects + kraken_report.metrics.coverage.reconnects
        ),
        stale_intervals_during_overlap=(
            coinbase_report.metrics.quotes.stale_interval_count
            + kraken_report.metrics.quotes.stale_interval_count
        ),
    )


def build_paired_quality_report(
    *,
    paired_collection_id: str,
    requested_duration_seconds: float,
    start_skew_seconds: float,
    coinbase_report: SessionQualityReport,
    kraken_report: SessionQualityReport,
    quality_config: DataQualityConfig,
) -> PairedQualityReport:
    """Build a paired quality report and apply overlap acceptance policy."""

    overlap = build_overlap_report(
        paired_collection_id=paired_collection_id,
        requested_duration_seconds=requested_duration_seconds,
        start_skew_seconds=start_skew_seconds,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
    )
    findings: list[QualityFinding] = []
    if start_skew_seconds > quality_config.quality.coverage.maximum_start_skew_seconds:
        findings.append(
            QualityFinding(
                finding_id="PAIR_START_SKEW_EXCEEDED",
                category="overlap",
                severity=QualitySeverity.WARNING,
                metric="start_skew_seconds",
                observed_value=start_skew_seconds,
                threshold=quality_config.quality.coverage.maximum_start_skew_seconds,
                message="paired collector start skew exceeds policy",
                evidence={"paired_collection_id": paired_collection_id},
            )
        )
    if (
        overlap.market_event_overlap_duration_seconds
        < quality_config.quality.coverage.minimum_cross_venue_overlap_seconds
    ):
        findings.append(
            QualityFinding(
                finding_id="PAIR_OVERLAP_TOO_SHORT",
                category="overlap",
                severity=QualitySeverity.ERROR,
                metric="market_event_overlap_duration_seconds",
                observed_value=overlap.market_event_overlap_duration_seconds,
                threshold=quality_config.quality.coverage.minimum_cross_venue_overlap_seconds,
                message="cross-venue local-receipt-time overlap is below policy",
                evidence={"paired_collection_id": paired_collection_id},
            )
        )
    disposition, reasons = _paired_disposition(
        findings,
        coinbase_report.disposition,
        kraken_report.disposition,
    )
    return PairedQualityReport(
        paired_collection_id=paired_collection_id,
        created_at=utc_now(),
        quality_policy_version=quality_config.policy_version,
        quality_code_git_commit=current_git_commit(),
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        overlap=overlap,
        findings=tuple(findings),
        disposition=disposition,
        disposition_reasons=tuple(reasons),
    )


def _paired_disposition(
    findings: list[QualityFinding],
    coinbase_disposition: QualityDisposition,
    kraken_disposition: QualityDisposition,
) -> tuple[QualityDisposition, list[str]]:
    reasons: list[str] = []
    if coinbase_disposition == QualityDisposition.REJECTED:
        reasons.append("Coinbase session rejected")
    if kraken_disposition == QualityDisposition.REJECTED:
        reasons.append("Kraken session rejected")
    errors = [
        finding
        for finding in findings
        if finding.severity in {QualitySeverity.CRITICAL, QualitySeverity.ERROR}
    ]
    if reasons or errors:
        return (
            QualityDisposition.REJECTED,
            reasons + [f"{finding.finding_id}: {finding.message}" for finding in errors],
        )
    warnings = [finding for finding in findings if finding.severity == QualitySeverity.WARNING]
    if (
        coinbase_disposition == QualityDisposition.QUARANTINED
        or kraken_disposition == QualityDisposition.QUARANTINED
        or warnings
    ):
        return (
            QualityDisposition.QUARANTINED,
            [
                reason
                for reason in (
                    "Coinbase session quarantined"
                    if coinbase_disposition == QualityDisposition.QUARANTINED
                    else "",
                    "Kraken session quarantined"
                    if kraken_disposition == QualityDisposition.QUARANTINED
                    else "",
                    *[f"{finding.finding_id}: {finding.message}" for finding in warnings],
                )
                if reason
            ],
        )
    return QualityDisposition.ACCEPTED, []


def _overlap(
    first_start: datetime | None,
    first_end: datetime | None,
    second_start: datetime | None,
    second_end: datetime | None,
) -> tuple[datetime | None, datetime | None, float]:
    if first_start is None or first_end is None or second_start is None or second_end is None:
        return None, None, 0.0
    start = max(first_start, second_start)
    end = min(first_end, second_end)
    if end <= start:
        return None, None, 0.0
    return start, end, (end - start).total_seconds()


def _coverage_rate(overlap_seconds: float, duration_seconds: float) -> float:
    if duration_seconds <= 0:
        return 0.0
    return max(0.0, min(1.0, overlap_seconds / duration_seconds))
