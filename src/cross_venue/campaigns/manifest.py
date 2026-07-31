"""Validated multi-session campaign manifest finalization."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from cross_venue.campaigns.exceptions import CampaignCompletionError
from cross_venue.campaigns.models import (
    AcceptedPairManifestReference,
    AttemptStatus,
    CampaignConfig,
    CampaignRole,
    CampaignStatus,
    InclusionStatus,
    ValidatedCampaignManifest,
)
from cross_venue.campaigns.registry import load_registry, registry_sha256
from cross_venue.campaigns.validation import validate_campaign
from cross_venue.quality.io import current_git_commit, model_sha256, utc_now
from cross_venue.storage.manifest_store import atomic_write_json


def finalize_campaign_manifest(config: CampaignConfig) -> tuple[ValidatedCampaignManifest, Path]:
    """Create the ignored validated campaign manifest after completion."""

    registry = load_registry(config)
    if registry.campaign_role == CampaignRole.DEVELOPMENT_SMOKE:
        raise CampaignCompletionError(
            "development smoke campaigns cannot finalize as research evidence"
        )
    if registry.campaign_status != CampaignStatus.COMPLETE:
        raise CampaignCompletionError("cannot finalize an incomplete campaign")
    validate_campaign(config)
    accepted = [
        attempt
        for attempt in registry.attempts.values()
        if attempt.attempt_status == AttemptStatus.ACCEPTED
        and attempt.inclusion_status == InclusionStatus.INCLUDED
    ]
    entries = tuple(
        AcceptedPairManifestReference(
            slot_id=attempt.slot_id,
            campaign_attempt_id=attempt.campaign_attempt_id,
            planned_start_utc=attempt.planned_start_utc,
            actual_start_utc=attempt.actual_started_at or attempt.planned_start_utc,
            time_bucket=attempt.time_bucket,
            paired_collection_id=attempt.paired_collection_id or "",
            validated_pair_manifest_id=attempt.validated_pair_manifest_id or "",
            validated_pair_manifest_relative_path=attempt.validated_pair_manifest_path or "",
            validated_pair_manifest_sha256=attempt.validated_pair_manifest_sha256 or "",
            paired_overlap_seconds=attempt.paired_overlap_seconds,
            coinbase_session_id=attempt.coinbase_session_id or "",
            kraken_session_id=attempt.kraken_session_id or "",
            source_manifest_hashes=attempt.source_session_manifest_hashes,
            source_shard_checksums=attempt.source_raw_shard_checksums,
            quality_report_hashes=attempt.session_quality_report_hashes,
        )
        for attempt in sorted(accepted, key=lambda item: (item.planned_start_utc, item.slot_id))
    )
    attempt_counts = Counter(attempt.attempt_status.value for attempt in registry.attempts.values())
    slot_counts = Counter(state.status.value for state in registry.planned_slots.values())
    manifest = ValidatedCampaignManifest(
        validated_campaign_manifest_version="3b.1",
        validated_campaign_manifest_id=f"validated-campaign-{config.campaign_id}",
        campaign_id=config.campaign_id,
        campaign_role=registry.campaign_role,
        campaign_schema_version=registry.campaign_schema_version,
        created_at=utc_now(),
        campaign_runtime_commit=registry.runtime_git_commit,
        finalization_commit=current_git_commit(),
        campaign_config_sha256=registry.campaign_config_sha256,
        quality_policy_version=registry.quality_policy_version,
        quality_policy_sha256=registry.quality_policy_sha256,
        campaign_registry_sha256=registry_sha256(config),
        campaign_ledger_sha256=registry.ledger_sha256,
        instrument=registry.instrument,
        venues=registry.venues,
        timezone=registry.timezone,
        accepted_attempt_count=registry.accepted_attempt_count,
        accepted_overlap_seconds=registry.accepted_overlap_seconds,
        accepted_calendar_dates=registry.accepted_calendar_dates,
        accepted_time_buckets=registry.accepted_time_buckets,
        all_attempt_counts_by_status=dict(attempt_counts),
        all_slot_counts_by_status=dict(slot_counts),
        accepted_pair_manifests=entries,
        excluded_attempt_summary=tuple(
            _excluded_summary(attempt)
            for attempt in registry.attempts.values()
            if attempt.inclusion_status == InclusionStatus.EXCLUDED
        ),
        minimum_requirements={
            "minimum_accepted_sessions": config.minimum_accepted_sessions,
            "minimum_total_accepted_overlap_seconds": (
                config.minimum_total_accepted_overlap_seconds
            ),
            "minimum_calendar_dates": config.minimum_calendar_dates,
            "minimum_time_buckets": config.minimum_time_buckets,
        },
        completion_evidence=registry.completion_requirements.model_dump(mode="json"),
    )
    manifest = manifest.model_copy(update={"content_hash": model_sha256(manifest)})
    output_path = config.validated_manifest_root / f"{manifest.validated_campaign_manifest_id}.json"
    if output_path.exists():
        raise CampaignCompletionError(f"campaign manifest already exists: {output_path}")
    atomic_write_json(output_path, manifest.model_dump(mode="json"))
    return manifest, output_path


def _excluded_summary(attempt: Any) -> dict[str, Any]:
    return {
        "slot_id": attempt.slot_id,
        "campaign_attempt_id": attempt.campaign_attempt_id,
        "attempt_status": attempt.attempt_status.value,
        "exclusion_reason": attempt.exclusion_reason,
    }
