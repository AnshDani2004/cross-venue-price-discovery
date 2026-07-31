"""Validated dataset manifest promotion."""

from __future__ import annotations

from pathlib import Path

from cross_venue.config import DataQualityConfig
from cross_venue.quality.exceptions import PromotionError
from cross_venue.quality.io import current_git_commit, model_sha256, persist_model_json, utc_now
from cross_venue.quality.models import (
    PairedQualityReport,
    QualityDisposition,
    ValidatedDatasetManifest,
)


def build_validated_dataset_manifest(
    paired_report: PairedQualityReport,
    *,
    quality_config: DataQualityConfig,
) -> ValidatedDatasetManifest:
    """Build an immutable manifest from an accepted paired quality report."""

    if paired_report.disposition != QualityDisposition.ACCEPTED:
        raise PromotionError("paired report is not accepted")
    for report in (paired_report.coinbase_report, paired_report.kraken_report):
        if report.disposition != QualityDisposition.ACCEPTED:
            raise PromotionError(f"session {report.session_id} is not accepted")
        if not report.archive_validation_passed:
            raise PromotionError(f"session {report.session_id} failed archive validation")
    overlap = paired_report.overlap
    if overlap.market_event_overlap_start is None or overlap.market_event_overlap_end is None:
        raise PromotionError("paired report has no market-event overlap")
    coinbase_start = paired_report.coinbase_report.metrics.coverage.first_market_event_ts
    kraken_start = paired_report.kraken_report.metrics.coverage.first_market_event_ts
    coinbase_end = paired_report.coinbase_report.metrics.coverage.last_market_event_ts
    kraken_end = paired_report.kraken_report.metrics.coverage.last_market_event_ts
    if coinbase_start is None or kraken_start is None or coinbase_end is None or kraken_end is None:
        raise PromotionError("accepted sessions require market-event timestamp bounds")
    manifest = ValidatedDatasetManifest(
        dataset_manifest_id=f"validated-{paired_report.paired_collection_id}",
        created_at=utc_now(),
        created_by_git_commit=current_git_commit(),
        quality_policy_version=quality_config.policy_version,
        canonical_instrument=paired_report.coinbase_report.canonical_instrument,
        venues=(paired_report.coinbase_report.venue, paired_report.kraken_report.venue),
        session_ids=(
            paired_report.coinbase_report.session_id,
            paired_report.kraken_report.session_id,
        ),
        paired_collection_ids=(paired_report.paired_collection_id,),
        raw_session_relative_paths=(
            paired_report.coinbase_report.source_session_relative_path,
            paired_report.kraken_report.source_session_relative_path,
        ),
        raw_manifest_hashes={
            paired_report.coinbase_report.session_id: (
                paired_report.coinbase_report.source_manifest_sha256
            ),
            paired_report.kraken_report.session_id: (
                paired_report.kraken_report.source_manifest_sha256
            ),
        },
        raw_shard_checksums={
            **paired_report.coinbase_report.input_shard_checksums,
            **paired_report.kraken_report.input_shard_checksums,
        },
        session_quality_report_paths=(
            (
                paired_report.coinbase_report.report_relative_path
                or f"reports/{paired_report.coinbase_report.session_id}.json"
            ),
            (
                paired_report.kraken_report.report_relative_path
                or f"reports/{paired_report.kraken_report.session_id}.json"
            ),
        ),
        session_quality_report_hashes={
            paired_report.coinbase_report.session_id: model_sha256(paired_report.coinbase_report),
            paired_report.kraken_report.session_id: model_sha256(paired_report.kraken_report),
        },
        cross_venue_overlap_report_path=(
            paired_report.paired_report_relative_path or "paired_report_not_persisted.json"
        ),
        start_time=min(coinbase_start, kraken_start),
        end_time=max(coinbase_end, kraken_end),
        overlap_start=overlap.market_event_overlap_start,
        overlap_end=overlap.market_event_overlap_end,
        overlap_duration_seconds=overlap.market_event_overlap_duration_seconds,
        accepted_channels=("matches", "ticker", "trade"),
        known_limitations=(
            "Raw archives are referenced, not copied or transformed.",
            "No deduplication, gap repair, feature engineering, modeling, "
            "or trading logic is included.",
        ),
    )
    return manifest.model_copy(update={"content_sha256": model_sha256(manifest)})


def promote_dataset(
    paired_report: PairedQualityReport,
    *,
    quality_config: DataQualityConfig,
    apply: bool = False,
) -> tuple[ValidatedDatasetManifest | None, str]:
    """Dry-run or apply validated dataset manifest creation."""

    manifest = build_validated_dataset_manifest(paired_report, quality_config=quality_config)
    path = quality_config.validated_manifest_root / f"{manifest.dataset_manifest_id}.json"
    if path.exists():
        raise PromotionError(f"validated manifest already exists: {path}")
    if not apply:
        return manifest, f"dry-run: would create {path}"
    persist_validated_manifest(path, manifest)
    return manifest, f"created {path}"


def persist_validated_manifest(path: Path, manifest: ValidatedDatasetManifest) -> None:
    """Persist an immutable validated dataset manifest."""

    if path.exists():
        raise PromotionError(f"validated manifest already exists: {path}")
    persist_model_json(path, manifest)
