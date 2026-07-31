"""Typed Phase 3B campaign contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from cross_venue.runtime_limits import (
    MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE,
)
from cross_venue.schemas import Exchange

CAMPAIGN_SCHEMA_VERSION = "3b.2"
LEGACY_CAMPAIGN_SCHEMA_VERSION = "3b.1"
DEFAULT_PHASE_3B_CAMPAIGN_ID = "btc-usd-coinbase-kraken-2026-07-31-v1"
CAMPAIGN_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{1,126}[a-z0-9])?$"
CampaignId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=CAMPAIGN_ID_PATTERN),
]
_CAMPAIGN_ID_ADAPTER = TypeAdapter(CampaignId)


def validate_campaign_id(value: str) -> CampaignId:
    """Validate a campaign ID without normalizing it."""

    return _CAMPAIGN_ID_ADAPTER.validate_python(value)


class CampaignStatus(StrEnum):
    """Lifecycle status for the overall campaign."""

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class SlotStatus(StrEnum):
    """Lifecycle status for a planned slot."""

    PLANNED = "PLANNED"
    DUE = "DUE"
    RUNNING = "RUNNING"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    MISSED = "MISSED"
    NOT_NEEDED = "NOT_NEEDED"


class AttemptStatus(StrEnum):
    """Lifecycle status for one attempt."""

    STARTED = "STARTED"
    COLLECTION_COMPLETE = "COLLECTION_COMPLETE"
    QUALITY_COMPLETE = "QUALITY_COMPLETE"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class SlotType(StrEnum):
    """Whether a slot is primary or reserve."""

    PRIMARY = "PRIMARY"
    RESERVE = "RESERVE"


class TimeBucket(StrEnum):
    """Predeclared local time-of-day bucket."""

    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"
    EVENING = "EVENING"


class CampaignRole(StrEnum):
    """Research role for a collection campaign."""

    MULTI_DAY_VALIDATION = "MULTI_DAY_VALIDATION"
    EXPLORATORY_INTRADAY = "EXPLORATORY_INTRADAY"
    DEVELOPMENT_SMOKE = "DEVELOPMENT_SMOKE"


class RuntimeMigrationReason(StrEnum):
    """Allowed reasons for changing a campaign runtime before collection starts."""

    GENERIC_ENGINE_BEFORE_FIRST_COLLECTION = "GENERIC_ENGINE_BEFORE_FIRST_COLLECTION"
    LONG_DURATION_PREFLIGHT_FIX = "LONG_DURATION_PREFLIGHT_FIX"
    CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX = "CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX"
    COLLECTOR_INTERNAL_MESSAGE_LIMIT_FIX = "COLLECTOR_INTERNAL_MESSAGE_LIMIT_FIX"


class AttemptExclusionReason(StrEnum):
    """Typed reasons an attempt is excluded from campaign research inputs."""

    ATTEMPT_NOT_COMPLETE = "ATTEMPT_NOT_COMPLETE"
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    COLLECTION_PREFLIGHT_FAILED = "COLLECTION_PREFLIGHT_FAILED"
    ARCHIVE_VALIDATION_FAILED = "ARCHIVE_VALIDATION_FAILED"
    COINBASE_QUALITY_NOT_ACCEPTED = "COINBASE_QUALITY_NOT_ACCEPTED"
    KRAKEN_QUALITY_NOT_ACCEPTED = "KRAKEN_QUALITY_NOT_ACCEPTED"
    PAIRED_QUALITY_NOT_ACCEPTED = "PAIRED_QUALITY_NOT_ACCEPTED"
    PAIRED_QUALITY_QUARANTINED = "PAIRED_QUALITY_QUARANTINED"
    INSUFFICIENT_PAIRED_OVERLAP = "INSUFFICIENT_PAIRED_OVERLAP"
    PROMOTION_DRY_RUN_BLOCKED = "PROMOTION_DRY_RUN_BLOCKED"


class FailureClassification(StrEnum):
    """Bounded failure classes for campaign attempts."""

    NETWORK_CONNECTION_FAILURE = "NETWORK_CONNECTION_FAILURE"
    SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
    COLLECTOR_RUNTIME_FAILURE = "COLLECTOR_RUNTIME_FAILURE"
    WRITER_FAILURE = "WRITER_FAILURE"
    ARCHIVE_VALIDATION_FAILURE = "ARCHIVE_VALIDATION_FAILURE"
    CHECKSUM_FAILURE = "CHECKSUM_FAILURE"
    QUALITY_ANALYSIS_FAILURE = "QUALITY_ANALYSIS_FAILURE"
    PROMOTION_FAILURE = "PROMOTION_FAILURE"
    PROCESS_INTERRUPTED = "PROCESS_INTERRUPTED"
    RUNTIME_COMMIT_MISMATCH = "RUNTIME_COMMIT_MISMATCH"
    COLLECTION_PREFLIGHT_FAILURE = "COLLECTION_PREFLIGHT_FAILURE"
    OUTSIDE_SLOT_WINDOW = "OUTSIDE_SLOT_WINDOW"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class MissedReason(StrEnum):
    """Allowed reasons for marking a slot missed."""

    IMPLEMENTATION_NOT_READY = "IMPLEMENTATION_NOT_READY"
    USER_UNAVAILABLE = "USER_UNAVAILABLE"
    SYSTEM_UNAVAILABLE = "SYSTEM_UNAVAILABLE"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    SLOT_WINDOW_EXPIRED = "SLOT_WINDOW_EXPIRED"
    CAMPAIGN_ALREADY_COMPLETE = "CAMPAIGN_ALREADY_COMPLETE"
    CAMPAIGN_INITIALIZED_AFTER_SLOT_WINDOW = "CAMPAIGN_INITIALIZED_AFTER_SLOT_WINDOW"


class InclusionStatus(StrEnum):
    """Whether an attempt is included in campaign research inputs."""

    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class CompletionState(StrEnum):
    """Campaign completion evaluation result."""

    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"


class LedgerEventType(StrEnum):
    """Hash-chained append-only event types."""

    CAMPAIGN_INITIALIZED = "CAMPAIGN_INITIALIZED"
    SLOT_MARKED_DUE = "SLOT_MARKED_DUE"
    SLOT_MARKED_MISSED = "SLOT_MARKED_MISSED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    COLLECTION_COMPLETED = "COLLECTION_COMPLETED"
    ARCHIVE_VALIDATED = "ARCHIVE_VALIDATED"
    QUALITY_ANALYZED = "QUALITY_ANALYZED"
    PROMOTION_DRY_RUN_COMPLETED = "PROMOTION_DRY_RUN_COMPLETED"
    VALIDATED_PAIR_MANIFEST_CREATED = "VALIDATED_PAIR_MANIFEST_CREATED"
    ATTEMPT_ACCEPTED = "ATTEMPT_ACCEPTED"
    ATTEMPT_QUARANTINED = "ATTEMPT_QUARANTINED"
    ATTEMPT_REJECTED = "ATTEMPT_REJECTED"
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    ATTEMPT_ABORTED = "ATTEMPT_ABORTED"
    CAMPAIGN_RUNTIME_MIGRATED = "CAMPAIGN_RUNTIME_MIGRATED"
    CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE = (
        "CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE"
    )
    CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS = (
        "CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS"
    )
    CAMPAIGN_COMPLETION_EVALUATED = "CAMPAIGN_COMPLETION_EVALUATED"
    CAMPAIGN_FINALIZED = "CAMPAIGN_FINALIZED"


class CampaignSlot(BaseModel):
    """One fixed primary or reserve slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str = Field(min_length=2)
    slot_type: SlotType
    planned_start_utc: datetime
    planned_start_local: str = Field(min_length=1)
    time_bucket: TimeBucket

    @field_validator("planned_start_utc", mode="before")
    @classmethod
    def parse_utc_z(cls, value: Any) -> Any:
        if isinstance(value, str) and value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("planned_start_utc")
    @classmethod
    def start_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("planned_start_utc must be timezone-aware")
        normalized = value.astimezone(UTC)
        offset = normalized.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("planned_start_utc must be UTC")
        return normalized


class CampaignConfig(BaseModel):
    """Strict collection campaign configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_schema_version: Literal["3b.1", "3b.2"]
    campaign_id: CampaignId
    campaign_role: CampaignRole = CampaignRole.MULTI_DAY_VALIDATION
    instrument: Literal["BTC-USD"]
    venues: tuple[Exchange, Exchange]
    timezone: str
    quality_policy_version: Literal["2d.2"]
    normalization_schema_version: str = Field(min_length=1)
    runtime_git_commit: str | None = Field(default=None, min_length=7, max_length=64)
    requested_duration_seconds: int = Field(
        gt=0,
        le=MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    )
    minimum_overlap_seconds_per_accepted_session: int = Field(gt=0)
    minimum_accepted_sessions: int = Field(gt=0)
    minimum_total_accepted_overlap_seconds: int = Field(gt=0)
    minimum_calendar_dates: int = Field(gt=0)
    minimum_time_buckets: int = Field(gt=0)
    maximum_attempts: int = Field(gt=0)
    early_start_tolerance_seconds: int = Field(ge=0, le=1800)
    late_start_tolerance_seconds: int = Field(ge=0, le=3600)
    maximum_messages_per_venue: int = Field(
        gt=0,
        le=MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE,
    )
    registry_root: Path
    validated_manifest_root: Path
    normalized_output_root: Path
    require_clean_working_tree: bool
    require_frozen_runtime_commit: bool
    require_archive_validation: bool
    require_quality_acceptance: bool
    require_promotion_dry_run: bool
    preserve_all_attempts: bool
    slots: tuple[CampaignSlot, ...] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    @field_validator("venues", mode="before")
    @classmethod
    def venues_tuple(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("venues")
    @classmethod
    def venues_must_be_fixed(cls, value: tuple[Exchange, Exchange]) -> tuple[Exchange, Exchange]:
        if value != (Exchange.COINBASE, Exchange.KRAKEN):
            raise ValueError("campaign venues must be coinbase then kraken")
        return value

    @field_validator("registry_root", "validated_manifest_root", "normalized_output_root")
    @classmethod
    def roots_must_be_local(cls, value: Path) -> Path:
        text = str(value)
        if "://" in text:
            raise ValueError("campaign roots must be local filesystem paths")
        return value

    @model_validator(mode="after")
    def campaign_invariants(self) -> CampaignConfig:
        slot_ids = [slot.slot_id for slot in self.slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("duplicate campaign slot IDs")
        timestamps = [slot.planned_start_utc for slot in self.slots]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("duplicate campaign slot timestamps")
        if sorted(timestamps) != timestamps:
            raise ValueError("campaign slots must be deterministically sorted")
        primary_count = sum(slot.slot_type == SlotType.PRIMARY for slot in self.slots)
        if primary_count < 1:
            raise ValueError("campaign must contain at least one primary slot")
        total_slots = len(self.slots)
        if self.minimum_accepted_sessions > total_slots:
            raise ValueError("minimum accepted sessions cannot exceed total planned slots")
        if self.minimum_accepted_sessions > self.maximum_attempts:
            raise ValueError("minimum accepted sessions cannot exceed maximum attempts")
        if self.maximum_attempts != total_slots:
            raise ValueError("maximum attempts must equal total planned slots")
        if self.minimum_overlap_seconds_per_accepted_session > self.requested_duration_seconds:
            raise ValueError("minimum overlap cannot exceed requested duration")
        if self.minimum_time_buckets > len(TimeBucket):
            raise ValueError("minimum time bucket requirement is impossible")
        if not (
            self.require_clean_working_tree
            and self.require_frozen_runtime_commit
            and self.require_archive_validation
            and self.require_quality_acceptance
            and self.require_promotion_dry_run
            and self.preserve_all_attempts
        ):
            raise ValueError("campaign safety requirements cannot be disabled")
        if self.campaign_role == CampaignRole.DEVELOPMENT_SMOKE and (
            self.minimum_accepted_sessions > 1
            or self.minimum_calendar_dates > 1
            or self.minimum_time_buckets > 1
        ):
            raise ValueError("development smoke campaigns cannot satisfy research requirements")
        return self

    def slot_by_id(self, slot_id: str) -> CampaignSlot:
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        raise KeyError(slot_id)


class AttemptSummary(BaseModel):
    """Derived summary for one campaign attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: CampaignId
    slot_id: str
    attempt_number: int = Field(gt=0)
    campaign_attempt_id: str = Field(min_length=1)
    slot_type: SlotType
    planned_start_utc: datetime
    planned_start_local: str
    time_bucket: TimeBucket
    actual_started_at: datetime | None = None
    actual_completed_at: datetime | None = None
    requested_duration_seconds: int
    maximum_messages_per_venue: int | None = Field(
        default=None,
        ge=1,
    )
    attempt_runtime_git_commit: str | None = Field(default=None, min_length=7, max_length=64)
    actual_collection_duration_seconds: float | None = Field(default=None, ge=0)
    paired_overlap_seconds: float = Field(default=0, ge=0)
    paired_collection_id: str | None = None
    coinbase_session_id: str | None = None
    kraken_session_id: str | None = None
    coinbase_frame_count: int = Field(default=0, ge=0)
    kraken_frame_count: int = Field(default=0, ge=0)
    coinbase_effective_duration_limit_seconds: float | None = Field(default=None, gt=0)
    kraken_effective_duration_limit_seconds: float | None = Field(default=None, gt=0)
    coinbase_effective_message_limit: int | None = Field(default=None, gt=0)
    kraken_effective_message_limit: int | None = Field(default=None, gt=0)
    coinbase_stop_reason: str | None = None
    kraken_stop_reason: str | None = None
    coinbase_trade_count: int = Field(default=0, ge=0)
    kraken_trade_count: int = Field(default=0, ge=0)
    coinbase_bbo_count: int = Field(default=0, ge=0)
    kraken_bbo_count: int = Field(default=0, ge=0)
    coinbase_archive_valid: bool = False
    kraken_archive_valid: bool = False
    coinbase_disposition: str | None = None
    kraken_disposition: str | None = None
    paired_disposition: str | None = None
    promotion_dry_run_allowed: bool = False
    validated_pair_manifest_id: str | None = None
    validated_pair_manifest_path: str | None = None
    validated_pair_manifest_sha256: str | None = None
    source_session_manifest_hashes: dict[str, str] = {}
    source_raw_shard_checksums: dict[str, dict[str, str]] = {}
    session_quality_report_hashes: dict[str, str] = {}
    paired_quality_report_hash: str | None = None
    attempt_status: AttemptStatus
    failure_classification: FailureClassification | None = None
    failure_message: str | None = None
    inclusion_status: InclusionStatus = InclusionStatus.EXCLUDED
    exclusion_reason: str | None = None

    @field_validator("planned_start_utc", "actual_started_at", "actual_completed_at")
    @classmethod
    def attempt_timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        return value

    @field_validator("validated_pair_manifest_path")
    @classmethod
    def attempt_path_must_be_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _validate_relative_path(value)
        return value

    @field_validator("failure_message")
    @classmethod
    def failure_message_bounded(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            raise ValueError("failure message is too long")
        return value


class PlannedSlotState(BaseModel):
    """Current derived state for one planned slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: CampaignSlot
    status: SlotStatus = SlotStatus.PLANNED
    attempts: tuple[str, ...] = ()
    missed_reason: MissedReason | None = None


class CompletionRequirements(BaseModel):
    """Current requirement satisfaction flags."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_sessions: bool
    accepted_overlap_seconds: bool
    calendar_dates: bool
    time_buckets: bool
    policy_consistency: bool
    runtime_consistency: bool
    attempts_registered: bool
    registry_and_ledger_valid: bool

    @property
    def satisfied(self) -> bool:
        return all(self.model_dump().values())


class CampaignRegistry(BaseModel):
    """Derived current-state campaign registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_schema_version: str
    campaign_id: CampaignId
    campaign_role: CampaignRole = CampaignRole.MULTI_DAY_VALIDATION
    campaign_status: CampaignStatus
    campaign_config_path: str
    campaign_config_sha256: str
    quality_policy_version: str
    quality_policy_sha256: str
    runtime_git_commit: str
    runtime_working_tree_clean: bool
    created_at: datetime
    updated_at: datetime
    instrument: str
    venues: tuple[Exchange, Exchange]
    timezone: str
    requested_duration_seconds: int
    minimum_overlap_seconds_per_accepted_session: int
    minimum_accepted_sessions: int
    minimum_total_accepted_overlap_seconds: int
    minimum_calendar_dates: int
    minimum_time_buckets: int
    maximum_attempts: int
    planned_slots: dict[str, PlannedSlotState]
    attempts: dict[str, AttemptSummary]
    accepted_attempt_count: int = 0
    quarantined_attempt_count: int = 0
    rejected_attempt_count: int = 0
    failed_attempt_count: int = 0
    missed_slot_count: int = 0
    accepted_overlap_seconds: float = 0
    accepted_calendar_dates: tuple[str, ...] = ()
    accepted_time_buckets: tuple[TimeBucket, ...] = ()
    completion_requirements: CompletionRequirements
    completion_status: CompletionState
    ledger_sha256: str

    @field_validator("campaign_config_path")
    @classmethod
    def registry_path_must_be_relative(cls, value: str) -> str:
        _validate_relative_path(value)
        return value


class LedgerEvent(BaseModel):
    """One append-only hash-chained ledger event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_index: int = Field(ge=0)
    campaign_id: CampaignId
    event_type: LedgerEventType
    occurred_at: datetime
    slot_id: str | None = None
    campaign_attempt_id: str | None = None
    payload: dict[str, Any]
    previous_event_hash: str
    event_hash: str

    @field_validator("occurred_at")
    @classmethod
    def event_time_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("ledger event timestamp must be timezone-aware")
        return value


class CampaignLockRecord(BaseModel):
    """On-disk campaign lock."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: CampaignId
    slot_id: str
    campaign_attempt_id: str
    process_id: int
    started_at: datetime
    runtime_commit: str


class AcceptedPairManifestReference(BaseModel):
    """Accepted pair entry inside a validated campaign manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str
    campaign_attempt_id: str
    planned_start_utc: datetime
    actual_start_utc: datetime
    time_bucket: TimeBucket
    paired_collection_id: str
    validated_pair_manifest_id: str
    validated_pair_manifest_relative_path: str
    validated_pair_manifest_sha256: str
    paired_overlap_seconds: float
    coinbase_session_id: str
    kraken_session_id: str
    source_manifest_hashes: dict[str, str]
    source_shard_checksums: dict[str, dict[str, str]]
    quality_report_hashes: dict[str, str]

    @field_validator("validated_pair_manifest_relative_path")
    @classmethod
    def pair_manifest_path_relative(cls, value: str) -> str:
        _validate_relative_path(value)
        return value


class ValidatedCampaignManifest(BaseModel):
    """Immutable manifest for a completed multi-session campaign."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validated_campaign_manifest_version: str
    validated_campaign_manifest_id: str
    campaign_id: CampaignId
    campaign_role: CampaignRole = CampaignRole.MULTI_DAY_VALIDATION
    campaign_schema_version: str
    created_at: datetime
    campaign_runtime_commit: str
    finalization_commit: str
    campaign_config_sha256: str
    quality_policy_version: str
    quality_policy_sha256: str
    campaign_registry_sha256: str
    campaign_ledger_sha256: str
    instrument: str
    venues: tuple[Exchange, Exchange]
    timezone: str
    accepted_attempt_count: int
    accepted_overlap_seconds: float
    accepted_calendar_dates: tuple[str, ...]
    accepted_time_buckets: tuple[TimeBucket, ...]
    all_attempt_counts_by_status: dict[str, int]
    all_slot_counts_by_status: dict[str, int]
    accepted_pair_manifests: tuple[AcceptedPairManifestReference, ...]
    excluded_attempt_summary: tuple[dict[str, Any], ...]
    minimum_requirements: dict[str, Any]
    completion_evidence: dict[str, Any]
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


def _validate_relative_path(value: str) -> None:
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise ValueError("campaign paths must be relative and portable")
