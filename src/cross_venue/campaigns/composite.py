"""Composite exploratory dataset handoff across separate campaigns."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.campaigns.exceptions import CampaignValidationError
from cross_venue.campaigns.ledger import ledger_sha256
from cross_venue.campaigns.models import (
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    CampaignRole,
    InclusionStatus,
)
from cross_venue.campaigns.paths import ledger_path
from cross_venue.campaigns.registry import (
    registry_sha256,
    validate_registry_and_ledger,
)
from cross_venue.quality.io import current_git_commit, model_sha256, utc_now
from cross_venue.schemas import Exchange
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json

COMPOSITE_EXPLORATORY_LABEL = "SUPPLEMENTAL_INTRADAY_EXPLORATORY_DATASET"
COMPOSITE_EXPLORATORY_WARNING = (
    "Eight-session intraday pilot plus a separately registered supplemental exploratory "
    "campaign. This exploratory composite supports descriptive analysis and hypothesis "
    "generation only; it is not a substitute for the multi-day validation campaign."
)


class CompositeCampaignSource(BaseModel):
    """One immutable source campaign referenced by a composite exploratory dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    campaign_role: CampaignRole
    campaign_runtime_commit: str
    campaign_config_sha256: str
    quality_policy_version: str
    quality_policy_sha256: str
    campaign_registry_sha256: str
    campaign_ledger_sha256: str
    accepted_attempt_count: int = Field(ge=0)
    accepted_overlap_seconds: float = Field(ge=0)
    accepted_attempt_ids: tuple[str, ...]


class CompositeAcceptedAttemptReference(BaseModel):
    """Lineage for one accepted attempt included in a composite exploratory dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_campaign_id: str
    source_campaign_role: CampaignRole
    slot_id: str
    campaign_attempt_id: str
    planned_start_utc: str
    actual_start_utc: str | None
    time_bucket: str
    attempt_runtime_commit: str | None
    paired_collection_id: str
    validated_pair_manifest_id: str
    validated_pair_manifest_path: str
    validated_pair_manifest_sha256: str
    paired_quality_report_hash: str
    session_quality_report_hashes: dict[str, str]
    source_session_manifest_hashes: dict[str, str]
    source_raw_shard_checksums: dict[str, dict[str, str]]
    inclusion_status: Literal["INCLUDED"]
    paired_overlap_seconds: float = Field(ge=0)

    @field_validator(
        "validated_pair_manifest_id",
        "validated_pair_manifest_path",
        "validated_pair_manifest_sha256",
        "paired_quality_report_hash",
    )
    @classmethod
    def required_lineage_field(cls, value: str) -> str:
        if not value:
            raise ValueError("accepted composite attempts require complete lineage")
        return value


class CompositeExploratoryDatasetManifest(BaseModel):
    """Manifest for a composite exploratory dataset spanning separate campaign ledgers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    composite_manifest_version: Literal["3b-composite.1"] = "3b-composite.1"
    composite_dataset_label: Literal["SUPPLEMENTAL_INTRADAY_EXPLORATORY_DATASET"] = (
        "SUPPLEMENTAL_INTRADAY_EXPLORATORY_DATASET"
    )
    warning: str
    created_at: str
    creation_commit: str
    source_campaign_ids: tuple[str, ...]
    instrument: str
    venues: tuple[Exchange, Exchange]
    quality_policy_version: str
    aggregate_accepted_session_count: int = Field(ge=0)
    aggregate_paired_overlap_seconds: float = Field(ge=0)
    accepted_session_count_requirement: int = Field(gt=0)
    accepted_overlap_seconds_requirement: float = Field(gt=0)
    requirements_satisfied: bool
    sources: tuple[CompositeCampaignSource, ...]
    accepted_attempts: tuple[CompositeAcceptedAttemptReference, ...]
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def source_identity_must_match_entries(self) -> CompositeExploratoryDatasetManifest:
        if self.source_campaign_ids != tuple(source.campaign_id for source in self.sources):
            raise ValueError("source campaign IDs must match source entries")
        return self


def build_composite_exploratory_dataset(
    campaign_configs: tuple[CampaignConfig, ...],
    *,
    output_path: Path,
    accepted_session_count_requirement: int = 10,
    accepted_overlap_seconds_requirement: float = 18_000,
) -> tuple[CompositeExploratoryDatasetManifest, Path]:
    """Create a lineage-only composite manifest without mutating source campaigns."""

    if len(campaign_configs) < 2:
        raise CampaignValidationError("composite exploratory dataset requires multiple campaigns")
    if output_path.exists():
        raise CampaignValidationError(f"composite manifest already exists: {output_path}")

    sources: list[CompositeCampaignSource] = []
    accepted_entries: list[CompositeAcceptedAttemptReference] = []
    instruments: set[str] = set()
    venues: set[tuple[Exchange, Exchange]] = set()
    quality_versions: set[str] = set()
    source_ids: list[str] = []

    for config in campaign_configs:
        registry = validate_registry_and_ledger(config)
        if registry.campaign_role != CampaignRole.EXPLORATORY_INTRADAY:
            raise CampaignValidationError(
                f"source campaign is not exploratory intraday: {registry.campaign_id}"
            )
        if registry.campaign_config_sha256 != sha256_file(Path(registry.campaign_config_path)):
            raise CampaignValidationError(
                f"source campaign config hash drift: {registry.campaign_id}"
            )
        source_ids.append(registry.campaign_id)
        instruments.add(registry.instrument)
        venues.add(registry.venues)
        quality_versions.add(registry.quality_policy_version)
        accepted = tuple(
            attempt
            for attempt in sorted(
                registry.attempts.values(),
                key=lambda item: (item.planned_start_utc, item.slot_id, item.campaign_attempt_id),
            )
            if attempt.attempt_status == AttemptStatus.ACCEPTED
            and attempt.inclusion_status == InclusionStatus.INCLUDED
        )
        sources.append(
            CompositeCampaignSource(
                campaign_id=registry.campaign_id,
                campaign_role=registry.campaign_role,
                campaign_runtime_commit=registry.runtime_git_commit,
                campaign_config_sha256=registry.campaign_config_sha256,
                quality_policy_version=registry.quality_policy_version,
                quality_policy_sha256=registry.quality_policy_sha256,
                campaign_registry_sha256=registry_sha256(config),
                campaign_ledger_sha256=ledger_sha256(ledger_path(config)),
                accepted_attempt_count=len(accepted),
                accepted_overlap_seconds=sum(
                    attempt.paired_overlap_seconds for attempt in accepted
                ),
                accepted_attempt_ids=tuple(attempt.campaign_attempt_id for attempt in accepted),
            )
        )
        accepted_entries.extend(
            _accepted_attempt_entry(registry.campaign_id, registry.campaign_role, attempt)
            for attempt in accepted
        )

    if len(set(source_ids)) != len(source_ids):
        raise CampaignValidationError("composite source campaign IDs must be unique")
    if len(instruments) != 1 or len(venues) != 1 or len(quality_versions) != 1:
        raise CampaignValidationError(
            "composite source campaigns must share instrument, venues, and policy"
        )

    accepted_count = len(accepted_entries)
    accepted_overlap = sum(entry.paired_overlap_seconds for entry in accepted_entries)
    manifest = CompositeExploratoryDatasetManifest(
        warning=COMPOSITE_EXPLORATORY_WARNING,
        created_at=utc_now().isoformat(),
        creation_commit=current_git_commit(),
        source_campaign_ids=tuple(source_ids),
        instrument=instruments.pop(),
        venues=venues.pop(),
        quality_policy_version=quality_versions.pop(),
        aggregate_accepted_session_count=accepted_count,
        aggregate_paired_overlap_seconds=accepted_overlap,
        accepted_session_count_requirement=accepted_session_count_requirement,
        accepted_overlap_seconds_requirement=accepted_overlap_seconds_requirement,
        requirements_satisfied=(
            accepted_count >= accepted_session_count_requirement
            and accepted_overlap >= accepted_overlap_seconds_requirement
        ),
        sources=tuple(sources),
        accepted_attempts=tuple(accepted_entries),
    )
    manifest = manifest.model_copy(update={"content_hash": model_sha256(manifest)})
    atomic_write_json(output_path, manifest.model_dump(mode="json"))
    return manifest, output_path


def _accepted_attempt_entry(
    campaign_id: str,
    campaign_role: CampaignRole,
    attempt: AttemptSummary,
) -> CompositeAcceptedAttemptReference:
    return CompositeAcceptedAttemptReference(
        source_campaign_id=campaign_id,
        source_campaign_role=campaign_role,
        slot_id=attempt.slot_id,
        campaign_attempt_id=attempt.campaign_attempt_id,
        planned_start_utc=attempt.planned_start_utc.isoformat(),
        actual_start_utc=attempt.actual_started_at.isoformat()
        if attempt.actual_started_at
        else None,
        time_bucket=attempt.time_bucket.value,
        attempt_runtime_commit=attempt.attempt_runtime_git_commit,
        paired_collection_id=attempt.paired_collection_id or "",
        validated_pair_manifest_id=attempt.validated_pair_manifest_id or "",
        validated_pair_manifest_path=attempt.validated_pair_manifest_path or "",
        validated_pair_manifest_sha256=attempt.validated_pair_manifest_sha256 or "",
        paired_quality_report_hash=attempt.paired_quality_report_hash or "",
        session_quality_report_hashes=dict(attempt.session_quality_report_hashes),
        source_session_manifest_hashes=dict(attempt.source_session_manifest_hashes),
        source_raw_shard_checksums={
            session_id: dict(checksums)
            for session_id, checksums in attempt.source_raw_shard_checksums.items()
        },
        inclusion_status="INCLUDED",
        paired_overlap_seconds=attempt.paired_overlap_seconds,
    )
