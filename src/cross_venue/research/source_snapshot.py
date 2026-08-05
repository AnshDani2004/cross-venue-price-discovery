"""Immutable source catalog and analysis snapshot construction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from cross_venue.campaigns.models import (
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    CampaignRegistry,
    CampaignRole,
    CompletionState,
    InclusionStatus,
    LedgerEvent,
    LedgerEventType,
    MissedReason,
    PlannedSlotState,
    SlotStatus,
)
from cross_venue.quality.models import (
    PairedQualityReport,
    QualityDisposition,
    ValidatedDatasetManifest,
)
from cross_venue.research.exceptions import (
    SnapshotPersistenceError,
    SnapshotValidationError,
    SourceCatalogError,
)
from cross_venue.schemas import Exchange

SOURCE_CATALOG_SCHEMA_VERSION = "3c-source-catalog.1"
SNAPSHOT_SCHEMA_VERSION = "3c-analysis-snapshot.1"
SNAPSHOT_VALIDATION_SCHEMA_VERSION = "3c-snapshot-validation.1"
DEFAULT_ANALYSIS_OUTPUT_ROOT = Path("data/analysis")
DEFAULT_FINAL_MINIMUM_ACCEPTED_SESSIONS = 10
DEFAULT_FINAL_MINIMUM_OVERLAP_SECONDS = Decimal("18000")
DEFAULT_FINAL_MINIMUM_CALENDAR_DATES = 3
DEFAULT_FINAL_MINIMUM_TIME_BUCKETS = 3
GENESIS_PREVIOUS_HASH = "0" * 64
OVERLAP_QUANTUM = Decimal("0.000001")


class SourceSelectionConfig(BaseModel):
    """Stable source-selection rules for an analysis snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_selection_version: Literal["3c-source-selection.1"] = "3c-source-selection.1"
    campaign_ids: tuple[str, ...]
    required_campaign_role: Literal["MULTI_DAY_VALIDATION"] = "MULTI_DAY_VALIDATION"
    required_attempt_status: Literal["ACCEPTED"] = "ACCEPTED"
    required_inclusion_status: Literal["INCLUDED"] = "INCLUDED"
    required_paired_disposition: Literal["ACCEPTED"] = "ACCEPTED"
    required_venue_disposition: Literal["ACCEPTED"] = "ACCEPTED"
    required_quality_policy_version: str = "2d.2"
    final_minimum_accepted_sessions: int = DEFAULT_FINAL_MINIMUM_ACCEPTED_SESSIONS
    final_minimum_total_overlap_seconds: Decimal = DEFAULT_FINAL_MINIMUM_OVERLAP_SECONDS
    final_minimum_calendar_dates: int = DEFAULT_FINAL_MINIMUM_CALENDAR_DATES
    final_minimum_time_buckets: int = DEFAULT_FINAL_MINIMUM_TIME_BUCKETS

    @field_serializer("final_minimum_total_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)

    @field_validator("campaign_ids")
    @classmethod
    def campaign_ids_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one campaign ID is required")
        if len(value) != len(set(value)):
            raise ValueError("duplicate source campaign ID")
        return value


class AcceptedSourceAttemptEntry(BaseModel):
    """Lineage for one accepted source attempt included in a source catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    campaign_role: Literal["MULTI_DAY_VALIDATION"]
    campaign_attempt_id: str
    slot_id: str
    slot_type: str
    time_bucket: str
    planned_start_utc: datetime
    planned_start_local: str
    actual_started_at: datetime
    actual_completed_at: datetime
    paired_overlap_seconds: Decimal
    paired_collection_id: str
    validated_pair_manifest_id: str
    validated_pair_manifest_relative_path: str
    validated_pair_manifest_sha256: str
    coinbase_session_id: str
    kraken_session_id: str
    source_session_manifest_hashes: dict[str, str]
    session_quality_report_hashes: dict[str, str]
    paired_quality_report_hash: str
    source_raw_shard_checksums: dict[str, dict[str, str]]
    attempt_runtime_git_commit: str
    quality_code_git_commit: str
    quality_policy_version: str
    inclusion_status: Literal["INCLUDED"]
    attempt_status: Literal["ACCEPTED"]
    paired_disposition: Literal["ACCEPTED"]
    coinbase_disposition: Literal["ACCEPTED"]
    kraken_disposition: Literal["ACCEPTED"]
    analysis_calendar_date: str
    source_registry_sha256: str
    source_ledger_sha256: str
    source_ledger_terminal_event_hash: str
    validated_pair_manifest_content_hash: str | None = None
    raw_session_relative_paths: tuple[str, ...]
    session_quality_report_paths: tuple[str, ...]
    paired_quality_report_relative_path: str

    @field_serializer("paired_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)

    @field_validator("planned_start_utc", "actual_started_at", "actual_completed_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator(
        "source_session_manifest_hashes",
        "session_quality_report_hashes",
        "source_raw_shard_checksums",
    )
    @classmethod
    def lineage_maps_must_be_present(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("accepted source attempts require complete lineage maps")
        return value


class SourceCampaignEntry(BaseModel):
    """One source campaign represented in the analysis source catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: str
    campaign_role: Literal["MULTI_DAY_VALIDATION"]
    campaign_schema_version: str
    campaign_status: str
    completion_status: str
    instrument: str
    venues: tuple[Exchange, Exchange]
    runtime_git_commit: str
    quality_policy_version: str
    quality_policy_sha256: str
    campaign_config_path: str
    campaign_config_sha256: str
    source_registry_sha256: str
    source_ledger_sha256: str
    source_ledger_terminal_event_hash: str
    accepted_attempt_count: int = Field(ge=0)
    accepted_overlap_seconds: Decimal
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[str, ...]
    missed_slot_count: int = Field(ge=0)
    quarantined_attempt_count: int = Field(ge=0)
    rejected_attempt_count: int = Field(ge=0)
    failed_attempt_count: int = Field(ge=0)

    @field_serializer("accepted_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)


class AnalysisSourceCatalog(BaseModel):
    """Deterministic catalog of accepted source attempts for analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_catalog_schema_version: Literal["3c-source-catalog.1"]
    source_catalog_id: str
    created_at: datetime
    source_selection_config_hash: str
    source_selection: SourceSelectionConfig
    source_campaign_ids: tuple[str, ...]
    source_campaigns: tuple[SourceCampaignEntry, ...]
    accepted_attempt_count: int = Field(ge=0)
    aggregate_paired_overlap_seconds: Decimal
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[str, ...]
    accepted_attempts: tuple[AcceptedSourceAttemptEntry, ...]
    excluded_attempt_summary: tuple[dict[str, str], ...]
    missed_slot_summary: tuple[dict[str, str], ...]
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @field_serializer("aggregate_paired_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)


class DatasetAnalysisSnapshot(BaseModel):
    """Immutable seven-session analysis snapshot manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_schema_version: Literal["3c-analysis-snapshot.1"]
    snapshot_id: str
    snapshot_label: str
    created_at: datetime
    snapshot_generation_code_commit: str
    source_catalog_schema_version: str
    source_catalog_id: str
    source_catalog_hash: str
    source_selection_config_hash: str
    source_campaign_ids: tuple[str, ...]
    source_campaign_roles: tuple[str, ...]
    accepted_attempt_count: int = Field(ge=0)
    aggregate_paired_overlap_seconds: Decimal
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[str, ...]
    runtime_commits: tuple[str, ...]
    quality_policy_versions: tuple[str, ...]
    ordered_accepted_attempt_ids: tuple[str, ...]
    validated_pair_manifest_identities: tuple[dict[str, str], ...]
    source_registry_identities: tuple[dict[str, str], ...]
    source_ledger_identities: tuple[dict[str, str], ...]
    status: Literal["SOURCE_SNAPSHOT_VALID"]
    final_composite_status: Literal["FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED", "SATISFIED"]
    final_composite_requirements: dict[str, str | int]
    explicit_limitations: tuple[str, ...]
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @field_serializer("aggregate_paired_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)


class SnapshotValidationResult(BaseModel):
    """Machine-readable validation result for an analysis source snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_validation_schema_version: Literal["3c-snapshot-validation.1"]
    validated_at: datetime
    snapshot_id: str
    validation_status: Literal["VALID", "INVALID"]
    snapshot_status: str
    final_composite_status: str
    accepted_attempt_count: int
    aggregate_paired_overlap_seconds: Decimal
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[str, ...]
    deterministic_snapshot_id_verified: bool
    deterministic_source_catalog_id_verified: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @field_serializer("aggregate_paired_overlap_seconds")
    def serialize_decimal(self, value: Decimal) -> str:
        return canonical_decimal(value)


class SnapshotBuildResult(BaseModel):
    """Paths and manifests produced by a source snapshot build."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: bool
    snapshot_root: Path
    source_catalog_path: Path
    snapshot_manifest_path: Path
    snapshot_validation_path: Path
    source_catalog: AnalysisSourceCatalog
    snapshot: DatasetAnalysisSnapshot
    validation: SnapshotValidationResult

    def to_text(self) -> str:
        action = "created" if self.created else "already current"
        return "\n".join(
            [
                f"Analysis snapshot {action}: {self.snapshot.snapshot_id}",
                f"Snapshot root: {self.snapshot_root}",
                f"Accepted attempts: {self.snapshot.accepted_attempt_count}",
                (
                    "Aggregate overlap seconds: "
                    f"{canonical_decimal(self.snapshot.aggregate_paired_overlap_seconds)}"
                ),
                f"Snapshot status: {self.snapshot.status}",
                f"Final composite status: {self.snapshot.final_composite_status}",
                f"Validation: {self.validation.validation_status}",
            ]
        )


def build_analysis_source_snapshot(
    *,
    source_collection_root: Path,
    analysis_output_root: Path = DEFAULT_ANALYSIS_OUTPUT_ROOT,
    campaign_ids: tuple[str, ...],
    snapshot_label: str | None = None,
) -> SnapshotBuildResult:
    """Build a write-once source catalog and immutable analysis snapshot."""

    source_root = source_collection_root.resolve()
    if not source_root.exists():
        raise SourceCatalogError(f"source collection root does not exist: {source_root}")
    output_root = analysis_output_root.resolve()
    selection = SourceSelectionConfig(campaign_ids=tuple(campaign_ids))
    source_catalog = build_source_catalog(
        source_collection_root=source_root,
        selection=selection,
    )
    label = snapshot_label or (
        f"preliminary-{source_catalog.accepted_attempt_count}-session-multiday-analysis"
    )
    snapshot = build_snapshot_manifest(source_catalog, snapshot_label=label)
    snapshot_root = output_root / "snapshots" / snapshot.snapshot_id
    source_catalog_path = snapshot_root / "source_catalog.json"
    snapshot_manifest_path = snapshot_root / "snapshot_manifest.json"
    snapshot_validation_path = snapshot_root / "snapshot_validation.json"

    if snapshot_root.exists():
        existing_catalog = AnalysisSourceCatalog.model_validate_json(
            source_catalog_path.read_text(encoding="utf-8")
        )
        existing_snapshot = DatasetAnalysisSnapshot.model_validate_json(
            snapshot_manifest_path.read_text(encoding="utf-8")
        )
        if (
            existing_catalog.content_hash == source_catalog.content_hash
            and existing_snapshot.content_hash == snapshot.content_hash
        ):
            validation = validate_analysis_source_snapshot(
                snapshot_root=snapshot_root,
                source_collection_root=source_root,
            )
            return SnapshotBuildResult(
                created=False,
                snapshot_root=snapshot_root,
                source_catalog_path=source_catalog_path,
                snapshot_manifest_path=snapshot_manifest_path,
                snapshot_validation_path=snapshot_validation_path,
                source_catalog=existing_catalog,
                snapshot=existing_snapshot,
                validation=validation,
            )
        raise SnapshotPersistenceError("snapshot path already exists with different content")

    temporary_root = snapshot_root.with_name(f".{snapshot.snapshot_id}.tmp")
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    try:
        temporary_root.mkdir(parents=True)
        temporary_catalog_path = temporary_root / "source_catalog.json"
        temporary_snapshot_path = temporary_root / "snapshot_manifest.json"
        temporary_validation_path = temporary_root / "snapshot_validation.json"
        atomic_write_json(temporary_catalog_path, source_catalog.model_dump(mode="json"))
        atomic_write_json(temporary_snapshot_path, snapshot.model_dump(mode="json"))
        validation = validate_analysis_source_snapshot(
            snapshot_root=temporary_root,
            source_collection_root=source_root,
        )
        if validation.validation_status != "VALID":
            raise SnapshotValidationError("; ".join(validation.errors))
        atomic_write_json(temporary_validation_path, validation.model_dump(mode="json"))
        temporary_root.replace(snapshot_root)
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise
    validation = SnapshotValidationResult.model_validate_json(
        snapshot_validation_path.read_text(encoding="utf-8")
    )
    return SnapshotBuildResult(
        created=True,
        snapshot_root=snapshot_root,
        source_catalog_path=source_catalog_path,
        snapshot_manifest_path=snapshot_manifest_path,
        snapshot_validation_path=snapshot_validation_path,
        source_catalog=source_catalog,
        snapshot=snapshot,
        validation=validation,
    )


def build_source_catalog(
    *,
    source_collection_root: Path,
    selection: SourceSelectionConfig,
) -> AnalysisSourceCatalog:
    """Build a deterministic source catalog from read-only campaign state."""

    source_root = source_collection_root.resolve()
    selection_hash = semantic_hash(selection, exclude={"content_hash", "created_at"})
    source_campaigns: list[SourceCampaignEntry] = []
    accepted_attempts: list[AcceptedSourceAttemptEntry] = []
    excluded: list[dict[str, str]] = []
    missed: list[dict[str, str]] = []

    for campaign_id in selection.campaign_ids:
        config, config_path = load_source_campaign_config(source_root, campaign_id)
        registry, ledger_events = validate_source_registry_and_ledger(config)
        if registry.campaign_role != CampaignRole.MULTI_DAY_VALIDATION:
            raise SourceCatalogError(f"source campaign is not multi-day validation: {campaign_id}")
        if registry.quality_policy_version != selection.required_quality_policy_version:
            raise SourceCatalogError(
                f"source campaign has incompatible quality policy: {campaign_id}"
            )
        if registry.campaign_config_sha256 != sha256_file(config_path):
            raise SourceCatalogError(f"source campaign config hash mismatch: {campaign_id}")
        quality_policy_path = source_root / "configs" / "data_quality.toml"
        if quality_policy_path.exists() and registry.quality_policy_sha256 != sha256_file(
            quality_policy_path
        ):
            raise SourceCatalogError(f"source campaign quality policy hash mismatch: {campaign_id}")
        terminal_hash = ledger_events[-1].event_hash if ledger_events else GENESIS_PREVIOUS_HASH
        registry_sha = sha256_file(source_registry_path(source_root, campaign_id))
        ledger_file_sha = sha256_file(source_ledger_path(source_root, campaign_id))
        campaign_entry = SourceCampaignEntry(
            campaign_id=registry.campaign_id,
            campaign_role="MULTI_DAY_VALIDATION",
            campaign_schema_version=registry.campaign_schema_version,
            campaign_status=registry.campaign_status.value,
            completion_status=registry.completion_status.value,
            instrument=registry.instrument,
            venues=registry.venues,
            runtime_git_commit=registry.runtime_git_commit,
            quality_policy_version=registry.quality_policy_version,
            quality_policy_sha256=registry.quality_policy_sha256,
            campaign_config_path=portable_relative_to(source_root, config_path),
            campaign_config_sha256=registry.campaign_config_sha256,
            source_registry_sha256=registry_sha,
            source_ledger_sha256=ledger_file_sha,
            source_ledger_terminal_event_hash=terminal_hash,
            accepted_attempt_count=registry.accepted_attempt_count,
            accepted_overlap_seconds=sum_decimal(
                decimal_from_float_string(attempt.paired_overlap_seconds)
                for attempt in registry.attempts.values()
                if is_included_accepted(attempt)
            ),
            accepted_calendar_dates=tuple(registry.accepted_calendar_dates),
            accepted_time_buckets=tuple(bucket.value for bucket in registry.accepted_time_buckets),
            missed_slot_count=registry.missed_slot_count,
            quarantined_attempt_count=registry.quarantined_attempt_count,
            rejected_attempt_count=registry.rejected_attempt_count,
            failed_attempt_count=registry.failed_attempt_count,
        )
        source_campaigns.append(campaign_entry)
        for attempt in sorted(
            registry.attempts.values(),
            key=lambda item: (
                item.planned_start_utc.astimezone(UTC),
                item.slot_id,
                item.campaign_attempt_id,
            ),
        ):
            if is_included_accepted(attempt):
                accepted_attempts.append(
                    build_attempt_entry(
                        source_root=source_root,
                        config=config,
                        registry=registry,
                        attempt=attempt,
                        source_registry_sha256=registry_sha,
                        source_ledger_sha256=ledger_file_sha,
                        source_ledger_terminal_event_hash=terminal_hash,
                    )
                )
            elif attempt.attempt_status == AttemptStatus.ACCEPTED:
                raise SourceCatalogError(
                    "accepted attempt is excluded from research inclusion: "
                    f"{attempt.campaign_attempt_id}"
                )
            elif attempt.inclusion_status == InclusionStatus.EXCLUDED:
                excluded.append(
                    {
                        "campaign_id": registry.campaign_id,
                        "campaign_attempt_id": attempt.campaign_attempt_id,
                        "attempt_status": attempt.attempt_status.value,
                        "inclusion_status": attempt.inclusion_status.value,
                        "exclusion_reason": attempt.exclusion_reason or "",
                    }
                )
        for slot_id, state in sorted(registry.planned_slots.items()):
            if state.status == SlotStatus.MISSED:
                missed.append(
                    {
                        "campaign_id": registry.campaign_id,
                        "slot_id": slot_id,
                        "slot_type": state.slot.slot_type.value,
                        "time_bucket": state.slot.time_bucket.value,
                        "planned_start_utc": state.slot.planned_start_utc.isoformat(),
                        "missed_reason": state.missed_reason.value if state.missed_reason else "",
                    }
                )

    validate_attempt_membership(accepted_attempts)
    aggregate_overlap = sum_decimal(attempt.paired_overlap_seconds for attempt in accepted_attempts)
    dates = tuple(sorted({attempt.analysis_calendar_date for attempt in accepted_attempts}))
    buckets = tuple(sorted({attempt.time_bucket for attempt in accepted_attempts}))
    source_campaign_ids = tuple(campaign.campaign_id for campaign in source_campaigns)
    catalog_seed = {
        "source_catalog_schema_version": SOURCE_CATALOG_SCHEMA_VERSION,
        "source_selection_config_hash": selection_hash,
        "source_campaigns": [campaign.model_dump(mode="json") for campaign in source_campaigns],
        "accepted_attempts": [attempt.model_dump(mode="json") for attempt in accepted_attempts],
    }
    catalog_id = f"analysis-source-catalog-{sha256_json(catalog_seed)[:16]}"
    catalog = AnalysisSourceCatalog(
        source_catalog_schema_version="3c-source-catalog.1",
        source_catalog_id=catalog_id,
        created_at=datetime.now(UTC),
        source_selection_config_hash=selection_hash,
        source_selection=selection,
        source_campaign_ids=source_campaign_ids,
        source_campaigns=tuple(source_campaigns),
        accepted_attempt_count=len(accepted_attempts),
        aggregate_paired_overlap_seconds=aggregate_overlap,
        accepted_calendar_dates=dates,
        accepted_time_buckets=buckets,
        accepted_attempts=tuple(accepted_attempts),
        excluded_attempt_summary=tuple(excluded),
        missed_slot_summary=tuple(missed),
    )
    return catalog.model_copy(update={"content_hash": semantic_hash(catalog)})


def build_snapshot_manifest(
    source_catalog: AnalysisSourceCatalog,
    *,
    snapshot_label: str,
) -> DatasetAnalysisSnapshot:
    """Create a deterministic snapshot manifest from a source catalog."""

    final_requirements: dict[str, str | int] = {
        "minimum_accepted_sessions": DEFAULT_FINAL_MINIMUM_ACCEPTED_SESSIONS,
        "minimum_total_overlap_seconds": canonical_decimal(DEFAULT_FINAL_MINIMUM_OVERLAP_SECONDS),
        "minimum_calendar_dates": DEFAULT_FINAL_MINIMUM_CALENDAR_DATES,
        "minimum_time_buckets": DEFAULT_FINAL_MINIMUM_TIME_BUCKETS,
    }
    final_satisfied = (
        source_catalog.accepted_attempt_count >= DEFAULT_FINAL_MINIMUM_ACCEPTED_SESSIONS
        and source_catalog.aggregate_paired_overlap_seconds >= DEFAULT_FINAL_MINIMUM_OVERLAP_SECONDS
        and len(source_catalog.accepted_calendar_dates) >= DEFAULT_FINAL_MINIMUM_CALENDAR_DATES
        and len(source_catalog.accepted_time_buckets) >= DEFAULT_FINAL_MINIMUM_TIME_BUCKETS
    )
    snapshot_seed = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_label": snapshot_label,
        "source_catalog_id": source_catalog.source_catalog_id,
        "source_catalog_hash": source_catalog.content_hash,
        "source_selection_config_hash": source_catalog.source_selection_config_hash,
        "final_composite_requirements": final_requirements,
    }
    snapshot_hash_prefix = sha256_json(snapshot_seed)[:16]
    snapshot_id = (
        f"analysis-snapshot-{source_catalog.accepted_attempt_count}-session-v1-"
        f"{snapshot_hash_prefix}"
    )
    source_roles = tuple(
        sorted({campaign.campaign_role for campaign in source_catalog.source_campaigns})
    )
    runtime_commits = tuple(
        sorted({attempt.attempt_runtime_git_commit for attempt in source_catalog.accepted_attempts})
    )
    quality_versions = tuple(
        sorted({attempt.quality_policy_version for attempt in source_catalog.accepted_attempts})
    )
    snapshot = DatasetAnalysisSnapshot(
        snapshot_schema_version="3c-analysis-snapshot.1",
        snapshot_id=snapshot_id,
        snapshot_label=snapshot_label,
        created_at=datetime.now(UTC),
        snapshot_generation_code_commit=current_git_commit(),
        source_catalog_schema_version=source_catalog.source_catalog_schema_version,
        source_catalog_id=source_catalog.source_catalog_id,
        source_catalog_hash=source_catalog.content_hash or "",
        source_selection_config_hash=source_catalog.source_selection_config_hash,
        source_campaign_ids=source_catalog.source_campaign_ids,
        source_campaign_roles=source_roles,
        accepted_attempt_count=source_catalog.accepted_attempt_count,
        aggregate_paired_overlap_seconds=source_catalog.aggregate_paired_overlap_seconds,
        accepted_calendar_dates=source_catalog.accepted_calendar_dates,
        accepted_time_buckets=source_catalog.accepted_time_buckets,
        runtime_commits=runtime_commits,
        quality_policy_versions=quality_versions,
        ordered_accepted_attempt_ids=tuple(
            attempt.campaign_attempt_id for attempt in source_catalog.accepted_attempts
        ),
        validated_pair_manifest_identities=tuple(
            {
                "campaign_attempt_id": attempt.campaign_attempt_id,
                "validated_pair_manifest_id": attempt.validated_pair_manifest_id,
                "validated_pair_manifest_relative_path": (
                    attempt.validated_pair_manifest_relative_path
                ),
                "validated_pair_manifest_sha256": attempt.validated_pair_manifest_sha256,
            }
            for attempt in source_catalog.accepted_attempts
        ),
        source_registry_identities=tuple(
            {
                "campaign_id": campaign.campaign_id,
                "source_registry_sha256": campaign.source_registry_sha256,
            }
            for campaign in source_catalog.source_campaigns
        ),
        source_ledger_identities=tuple(
            {
                "campaign_id": campaign.campaign_id,
                "source_ledger_sha256": campaign.source_ledger_sha256,
                "source_ledger_terminal_event_hash": (campaign.source_ledger_terminal_event_hash),
            }
            for campaign in source_catalog.source_campaigns
        ),
        status="SOURCE_SNAPSHOT_VALID",
        final_composite_status=(
            "SATISFIED" if final_satisfied else "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
        ),
        final_composite_requirements=final_requirements,
        explicit_limitations=(
            "Valid for preliminary multi-day analysis only.",
            "Does not satisfy the final 10-session / 18000-second composite target.",
            "Excludes quarantined attempt P08 and all missed slots.",
        ),
    )
    return snapshot.model_copy(update={"content_hash": semantic_hash(snapshot)})


def validate_analysis_source_snapshot(
    *,
    snapshot_root: Path,
    source_collection_root: Path | None = None,
) -> SnapshotValidationResult:
    """Validate a persisted source catalog and snapshot manifest."""

    errors: list[str] = []
    warnings: list[str] = []
    catalog_path = snapshot_root / "source_catalog.json"
    snapshot_path = snapshot_root / "snapshot_manifest.json"
    try:
        catalog = AnalysisSourceCatalog.model_validate_json(
            catalog_path.read_text(encoding="utf-8")
        )
        snapshot = DatasetAnalysisSnapshot.model_validate_json(
            snapshot_path.read_text(encoding="utf-8")
        )
        if semantic_hash(catalog) != catalog.content_hash:
            errors.append("source catalog content hash mismatch")
        if semantic_hash(snapshot) != snapshot.content_hash:
            errors.append("snapshot content hash mismatch")
        expected_catalog = catalog.model_copy(
            update={"source_catalog_id": recompute_source_catalog_id(catalog)}
        )
        if expected_catalog.source_catalog_id != catalog.source_catalog_id:
            errors.append("source catalog ID is not deterministic")
        expected_snapshot_id = recompute_snapshot_id(snapshot)
        if expected_snapshot_id != snapshot.snapshot_id:
            errors.append("snapshot ID is not deterministic")
        if snapshot.source_catalog_hash != catalog.content_hash:
            errors.append("snapshot source catalog hash does not match catalog")
        if snapshot.accepted_attempt_count != catalog.accepted_attempt_count:
            errors.append("snapshot accepted attempt count does not match catalog")
        if snapshot.aggregate_paired_overlap_seconds != catalog.aggregate_paired_overlap_seconds:
            errors.append("snapshot aggregate overlap does not match catalog")
        validate_attempt_membership(list(catalog.accepted_attempts))
        if source_collection_root is not None:
            rebuilt = build_source_catalog(
                source_collection_root=source_collection_root,
                selection=catalog.source_selection,
            )
            if rebuilt.content_hash != catalog.content_hash:
                errors.append("source catalog no longer matches source collection root")
    except Exception as exc:
        errors.append(str(exc))
        catalog = None
        snapshot = None
    validation_status: Literal["VALID", "INVALID"] = "VALID" if not errors else "INVALID"
    return SnapshotValidationResult(
        snapshot_validation_schema_version="3c-snapshot-validation.1",
        validated_at=datetime.now(UTC),
        snapshot_id=snapshot.snapshot_id if snapshot else snapshot_root.name,
        validation_status=validation_status,
        snapshot_status=snapshot.status if snapshot else "UNKNOWN",
        final_composite_status=snapshot.final_composite_status if snapshot else "UNKNOWN",
        accepted_attempt_count=snapshot.accepted_attempt_count if snapshot else 0,
        aggregate_paired_overlap_seconds=(
            snapshot.aggregate_paired_overlap_seconds if snapshot else Decimal("0")
        ),
        accepted_calendar_dates=snapshot.accepted_calendar_dates if snapshot else (),
        accepted_time_buckets=snapshot.accepted_time_buckets if snapshot else (),
        deterministic_snapshot_id_verified=not any(
            "snapshot ID is not deterministic" in error for error in errors
        ),
        deterministic_source_catalog_id_verified=not any(
            "source catalog ID is not deterministic" in error for error in errors
        ),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def snapshot_status(snapshot_root: Path) -> dict[str, Any]:
    """Return a compact status payload for an existing snapshot root."""

    snapshot = DatasetAnalysisSnapshot.model_validate_json(
        (snapshot_root / "snapshot_manifest.json").read_text(encoding="utf-8")
    )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_label": snapshot.snapshot_label,
        "status": snapshot.status,
        "final_composite_status": snapshot.final_composite_status,
        "accepted_attempt_count": snapshot.accepted_attempt_count,
        "aggregate_paired_overlap_seconds": canonical_decimal(
            snapshot.aggregate_paired_overlap_seconds
        ),
        "accepted_calendar_dates": list(snapshot.accepted_calendar_dates),
        "accepted_time_buckets": list(snapshot.accepted_time_buckets),
        "source_campaign_ids": list(snapshot.source_campaign_ids),
        "snapshot_manifest_path": str(snapshot_root / "snapshot_manifest.json"),
    }


def build_attempt_entry(
    *,
    source_root: Path,
    config: CampaignConfig,
    registry: CampaignRegistry,
    attempt: AttemptSummary,
    source_registry_sha256: str,
    source_ledger_sha256: str,
    source_ledger_terminal_event_hash: str,
) -> AcceptedSourceAttemptEntry:
    """Build and validate one accepted source-attempt entry."""

    require_attempt_lineage(attempt)
    pair_path = config.validated_manifest_root / (attempt.validated_pair_manifest_path or "")
    if not pair_path.exists():
        raise SourceCatalogError(
            f"missing validated-pair manifest: {attempt.validated_pair_manifest_path}"
        )
    manifest_sha = sha256_file(pair_path)
    if manifest_sha != attempt.validated_pair_manifest_sha256:
        raise SourceCatalogError(
            f"validated-pair manifest hash mismatch: {attempt.campaign_attempt_id}"
        )
    validated = ValidatedDatasetManifest.model_validate_json(pair_path.read_text(encoding="utf-8"))
    if validated.dataset_manifest_id != attempt.validated_pair_manifest_id:
        raise SourceCatalogError("validated-pair manifest ID does not match attempt")
    if tuple(validated.paired_collection_ids) != (attempt.paired_collection_id,):
        raise SourceCatalogError("validated-pair manifest paired collection does not match attempt")
    expected_sessions = {attempt.coinbase_session_id, attempt.kraken_session_id}
    if set(validated.session_ids) != expected_sessions:
        raise SourceCatalogError("validated-pair manifest sessions do not match attempt")
    if validated.quality_policy_version != registry.quality_policy_version:
        raise SourceCatalogError("validated-pair manifest quality policy mismatch")
    if validated.raw_manifest_hashes != attempt.source_session_manifest_hashes:
        raise SourceCatalogError("source session manifest hashes do not match attempt")
    if validated.session_quality_report_hashes != attempt.session_quality_report_hashes:
        raise SourceCatalogError("session quality report hashes do not match attempt")
    paired_path = source_root / "data" / "quality" / validated.cross_venue_overlap_report_path
    if not paired_path.exists():
        raise SourceCatalogError("paired quality report is missing")
    paired_report = PairedQualityReport.model_validate_json(paired_path.read_text(encoding="utf-8"))
    if paired_report.disposition != QualityDisposition.ACCEPTED:
        raise SourceCatalogError("paired quality report is not accepted")
    if paired_report.paired_collection_id != attempt.paired_collection_id:
        raise SourceCatalogError("paired quality report ID does not match attempt")
    if paired_report.coinbase_report.disposition != QualityDisposition.ACCEPTED:
        raise SourceCatalogError("Coinbase quality report is not accepted")
    if paired_report.kraken_report.disposition != QualityDisposition.ACCEPTED:
        raise SourceCatalogError("Kraken quality report is not accepted")
    if paired_report.quality_policy_version != registry.quality_policy_version:
        raise SourceCatalogError("paired quality policy does not match registry")
    expected_pair_hash = attempt.paired_quality_report_hash or ""
    if expected_pair_hash != model_hash(paired_report):
        raise SourceCatalogError("paired quality report hash does not match attempt")
    for relative_path in validated.raw_session_relative_paths:
        session_root = source_root / "data" / "raw" / relative_path
        if not session_root.exists():
            raise SourceCatalogError(f"raw session path is missing: {relative_path}")
    for relative_path in validated.session_quality_report_paths:
        report_path = source_root / "data" / "quality" / relative_path
        if not report_path.exists():
            raise SourceCatalogError(f"session quality report is missing: {relative_path}")
    overlap = decimal_from_float_string(attempt.paired_overlap_seconds)
    actual_started_at = attempt.actual_started_at
    actual_completed_at = attempt.actual_completed_at
    if actual_started_at is None or actual_completed_at is None:
        raise SourceCatalogError("accepted attempt missing actual timestamps")
    return AcceptedSourceAttemptEntry(
        campaign_id=attempt.campaign_id,
        campaign_role="MULTI_DAY_VALIDATION",
        campaign_attempt_id=attempt.campaign_attempt_id,
        slot_id=attempt.slot_id,
        slot_type=attempt.slot_type.value,
        time_bucket=attempt.time_bucket.value,
        planned_start_utc=attempt.planned_start_utc,
        planned_start_local=attempt.planned_start_local,
        actual_started_at=actual_started_at,
        actual_completed_at=actual_completed_at,
        paired_overlap_seconds=overlap,
        paired_collection_id=attempt.paired_collection_id or "",
        validated_pair_manifest_id=attempt.validated_pair_manifest_id or "",
        validated_pair_manifest_relative_path=attempt.validated_pair_manifest_path or "",
        validated_pair_manifest_sha256=attempt.validated_pair_manifest_sha256 or "",
        coinbase_session_id=attempt.coinbase_session_id or "",
        kraken_session_id=attempt.kraken_session_id or "",
        source_session_manifest_hashes=dict(attempt.source_session_manifest_hashes),
        session_quality_report_hashes=dict(attempt.session_quality_report_hashes),
        paired_quality_report_hash=attempt.paired_quality_report_hash or "",
        source_raw_shard_checksums=dict(attempt.source_raw_shard_checksums),
        attempt_runtime_git_commit=attempt.attempt_runtime_git_commit or "",
        quality_code_git_commit=paired_report.quality_code_git_commit,
        quality_policy_version=registry.quality_policy_version,
        inclusion_status=cast(Literal["INCLUDED"], attempt.inclusion_status.value),
        attempt_status=cast(Literal["ACCEPTED"], attempt.attempt_status.value),
        paired_disposition=cast(Literal["ACCEPTED"], attempt.paired_disposition or ""),
        coinbase_disposition=cast(Literal["ACCEPTED"], attempt.coinbase_disposition or ""),
        kraken_disposition=cast(Literal["ACCEPTED"], attempt.kraken_disposition or ""),
        analysis_calendar_date=attempt.planned_start_local.split(" ")[0],
        source_registry_sha256=source_registry_sha256,
        source_ledger_sha256=source_ledger_sha256,
        source_ledger_terminal_event_hash=source_ledger_terminal_event_hash,
        validated_pair_manifest_content_hash=validated.content_sha256,
        raw_session_relative_paths=tuple(validated.raw_session_relative_paths),
        session_quality_report_paths=tuple(validated.session_quality_report_paths),
        paired_quality_report_relative_path=validated.cross_venue_overlap_report_path,
    )


def require_attempt_lineage(attempt: AttemptSummary) -> None:
    """Require complete accepted-attempt lineage before catalog inclusion."""

    if attempt.attempt_status != AttemptStatus.ACCEPTED:
        raise SourceCatalogError("attempt is not accepted")
    if attempt.inclusion_status != InclusionStatus.INCLUDED:
        raise SourceCatalogError("accepted attempt is not included")
    required = {
        "paired_collection_id": attempt.paired_collection_id,
        "validated_pair_manifest_id": attempt.validated_pair_manifest_id,
        "validated_pair_manifest_path": attempt.validated_pair_manifest_path,
        "validated_pair_manifest_sha256": attempt.validated_pair_manifest_sha256,
        "coinbase_session_id": attempt.coinbase_session_id,
        "kraken_session_id": attempt.kraken_session_id,
        "paired_quality_report_hash": attempt.paired_quality_report_hash,
        "attempt_runtime_git_commit": attempt.attempt_runtime_git_commit,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SourceCatalogError(f"accepted attempt missing required lineage: {missing}")
    if attempt.actual_started_at is None or attempt.actual_completed_at is None:
        raise SourceCatalogError("accepted attempt missing actual timestamps")
    if attempt.paired_disposition != "ACCEPTED":
        raise SourceCatalogError("accepted attempt paired disposition is not accepted")
    if attempt.coinbase_disposition != "ACCEPTED" or attempt.kraken_disposition != "ACCEPTED":
        raise SourceCatalogError("accepted attempt venue disposition is not accepted")
    if not attempt.source_session_manifest_hashes:
        raise SourceCatalogError("accepted attempt missing source session manifest hashes")
    if not attempt.source_raw_shard_checksums:
        raise SourceCatalogError("accepted attempt missing raw shard checksum lineage")
    if not attempt.session_quality_report_hashes:
        raise SourceCatalogError("accepted attempt missing session quality report hashes")


def validate_attempt_membership(attempts: list[AcceptedSourceAttemptEntry]) -> None:
    """Validate deterministic membership and duplicate constraints."""

    attempt_ids = [attempt.campaign_attempt_id for attempt in attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise SourceCatalogError("duplicate campaign attempt identity")
    manifest_ids = [attempt.validated_pair_manifest_id for attempt in attempts]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise SourceCatalogError("duplicate validated-pair manifest identity")
    ordered = sorted(
        attempts,
        key=lambda item: (
            item.planned_start_utc.astimezone(UTC),
            item.slot_id,
            item.campaign_attempt_id,
        ),
    )
    if tuple(attempts) != tuple(ordered):
        raise SourceCatalogError("accepted source attempts are not deterministically ordered")
    for attempt in attempts:
        if attempt.attempt_status != "ACCEPTED" or attempt.inclusion_status != "INCLUDED":
            raise SourceCatalogError("source catalog includes a non-included accepted attempt")
        if attempt.paired_disposition != "ACCEPTED":
            raise SourceCatalogError("source catalog includes non-accepted paired disposition")


def load_source_campaign_config(
    source_root: Path,
    campaign_id: str,
) -> tuple[CampaignConfig, Path]:
    """Load one source campaign config with roots resolved under the source checkout."""

    registry_payload = json.loads(source_registry_path(source_root, campaign_id).read_text())
    config_path = source_root / str(registry_payload["campaign_config_path"])
    if not config_path.exists():
        raise SourceCatalogError(f"campaign config missing: {config_path}")
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    config = CampaignConfig.model_validate(payload)
    if config.campaign_id != campaign_id:
        raise SourceCatalogError("campaign config ID does not match requested campaign")
    resolved_payload = config.model_dump(mode="python")
    resolved_payload.update(
        {
            "registry_root": resolve_source_path(source_root, config.registry_root),
            "validated_manifest_root": resolve_source_path(
                source_root, config.validated_manifest_root
            ),
            "normalized_output_root": resolve_source_path(
                source_root, config.normalized_output_root
            ),
        }
    )
    return CampaignConfig.model_validate(resolved_payload), config_path


def validate_source_registry_and_ledger(
    config: CampaignConfig,
) -> tuple[CampaignRegistry, list[LedgerEvent]]:
    """Validate hash-chain integrity and registry/ledger agreement without writes."""

    registry = CampaignRegistry.model_validate_json(
        campaign_registry_path(config).read_text(encoding="utf-8")
    )
    events = read_source_ledger(campaign_ledger_path(config))
    rebuilt = rebuild_registry_from_events(events)
    if _registry_comparable(rebuilt) != _registry_comparable(registry):
        raise SourceCatalogError("registry does not match ledger reconstruction")
    actual_ledger_sha = sha256_file(campaign_ledger_path(config))
    if registry.ledger_sha256 != actual_ledger_sha:
        raise SourceCatalogError("registry ledger hash does not match ledger file")
    return registry, events


def rebuild_registry_from_events(events: list[LedgerEvent]) -> CampaignRegistry:
    """Rebuild campaign state required for source validation from ledger events."""

    if not events or events[0].event_type != LedgerEventType.CAMPAIGN_INITIALIZED:
        raise SourceCatalogError("campaign ledger missing initialization event")
    registry = CampaignRegistry.model_validate(events[0].payload["registry"])
    planned_slots: dict[str, PlannedSlotState] = dict(registry.planned_slots)
    attempts: dict[str, AttemptSummary] = {}
    for event in events[1:]:
        if event.event_type == LedgerEventType.SLOT_MARKED_MISSED:
            slot_id = require_slot_id(event)
            state = planned_slots[slot_id]
            planned_slots[slot_id] = state.model_copy(
                update={
                    "status": SlotStatus.MISSED,
                    "missed_reason": MissedReason(event.payload["reason"]),
                }
            )
        elif event.event_type == LedgerEventType.ATTEMPT_STARTED:
            attempt = AttemptSummary.model_validate(event.payload["attempt"])
            attempts[attempt.campaign_attempt_id] = attempt
            state = planned_slots[attempt.slot_id]
            planned_slots[attempt.slot_id] = state.model_copy(
                update={
                    "status": SlotStatus.RUNNING,
                    "attempts": (*state.attempts, attempt.campaign_attempt_id),
                }
            )
        elif event.event_type in {
            LedgerEventType.ATTEMPT_ACCEPTED,
            LedgerEventType.ATTEMPT_QUARANTINED,
            LedgerEventType.ATTEMPT_REJECTED,
            LedgerEventType.ATTEMPT_FAILED,
            LedgerEventType.ATTEMPT_ABORTED,
        }:
            attempt = AttemptSummary.model_validate(event.payload["attempt"])
            attempts[attempt.campaign_attempt_id] = attempt
            state = planned_slots[attempt.slot_id]
            planned_slots[attempt.slot_id] = state.model_copy(
                update={"status": SlotStatus(attempt.attempt_status.value)}
            )
        elif event.event_type in {
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS,
        }:
            registry = registry.model_copy(
                update={
                    "runtime_git_commit": event.payload["new_runtime_commit"],
                    "runtime_working_tree_clean": event.payload["runtime_working_tree_clean"],
                }
            )
    counts = Counter(attempt.attempt_status for attempt in attempts.values())
    included_accepted = [
        attempt
        for attempt in attempts.values()
        if attempt.attempt_status == AttemptStatus.ACCEPTED
        and attempt.inclusion_status == InclusionStatus.INCLUDED
    ]
    accepted_dates = tuple(
        sorted({attempt.planned_start_local.split(" ")[0] for attempt in included_accepted})
    )
    accepted_buckets = tuple(sorted({attempt.time_bucket for attempt in included_accepted}))
    completion_requirements = registry.completion_requirements.model_copy(
        update={
            "accepted_sessions": len(included_accepted) >= registry.minimum_accepted_sessions,
            "accepted_overlap_seconds": (
                sum(attempt.paired_overlap_seconds for attempt in included_accepted)
                >= registry.minimum_total_accepted_overlap_seconds
            ),
            "calendar_dates": len(accepted_dates) >= registry.minimum_calendar_dates,
            "time_buckets": len(accepted_buckets) >= registry.minimum_time_buckets,
            "attempts_registered": (
                len(attempts)
                + sum(1 for state in planned_slots.values() if state.status == SlotStatus.MISSED)
                >= registry.maximum_attempts
            ),
            "registry_and_ledger_valid": True,
        }
    )
    completion_status = (
        CompletionState.SATISFIED
        if completion_requirements.satisfied
        else CompletionState.UNSATISFIED
    )
    return registry.model_copy(
        update={
            "planned_slots": planned_slots,
            "attempts": attempts,
            "accepted_attempt_count": len(included_accepted),
            "quarantined_attempt_count": counts[AttemptStatus.QUARANTINED],
            "rejected_attempt_count": counts[AttemptStatus.REJECTED],
            "failed_attempt_count": counts[AttemptStatus.FAILED],
            "missed_slot_count": sum(
                1 for state in planned_slots.values() if state.status == SlotStatus.MISSED
            ),
            "accepted_overlap_seconds": float(
                sum_decimal(
                    decimal_from_float_string(attempt.paired_overlap_seconds)
                    for attempt in included_accepted
                )
            ),
            "accepted_calendar_dates": accepted_dates,
            "accepted_time_buckets": accepted_buckets,
            "completion_requirements": completion_requirements,
            "completion_status": completion_status,
        }
    )


def read_source_ledger(path: Path) -> list[LedgerEvent]:
    """Read and validate a campaign ledger hash chain."""

    events = [
        LedgerEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    previous = GENESIS_PREVIOUS_HASH
    for index, event in enumerate(events):
        if event.event_index != index:
            raise SourceCatalogError("ledger event index mismatch")
        if event.previous_event_hash != previous:
            raise SourceCatalogError("ledger previous hash mismatch")
        if compute_event_hash(event) != event.event_hash:
            raise SourceCatalogError("ledger event hash mismatch")
        previous = event.event_hash
    return events


def is_included_accepted(attempt: AttemptSummary) -> bool:
    return (
        attempt.attempt_status == AttemptStatus.ACCEPTED
        and attempt.inclusion_status == InclusionStatus.INCLUDED
    )


def recompute_source_catalog_id(catalog: AnalysisSourceCatalog) -> str:
    seed = {
        "source_catalog_schema_version": catalog.source_catalog_schema_version,
        "source_selection_config_hash": catalog.source_selection_config_hash,
        "source_campaigns": [
            campaign.model_dump(mode="json") for campaign in catalog.source_campaigns
        ],
        "accepted_attempts": [
            attempt.model_dump(mode="json") for attempt in catalog.accepted_attempts
        ],
    }
    return f"analysis-source-catalog-{sha256_json(seed)[:16]}"


def recompute_snapshot_id(snapshot: DatasetAnalysisSnapshot) -> str:
    seed = {
        "snapshot_schema_version": snapshot.snapshot_schema_version,
        "snapshot_label": snapshot.snapshot_label,
        "source_catalog_id": snapshot.source_catalog_id,
        "source_catalog_hash": snapshot.source_catalog_hash,
        "source_selection_config_hash": snapshot.source_selection_config_hash,
        "final_composite_requirements": snapshot.final_composite_requirements,
    }
    return (
        f"analysis-snapshot-{snapshot.accepted_attempt_count}-session-v1-{sha256_json(seed)[:16]}"
    )


def _registry_comparable(registry: CampaignRegistry) -> dict[str, Any]:
    data = registry.model_dump(mode="json")
    data.pop("updated_at", None)
    data.pop("ledger_sha256", None)
    return data


def require_slot_id(event: LedgerEvent) -> str:
    if event.slot_id is None:
        raise SourceCatalogError("ledger event missing slot ID")
    return event.slot_id


def source_registry_path(source_root: Path, campaign_id: str) -> Path:
    return (
        source_root
        / "data"
        / "campaigns"
        / f"campaign={campaign_id}"
        / "registry"
        / "campaign_registry.json"
    )


def source_ledger_path(source_root: Path, campaign_id: str) -> Path:
    return (
        source_root
        / "data"
        / "campaigns"
        / f"campaign={campaign_id}"
        / "ledger"
        / "campaign_events.jsonl"
    )


def campaign_registry_path(config: CampaignConfig) -> Path:
    return (
        config.registry_root
        / f"campaign={config.campaign_id}"
        / "registry"
        / "campaign_registry.json"
    )


def campaign_ledger_path(config: CampaignConfig) -> Path:
    return (
        config.registry_root / f"campaign={config.campaign_id}" / "ledger" / "campaign_events.jsonl"
    )


def resolve_source_path(source_root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else source_root / path
    resolved_root = source_root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SourceCatalogError("source path escapes collection root") from exc
    return resolved_candidate


def portable_relative_to(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    return resolved_path.relative_to(resolved_root).as_posix()


def validate_relative_path(value: str) -> None:
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise SourceCatalogError("source artifact path must be relative")


def decimal_from_float_string(value: float | Decimal | str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(OVERLAP_QUANTUM)
    except InvalidOperation as exc:
        raise SourceCatalogError(f"invalid decimal overlap value: {value}") from exc


def sum_decimal(values: Any) -> Decimal:
    total = Decimal("0.000000")
    for value in values:
        total += decimal_from_float_string(value)
    return total.quantize(OVERLAP_QUANTUM)


def canonical_decimal(value: Decimal) -> str:
    return format(value.quantize(OVERLAP_QUANTUM), "f")


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    def default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, Decimal):
            return canonical_decimal(item)
        return str(item)

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def model_hash(model: BaseModel) -> str:
    return sha256_json(model.model_dump(mode="json"))


def semantic_hash(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    excluded = {
        "content_hash",
        "created_at",
        "validated_at",
        "snapshot_generation_code_commit",
    } | (exclude or set())
    return sha256_json(model.model_dump(mode="json", exclude=excluded))


def compute_event_hash(event: LedgerEvent) -> str:
    payload = event.model_dump(mode="json")
    payload.pop("event_hash", None)
    return sha256_json(payload)


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        fsync_parent(path.parent)
    except OSError as exc:
        raise SnapshotPersistenceError(f"could not write JSON artifact: {path}") from exc


def fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
