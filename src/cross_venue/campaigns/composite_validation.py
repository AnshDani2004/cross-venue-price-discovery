"""Composite validation manifest across separate multi-day campaigns."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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
from cross_venue.campaigns.registry import registry_sha256, validate_registry_and_ledger
from cross_venue.quality.io import current_git_commit, model_sha256, utc_now
from cross_venue.schemas import Exchange
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json

COMPOSITE_VALIDATION_LABEL = "SUPPLEMENTAL_MULTI_DAY_VALIDATION_DATASET"
COMPOSITE_VALIDATION_WARNING = (
    "Composite manifest over separate immutable multi-day validation campaign ledgers. "
    "This manifest verifies aggregate coverage only; it does not merge, rewrite, or "
    "reclassify source campaign evidence."
)


class CompositeValidationSource(BaseModel):
    """One validated source campaign referenced by a composite manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    campaign_role: Literal["MULTI_DAY_VALIDATION"]
    campaign_runtime_commit: str
    campaign_config_sha256: str
    quality_policy_version: str
    quality_policy_sha256: str
    campaign_registry_sha256: str
    campaign_ledger_sha256: str
    accepted_attempt_count: int = Field(ge=0)
    accepted_overlap_seconds: float = Field(ge=0)
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[str, ...]
    accepted_attempt_ids: tuple[str, ...]


class CompositeValidationAttemptReference(BaseModel):
    """Lineage for one accepted attempt in the composite validation manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_campaign_id: str
    source_campaign_role: Literal["MULTI_DAY_VALIDATION"]
    slot_id: str
    campaign_attempt_id: str
    planned_start_utc: datetime
    planned_start_local: str
    actual_start_utc: datetime
    time_bucket: str
    attempt_runtime_commit: str
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

    @field_validator("planned_start_utc", "actual_start_utc")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("composite attempt timestamps must be timezone-aware")
        return value

    @field_validator(
        "attempt_runtime_commit",
        "paired_collection_id",
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

    @model_validator(mode="after")
    def lineage_maps_must_be_present(self) -> CompositeValidationAttemptReference:
        if not self.session_quality_report_hashes:
            raise ValueError("accepted composite attempts require quality-report hashes")
        if not self.source_session_manifest_hashes:
            raise ValueError("accepted composite attempts require source-manifest hashes")
        if not self.source_raw_shard_checksums:
            raise ValueError("accepted composite attempts require raw-shard checksum references")
        return self


class CompositeValidationManifest(BaseModel):
    """Aggregate validation manifest spanning separate source campaign ledgers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    composite_manifest_version: Literal["3b-composite-validation.1"] = "3b-composite-validation.1"
    composite_dataset_label: Literal["SUPPLEMENTAL_MULTI_DAY_VALIDATION_DATASET"] = (
        "SUPPLEMENTAL_MULTI_DAY_VALIDATION_DATASET"
    )
    warning: str
    created_at: datetime
    creation_commit: str
    source_campaign_ids: tuple[str, ...]
    instrument: str
    venues: tuple[Exchange, Exchange]
    quality_policy_version: str
    quality_policy_sha256: str
    aggregate_accepted_session_count: int = Field(ge=0)
    aggregate_paired_overlap_seconds: float = Field(ge=0)
    aggregate_accepted_calendar_dates: tuple[str, ...]
    aggregate_accepted_time_buckets: tuple[str, ...]
    minimum_accepted_sessions: int = Field(gt=0)
    minimum_total_accepted_overlap_seconds: float = Field(gt=0)
    minimum_calendar_dates: int = Field(gt=0)
    minimum_time_buckets: int = Field(gt=0)
    sources: tuple[CompositeValidationSource, ...]
    accepted_attempts: tuple[CompositeValidationAttemptReference, ...]
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def source_identity_must_match_entries(self) -> CompositeValidationManifest:
        if self.source_campaign_ids != tuple(source.campaign_id for source in self.sources):
            raise ValueError("source campaign IDs must match source entries")
        return self


def build_composite_validation_manifest(
    campaign_configs: tuple[CampaignConfig, ...],
    *,
    output_path: Path,
    minimum_accepted_sessions: int = 10,
    minimum_total_accepted_overlap_seconds: float = 18_000,
    minimum_calendar_dates: int = 3,
    minimum_time_buckets: int = 3,
) -> tuple[CompositeValidationManifest, Path]:
    """Validate aggregate source coverage and persist a composite manifest."""

    if len(campaign_configs) < 2:
        raise CampaignValidationError("composite validation requires multiple campaigns")
    if output_path.exists():
        raise CampaignValidationError(
            f"composite validation manifest already exists: {output_path}"
        )

    sources: list[CompositeValidationSource] = []
    accepted_entries: list[CompositeValidationAttemptReference] = []
    source_ids: list[str] = []
    instruments: set[str] = set()
    venues: set[tuple[Exchange, Exchange]] = set()
    quality_versions: set[str] = set()
    quality_hashes: set[str] = set()

    for config in campaign_configs:
        registry = validate_registry_and_ledger(config)
        if registry.campaign_role != CampaignRole.MULTI_DAY_VALIDATION:
            raise CampaignValidationError(
                f"source campaign is not multi-day validation: {registry.campaign_id}"
            )
        if registry.campaign_config_sha256 != sha256_file(Path(registry.campaign_config_path)):
            raise CampaignValidationError(
                f"source campaign config hash drift: {registry.campaign_id}"
            )
        accepted = tuple(
            attempt
            for attempt in sorted(
                registry.attempts.values(),
                key=lambda item: (
                    item.planned_start_utc.astimezone(UTC),
                    item.slot_id,
                    item.campaign_attempt_id,
                ),
            )
            if attempt.attempt_status == AttemptStatus.ACCEPTED
            and attempt.inclusion_status == InclusionStatus.INCLUDED
        )
        source_ids.append(registry.campaign_id)
        instruments.add(registry.instrument)
        venues.add(registry.venues)
        quality_versions.add(registry.quality_policy_version)
        quality_hashes.add(registry.quality_policy_sha256)
        sources.append(
            CompositeValidationSource(
                campaign_id=registry.campaign_id,
                campaign_role="MULTI_DAY_VALIDATION",
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
                accepted_calendar_dates=registry.accepted_calendar_dates,
                accepted_time_buckets=tuple(
                    bucket.value for bucket in registry.accepted_time_buckets
                ),
                accepted_attempt_ids=tuple(attempt.campaign_attempt_id for attempt in accepted),
            )
        )
        for attempt in accepted:
            try:
                accepted_entries.append(_accepted_attempt_entry(registry.campaign_id, attempt))
            except ValidationError as exc:
                raise CampaignValidationError(
                    "accepted attempt requires complete lineage for composite validation: "
                    f"{attempt.campaign_attempt_id}"
                ) from exc

    if len(set(source_ids)) != len(source_ids):
        raise CampaignValidationError("composite source campaign IDs must be unique")
    if (
        len(instruments) != 1
        or len(venues) != 1
        or len(quality_versions) != 1
        or len(quality_hashes) != 1
    ):
        raise CampaignValidationError(
            "composite source campaigns must share instrument, venues, and quality policy"
        )

    aggregate_dates = tuple(
        sorted({entry.planned_start_local.split(" ")[0] for entry in accepted_entries})
    )
    aggregate_buckets = tuple(sorted({entry.time_bucket for entry in accepted_entries}))
    accepted_count = len(accepted_entries)
    accepted_overlap = sum(entry.paired_overlap_seconds for entry in accepted_entries)
    _require_aggregate_thresholds(
        accepted_count=accepted_count,
        accepted_overlap=accepted_overlap,
        accepted_dates=len(aggregate_dates),
        accepted_buckets=len(aggregate_buckets),
        minimum_accepted_sessions=minimum_accepted_sessions,
        minimum_total_accepted_overlap_seconds=minimum_total_accepted_overlap_seconds,
        minimum_calendar_dates=minimum_calendar_dates,
        minimum_time_buckets=minimum_time_buckets,
    )

    manifest = CompositeValidationManifest(
        warning=COMPOSITE_VALIDATION_WARNING,
        created_at=utc_now(),
        creation_commit=current_git_commit(),
        source_campaign_ids=tuple(source_ids),
        instrument=instruments.pop(),
        venues=venues.pop(),
        quality_policy_version=quality_versions.pop(),
        quality_policy_sha256=quality_hashes.pop(),
        aggregate_accepted_session_count=accepted_count,
        aggregate_paired_overlap_seconds=accepted_overlap,
        aggregate_accepted_calendar_dates=aggregate_dates,
        aggregate_accepted_time_buckets=aggregate_buckets,
        minimum_accepted_sessions=minimum_accepted_sessions,
        minimum_total_accepted_overlap_seconds=minimum_total_accepted_overlap_seconds,
        minimum_calendar_dates=minimum_calendar_dates,
        minimum_time_buckets=minimum_time_buckets,
        sources=tuple(sources),
        accepted_attempts=tuple(accepted_entries),
    )
    manifest = manifest.model_copy(update={"content_hash": model_sha256(manifest)})
    atomic_write_json(output_path, manifest.model_dump(mode="json"))
    return manifest, output_path


def _accepted_attempt_entry(
    campaign_id: str,
    attempt: AttemptSummary,
) -> CompositeValidationAttemptReference:
    if attempt.inclusion_status != InclusionStatus.INCLUDED:
        raise CampaignValidationError("included composite attempt was not marked INCLUDED")
    return CompositeValidationAttemptReference(
        source_campaign_id=campaign_id,
        source_campaign_role="MULTI_DAY_VALIDATION",
        slot_id=attempt.slot_id,
        campaign_attempt_id=attempt.campaign_attempt_id,
        planned_start_utc=attempt.planned_start_utc,
        planned_start_local=attempt.planned_start_local,
        actual_start_utc=attempt.actual_started_at or attempt.planned_start_utc,
        time_bucket=attempt.time_bucket.value,
        attempt_runtime_commit=attempt.attempt_runtime_git_commit or "",
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


def _require_aggregate_thresholds(
    *,
    accepted_count: int,
    accepted_overlap: float,
    accepted_dates: int,
    accepted_buckets: int,
    minimum_accepted_sessions: int,
    minimum_total_accepted_overlap_seconds: float,
    minimum_calendar_dates: int,
    minimum_time_buckets: int,
) -> None:
    errors: list[str] = []
    if accepted_count < minimum_accepted_sessions:
        errors.append(
            f"accepted sessions {accepted_count} below required {minimum_accepted_sessions}"
        )
    if accepted_overlap < minimum_total_accepted_overlap_seconds:
        errors.append(
            "accepted overlap "
            f"{accepted_overlap:g} below required {minimum_total_accepted_overlap_seconds:g}"
        )
    if accepted_dates < minimum_calendar_dates:
        errors.append(f"accepted dates {accepted_dates} below required {minimum_calendar_dates}")
    if accepted_buckets < minimum_time_buckets:
        errors.append(f"accepted buckets {accepted_buckets} below required {minimum_time_buckets}")
    if errors:
        raise CampaignValidationError("; ".join(errors))
