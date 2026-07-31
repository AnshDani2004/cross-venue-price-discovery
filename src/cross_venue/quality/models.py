"""Typed Phase 2D data-quality report models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.schemas import Exchange

JsonScalar = str | int | float | bool | None
REPORT_SCHEMA_VERSION = "0.1.0"


class QualitySeverity(StrEnum):
    """Severity for one quality finding."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class QualityDisposition(StrEnum):
    """Final quality decision for a session or paired collection."""

    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class QualityFinding(BaseModel):
    """One typed quality observation with evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    severity: QualitySeverity
    metric: str = Field(min_length=1)
    observed_value: JsonScalar
    threshold: JsonScalar = None
    message: str = Field(min_length=1)
    evidence: dict[str, JsonScalar] = Field(min_length=1)
    affected_channel: str | None = Field(default=None, min_length=1)
    affected_record_range: tuple[int, int] | None = None

    @model_validator(mode="after")
    def record_range_must_be_ordered(self) -> QualityFinding:
        if (
            self.affected_record_range is not None
            and self.affected_record_range[1] < self.affected_record_range[0]
        ):
            raise ValueError("affected record range must be ordered")
        return self


class DuplicateMetrics(BaseModel):
    """Duplicate diagnostics for one session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exact_raw_duplicate_count: int = Field(ge=0)
    exact_raw_duplicate_rate: float = Field(ge=0, le=1)
    consecutive_duplicate_count: int = Field(ge=0)
    maximum_duplicate_run: int = Field(ge=0)
    first_duplicate_record_indices: tuple[int, ...] = ()
    duplicate_trade_id_count: int = Field(ge=0)
    duplicate_trade_id_rate: float = Field(ge=0, le=1)
    conflicting_duplicate_trade_count: int = Field(ge=0)
    exact_duplicate_trade_count: int = Field(ge=0)
    repeated_quote_state_count: int = Field(ge=0)


class ContinuityMetrics(BaseModel):
    """Channel-specific continuity diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coinbase_sequence_observations: int = Field(ge=0)
    coinbase_missing_sequence_count: int = Field(ge=0)
    coinbase_duplicate_sequence_count: int = Field(ge=0)
    coinbase_nonmonotonic_sequence_count: int = Field(ge=0)
    coinbase_sequence_discontinuity_count: int = Field(ge=0)
    kraken_trade_id_observations: int = Field(ge=0)
    kraken_duplicate_trade_id_count: int = Field(ge=0)
    kraken_nonmonotonic_trade_id_count: int = Field(ge=0)
    kraken_ticker_sequence_checks_skipped: bool = True
    reconnect_boundaries: int = Field(ge=0)


class TimestampMetrics(BaseModel):
    """Receipt and exchange timestamp diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    missing_receipt_timestamps: int = Field(ge=0)
    nonmonotonic_receipt_timestamps: int = Field(ge=0)
    equal_receipt_timestamps: int = Field(ge=0)
    min_interarrival_ms: float | None = Field(default=None, ge=0)
    median_interarrival_ms: float | None = Field(default=None, ge=0)
    p95_interarrival_ms: float | None = Field(default=None, ge=0)
    p99_interarrival_ms: float | None = Field(default=None, ge=0)
    max_interarrival_ms: float | None = Field(default=None, ge=0)
    missing_exchange_timestamps: int = Field(ge=0)
    missing_exchange_timestamp_rate: float = Field(ge=0, le=1)
    nonmonotonic_exchange_timestamps: int = Field(ge=0)
    equal_exchange_timestamps: int = Field(ge=0)
    observed_exchange_receipt_delta_count: int = Field(ge=0)
    observed_exchange_receipt_delta_min_ms: float | None = None
    observed_exchange_receipt_delta_median_ms: float | None = None
    observed_exchange_receipt_delta_p95_ms: float | None = None
    observed_exchange_receipt_delta_p99_ms: float | None = None
    observed_exchange_receipt_delta_max_ms: float | None = None
    negative_observed_exchange_receipt_delta_count: int = Field(ge=0)


class QuoteMetrics(BaseModel):
    """Top-of-book quality diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid_quote_count: int = Field(ge=0)
    locked_market_count: int = Field(ge=0)
    crossed_market_count: int = Field(ge=0)
    missing_bid_count: int = Field(ge=0)
    missing_ask_count: int = Field(ge=0)
    nonpositive_price_count: int = Field(ge=0)
    negative_size_count: int = Field(ge=0)
    zero_bid_size_count: int = Field(ge=0)
    zero_ask_size_count: int = Field(ge=0)
    repeated_quote_state_count: int = Field(ge=0)
    bid_only_change_count: int = Field(ge=0)
    ask_only_change_count: int = Field(ge=0)
    both_side_change_count: int = Field(ge=0)
    timestamp_reversal_count: int = Field(ge=0)
    stale_interval_count: int = Field(ge=0)
    stale_total_duration_seconds: float = Field(ge=0)
    stale_max_duration_seconds: float = Field(ge=0)
    stale_percentage_of_session: float = Field(ge=0, le=1)


class CoverageMetrics(BaseModel):
    """Coverage and event-rate diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_duration_seconds: float = Field(ge=0)
    frames_received: int = Field(ge=0)
    raw_records: int = Field(ge=0)
    trades: int = Field(ge=0)
    top_of_book_events: int = Field(ge=0)
    control_messages: int = Field(ge=0)
    unsupported_messages: int = Field(ge=0)
    parse_errors: int = Field(ge=0)
    exchange_errors: int = Field(ge=0)
    reconnects: int = Field(ge=0)
    connections_opened: int = Field(ge=0)
    subscription_acknowledgements: int = Field(ge=0)
    frames_per_second: float = Field(ge=0)
    trades_per_second: float = Field(ge=0)
    top_of_book_events_per_second: float = Field(ge=0)
    archive_bytes: int = Field(ge=0)
    shard_count: int = Field(ge=0)
    first_market_event_ts: datetime | None = None
    last_market_event_ts: datetime | None = None
    first_top_of_book_ts: datetime | None = None
    last_top_of_book_ts: datetime | None = None

    @field_validator(
        "first_market_event_ts",
        "last_market_event_ts",
        "first_top_of_book_ts",
        "last_top_of_book_ts",
    )
    @classmethod
    def optional_timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("coverage timestamps must be timezone-aware")
        return value


class SessionQualityMetrics(BaseModel):
    """All computed session-quality metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duplicates: DuplicateMetrics
    continuity: ContinuityMetrics
    timestamps: TimestampMetrics
    quotes: QuoteMetrics
    coverage: CoverageMetrics


class SessionQualityReport(BaseModel):
    """Immutable quality report for one Phase 2C raw session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    report_schema_version: str = Field(default=REPORT_SCHEMA_VERSION, min_length=1)
    session_id: str = Field(min_length=1)
    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    source_session_relative_path: str = Field(min_length=1)
    source_manifest_sha256: str = Field(min_length=64, max_length=64)
    quality_policy_version: str = Field(min_length=1)
    quality_code_git_commit: str = Field(min_length=1)
    analysis_timestamp: datetime
    input_shard_checksums: dict[str, str] = Field(min_length=1)
    archive_validation_passed: bool
    archive_validation_errors: tuple[str, ...] = ()
    metrics: SessionQualityMetrics
    findings: tuple[QualityFinding, ...] = ()
    disposition: QualityDisposition
    disposition_reasons: tuple[str, ...] = ()
    report_relative_path: str | None = Field(default=None, min_length=1)

    @field_validator("analysis_timestamp")
    @classmethod
    def analysis_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("analysis timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def disposition_must_match_findings(self) -> SessionQualityReport:
        if self.disposition == QualityDisposition.ACCEPTED and any(
            finding.severity == QualitySeverity.CRITICAL for finding in self.findings
        ):
            raise ValueError("accepted report cannot contain critical findings")
        if self.disposition != QualityDisposition.ACCEPTED and not self.disposition_reasons:
            raise ValueError("non-accepted reports require disposition reasons")
        if self.disposition == QualityDisposition.REJECTED and not self.disposition_reasons:
            raise ValueError("rejected reports require rejection evidence")
        return self


class CrossVenueOverlapReport(BaseModel):
    """Overlap metrics for paired Coinbase/Kraken sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paired_collection_id: str = Field(min_length=1)
    requested_duration_seconds: float = Field(gt=0)
    start_skew_seconds: float = Field(ge=0)
    coinbase_session_id: str = Field(min_length=1)
    kraken_session_id: str = Field(min_length=1)
    market_event_overlap_start: datetime | None = None
    market_event_overlap_end: datetime | None = None
    market_event_overlap_duration_seconds: float = Field(ge=0)
    top_of_book_overlap_start: datetime | None = None
    top_of_book_overlap_end: datetime | None = None
    top_of_book_overlap_duration_seconds: float = Field(ge=0)
    coinbase_overlap_coverage_rate: float = Field(ge=0, le=1)
    kraken_overlap_coverage_rate: float = Field(ge=0, le=1)
    reconnect_boundaries_during_overlap: int = Field(ge=0)
    stale_intervals_during_overlap: int = Field(ge=0)

    @field_validator(
        "market_event_overlap_start",
        "market_event_overlap_end",
        "top_of_book_overlap_start",
        "top_of_book_overlap_end",
    )
    @classmethod
    def overlap_timestamps_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("overlap timestamps must be timezone-aware")
        return value


class PairedQualityReport(BaseModel):
    """Quality report for one paired controlled collection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    paired_collection_id: str = Field(min_length=1)
    report_schema_version: str = Field(default=REPORT_SCHEMA_VERSION, min_length=1)
    created_at: datetime
    quality_policy_version: str = Field(min_length=1)
    quality_code_git_commit: str = Field(min_length=1)
    coinbase_report: SessionQualityReport
    kraken_report: SessionQualityReport
    overlap: CrossVenueOverlapReport
    findings: tuple[QualityFinding, ...] = ()
    disposition: QualityDisposition
    disposition_reasons: tuple[str, ...] = ()
    paired_report_relative_path: str | None = Field(default=None, min_length=1)

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def non_accepted_pair_requires_reason(self) -> PairedQualityReport:
        if self.disposition != QualityDisposition.ACCEPTED and not self.disposition_reasons:
            raise ValueError("non-accepted paired report requires disposition reasons")
        return self


class AggregateQualityReport(BaseModel):
    """Aggregate quality summary across session reports."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_schema_version: str = Field(default=REPORT_SCHEMA_VERSION, min_length=1)
    created_at: datetime
    quality_policy_version: str = Field(min_length=1)
    session_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    total_duration_seconds: float = Field(ge=0)
    total_frames: int = Field(ge=0)
    total_raw_bytes: int = Field(ge=0)
    total_trades: int = Field(ge=0)
    total_top_of_book_events: int = Field(ge=0)
    parse_error_rates: tuple[float, ...] = ()
    unsupported_message_rates: tuple[float, ...] = ()
    duplicate_raw_rates: tuple[float, ...] = ()
    sequence_anomaly_counts: tuple[int, ...] = ()
    receipt_time_anomaly_counts: tuple[int, ...] = ()
    stale_quote_percentages: tuple[float, ...] = ()
    reconnect_counts: tuple[int, ...] = ()
    venue_event_rates: dict[str, float] = {}

    @field_validator("created_at")
    @classmethod
    def aggregate_timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ValidatedDatasetManifest(BaseModel):
    """Immutable manifest referencing accepted raw sessions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_manifest_id: str = Field(min_length=1)
    dataset_manifest_version: str = Field(default=REPORT_SCHEMA_VERSION, min_length=1)
    created_at: datetime
    created_by_git_commit: str = Field(min_length=1)
    quality_policy_version: str = Field(min_length=1)
    canonical_instrument: str = Field(min_length=1)
    venues: tuple[Exchange, ...] = Field(min_length=1)
    session_ids: tuple[str, ...] = Field(min_length=1)
    paired_collection_ids: tuple[str, ...] = Field(min_length=1)
    raw_session_relative_paths: tuple[str, ...] = Field(min_length=1)
    raw_manifest_hashes: dict[str, str] = Field(min_length=1)
    raw_shard_checksums: dict[str, str] = Field(min_length=1)
    session_quality_report_paths: tuple[str, ...] = Field(min_length=1)
    session_quality_report_hashes: dict[str, str] = Field(min_length=1)
    cross_venue_overlap_report_path: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    overlap_start: datetime
    overlap_end: datetime
    overlap_duration_seconds: float = Field(gt=0)
    accepted_channels: tuple[str, ...] = Field(min_length=1)
    excluded_sessions: dict[str, str] = {}
    quarantined_sessions: dict[str, str] = {}
    rejected_sessions: dict[str, str] = {}
    known_limitations: tuple[str, ...] = ()
    content_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("created_at", "start_time", "end_time", "overlap_start", "overlap_end")
    @classmethod
    def manifest_timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("dataset manifest timestamps must be timezone-aware")
        return value

    @field_validator(
        "raw_session_relative_paths",
        "session_quality_report_paths",
        mode="after",
    )
    @classmethod
    def paths_must_be_relative(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            parsed = PurePosixPath(item)
            if parsed.is_absolute() or ".." in parsed.parts:
                raise ValueError("manifest paths must be relative and portable")
        return value

    @field_validator("cross_venue_overlap_report_path")
    @classmethod
    def overlap_path_must_be_relative(cls, value: str) -> str:
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("manifest paths must be relative and portable")
        return value

    @model_validator(mode="before")
    @classmethod
    def validated_manifest_must_not_include_bad_sessions(cls, data: Any) -> Any:
        if isinstance(data, dict) and (
            data.get("quarantined_sessions") or data.get("rejected_sessions")
        ):
            raise ValueError("validated manifest cannot include quarantined or rejected sessions")
        return data


QualityReportKind = Literal["session", "paired", "aggregate", "validated_manifest"]
