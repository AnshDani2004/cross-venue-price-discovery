"""Paired controlled public collection with quality analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cross_venue.collectors.coinbase.collector import load_coinbase_live_collector
from cross_venue.collectors.kraken.collector import load_kraken_live_collector
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.exceptions import CollectionPreflightError
from cross_venue.quality.io import current_git_commit, persist_model_json, portable_relative_path
from cross_venue.quality.models import PairedQualityReport, SessionQualityReport
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.runtime_limits import (
    MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    validate_paired_collection_duration,
    validate_paired_collection_message_limit,
)
from cross_venue.storage.archive_writer import RotatingRawArchiveWriter
from cross_venue.storage.manifest_store import persist_manifest
from cross_venue.storage.quality_store import persist_quality_summary
from cross_venue.storage.session import build_manifest, build_quality_summary


@dataclass(frozen=True, slots=True)
class PairedCollectionResult:
    """Result of one paired controlled quality collection."""

    paired_report: PairedQualityReport
    coinbase_summary: CollectorRunSummary
    kraken_summary: CollectorRunSummary
    coinbase_report_path: Path
    kraken_report_path: Path
    paired_report_path: Path

    @property
    def successful(self) -> bool:
        return self.paired_report.disposition.value == "ACCEPTED"

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Paired collection ID: {self.paired_report.paired_collection_id}",
                f"Coinbase session ID: {self.paired_report.coinbase_report.session_id}",
                f"Kraken session ID: {self.paired_report.kraken_report.session_id}",
                f"Requested duration: {self.paired_report.overlap.requested_duration_seconds}",
                f"Start skew seconds: {self.paired_report.overlap.start_skew_seconds}",
                (
                    "Overlap duration seconds: "
                    f"{self.paired_report.overlap.market_event_overlap_duration_seconds}"
                ),
                (
                    "Coinbase frames: "
                    f"{self.paired_report.coinbase_report.metrics.coverage.frames_received}"
                ),
                (
                    "Kraken frames: "
                    f"{self.paired_report.kraken_report.metrics.coverage.frames_received}"
                ),
                (f"Coinbase disposition: {self.paired_report.coinbase_report.disposition.value}"),
                f"Kraken disposition: {self.paired_report.kraken_report.disposition.value}",
                f"Paired disposition: {self.paired_report.disposition.value}",
                f"Paired report: {self.paired_report_path}",
            ]
        )


async def collect_paired_quality(
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    duration_seconds: float | None = None,
    max_messages_per_venue: int | None = None,
    paired_collection_id: str | None = None,
) -> PairedCollectionResult:
    """Run one bounded concurrent Coinbase/Kraken archival collection and analyze it."""

    requested_duration = (
        quality_config.default_controlled_duration_seconds
        if duration_seconds is None
        else duration_seconds
    )
    try:
        requested_duration = validate_paired_collection_duration(requested_duration)
    except ValueError as exc:
        raise CollectionPreflightError(str(exc)) from exc
    message_limit = (
        quality_config.max_messages_per_venue
        if max_messages_per_venue is None
        else max_messages_per_venue
    )
    try:
        message_limit = validate_paired_collection_message_limit(message_limit)
    except ValueError as exc:
        raise CollectionPreflightError(str(exc)) from exc
    pair_id = paired_collection_id or f"paired-{uuid4()}"
    limits = RunLimits(
        duration_seconds=requested_duration,
        max_messages=message_limit,
        max_phase_duration_seconds=MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    )
    coinbase_writer = RotatingRawArchiveWriter(storage_config=storage_config)
    kraken_writer = RotatingRawArchiveWriter(storage_config=storage_config)
    coinbase_task = asyncio.create_task(
        load_coinbase_live_collector().collect(limits=limits, archive_writer=coinbase_writer)
    )
    kraken_task = asyncio.create_task(
        load_kraken_live_collector().collect(limits=limits, archive_writer=kraken_writer)
    )
    coinbase_summary, kraken_summary = await asyncio.gather(coinbase_task, kraken_task)
    coinbase_report = _persist_summary_and_analyze(
        coinbase_summary,
        storage_config=storage_config,
        quality_config=quality_config,
        pair_id=pair_id,
        venue_name="coinbase",
    )
    kraken_report = _persist_summary_and_analyze(
        kraken_summary,
        storage_config=storage_config,
        quality_config=quality_config,
        pair_id=pair_id,
        venue_name="kraken",
    )
    start_skew = abs(
        (coinbase_summary.stats.started_at - kraken_summary.stats.started_at).total_seconds()
    )
    paired_report = build_paired_quality_report(
        paired_collection_id=pair_id,
        requested_duration_seconds=requested_duration,
        start_skew_seconds=start_skew,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    )
    pair_root = quality_config.report_root / "paired" / pair_id
    paired_report_path = pair_root / "paired_quality_report.json"
    paired_report = paired_report.model_copy(
        update={
            "paired_report_relative_path": portable_relative_path(
                quality_config.report_root,
                paired_report_path,
            )
        }
    )
    persist_model_json(paired_report_path, paired_report)
    return PairedCollectionResult(
        paired_report=paired_report,
        coinbase_summary=coinbase_summary,
        kraken_summary=kraken_summary,
        coinbase_report_path=pair_root / "coinbase_session_quality_report.json",
        kraken_report_path=pair_root / "kraken_session_quality_report.json",
        paired_report_path=paired_report_path,
    )


def _persist_summary_and_analyze(
    summary: CollectorRunSummary,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    pair_id: str,
    venue_name: str,
) -> SessionQualityReport:
    if summary.archive_summary is None:
        raise ValueError(f"{venue_name} archive summary missing")
    persist_manifest(
        summary.archive_summary.session_paths.manifest_path,
        build_manifest(summary, git_commit=current_git_commit()),
    )
    persist_quality_summary(
        summary.archive_summary.session_paths.quality_path,
        build_quality_summary(summary),
    )
    pair_root = quality_config.report_root / "paired" / pair_id
    report_path = pair_root / f"{venue_name}_session_quality_report.json"
    report = analyze_session_quality(
        summary.archive_summary.session_paths.session_root,
        storage_config=storage_config,
        quality_config=quality_config,
        report_path=report_path,
    )
    report = report.model_copy(
        update={
            "report_relative_path": portable_relative_path(
                quality_config.report_root,
                report_path,
            )
        }
    )
    persist_model_json(report_path, report)
    return report
