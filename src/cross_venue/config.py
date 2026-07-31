"""Project configuration models and TOML loading helpers."""

from __future__ import annotations

import os
import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.schemas import Exchange, InstrumentId

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
QualitySeverityName = Literal["info", "warning", "error", "critical"]
MarketType = Literal["spot"]
TopOfBookEventTrigger = Literal["bbo", "trades"]
TargetType = Literal["direction"]
SamplingMethod = Literal["event_time_with_receipt_time_ordering"]
Baseline = Literal["no_change_and_unconditional_response"]
HoldoutPolicy = Literal["chronological_last_20_percent"]
MultipleTestingPolicy = Literal["benjamini_hochberg_fdr_5pct"]
TimestampOrdering = Literal["receipt_time", "exchange_sequence_then_exchange_timestamp"]
NaiveDatetimePolicy = Literal["reject"]
TimestampPrecision = Literal["microsecond"]
TieBreakerField = Literal["local_receipt_ts", "venue", "sequence_number", "message_type"]
ArchiveFormat = Literal["jsonl"]
ChecksumAlgorithm = Literal["sha256"]
ParquetCompression = Literal["zstd", "snappy", "none"]
TimestampUnit = Literal["ns"]
DataPageVersion = Literal["1.0", "2.0"]


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _validate_https_url(value: str, *, field_name: str) -> str:
    if not value.startswith("https://"):
        raise ValueError(f"{field_name} must be an https URL")
    return value


def _validate_wss_url(value: str) -> str:
    if not value.startswith("wss://"):
        raise ValueError("public_websocket_endpoint must use wss://")
    return value


class ProjectSettings(BaseModel):
    """Validated project-level settings with safe local defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    environment: Environment = "development"
    timezone: str = "UTC"
    data_directory: Path = Path("data")
    report_directory: Path = Path("reports")
    log_level: LogLevel = "INFO"

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    @field_validator("data_directory", "report_directory")
    @classmethod
    def path_must_not_be_empty(cls, value: Path) -> Path:
        if str(value).strip() == "":
            raise ValueError("path must not be empty")
        return value.expanduser()

    def resolve_path(self, path: Path, *, base_directory: Path | None = None) -> Path:
        """Resolve a configured path consistently against a base directory."""

        if path.is_absolute():
            return path.resolve()
        return ((base_directory or Path.cwd()) / path).resolve()

    @property
    def resolved_data_directory(self) -> Path:
        """Return the absolute data directory for the current process."""

        return self.resolve_path(self.data_directory)

    @property
    def resolved_report_directory(self) -> Path:
        """Return the absolute report directory for the current process."""

        return self.resolve_path(self.report_directory)

    @classmethod
    def from_environment(
        cls,
        environ: dict[str, str] | None = None,
        *,
        base_settings: ProjectSettings | None = None,
    ) -> ProjectSettings:
        """Create settings from safe ``CROSS_VENUE_*`` environment overrides."""

        source = environ if environ is not None else dict(os.environ)
        base = base_settings or cls()
        update: dict[str, Any] = {}
        mapping = {
            "CROSS_VENUE_ENV": "environment",
            "CROSS_VENUE_TIMEZONE": "timezone",
            "CROSS_VENUE_DATA_DIRECTORY": "data_directory",
            "CROSS_VENUE_REPORT_DIRECTORY": "report_directory",
            "CROSS_VENUE_LOG_LEVEL": "log_level",
        }
        for env_name, field_name in mapping.items():
            if env_name in source:
                update[field_name] = source[env_name]
        return cls.model_validate(base.model_dump() | update)


class UniverseVenueConfig(BaseModel):
    """Configured market for one venue in the research universe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange: Exchange
    venue_symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    market_type: str = Field(default="spot")

    @model_validator(mode="after")
    def market_type_must_be_spot(self) -> UniverseVenueConfig:
        if self.market_type != "spot":
            raise ValueError("Phase 01 supports spot markets only")
        return self

    def to_instrument_id(self) -> InstrumentId:
        """Convert the config entry into the normalized instrument schema."""

        return InstrumentId(
            exchange=self.exchange,
            venue_symbol=self.venue_symbol,
            base_asset=self.base_asset,
            quote_asset=self.quote_asset,
        )


class UniverseConfig(BaseModel):
    """Validated universe configuration for phase-gated research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venues: dict[str, UniverseVenueConfig]

    @model_validator(mode="after")
    def initial_universe_contains_required_spot_markets(self) -> UniverseConfig:
        required_keys = {"coinbase", "kraken"}
        actual_keys = set(self.venues)
        if actual_keys != required_keys:
            raise ValueError("initial universe must contain exactly coinbase and kraken")

        instruments = {key: venue.to_instrument_id() for key, venue in self.venues.items()}
        if instruments["coinbase"].venue_symbol != "BTC-USD":
            raise ValueError("coinbase venue_symbol must be BTC-USD")
        if instruments["kraken"].venue_symbol != "BTC/USD":
            raise ValueError("kraken venue_symbol must be BTC/USD")

        normalized_symbols = {instrument.normalized_symbol for instrument in instruments.values()}
        if normalized_symbols != {"BTC-USD"}:
            raise ValueError("initial universe must contain BTC-USD spot markets only")

        return self

    @property
    def instruments(self) -> tuple[InstrumentId, ...]:
        """Return configured instruments in deterministic venue order."""

        return tuple(self.venues[key].to_instrument_id() for key in sorted(self.venues))


def load_universe_config(path: Path) -> UniverseConfig:
    """Load and validate a universe configuration from TOML."""

    return UniverseConfig.model_validate(_load_toml(path))


def load_project_settings(path: Path | None = None) -> ProjectSettings:
    """Load project settings from TOML, then apply safe environment overrides."""

    settings = ProjectSettings()
    if path is not None:
        settings = ProjectSettings.model_validate(_load_toml(path))
    return ProjectSettings.from_environment(base_settings=settings)


class ChannelFeedConfig(BaseModel):
    """Public market-data contract for one venue channel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    channel: str = Field(min_length=1)
    timestamp_field: str = Field(min_length=1)
    sequence_field: str | None = Field(default=None, min_length=1)
    checksum_field: str | None = Field(default=None, min_length=1)
    event_trigger: TopOfBookEventTrigger | None = None


class VenueFeedConfig(BaseModel):
    """Public market-data feed contract for one initial venue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue_id: Exchange
    enabled: bool = True
    market_type: MarketType = "spot"
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    public_websocket_endpoint: str = Field(min_length=1)
    trade: ChannelFeedConfig
    top_of_book: ChannelFeedConfig
    heartbeat_channel_or_policy: str = Field(min_length=1)
    reconnect_initial_delay_seconds: int = Field(gt=0)
    reconnect_max_delay_seconds: int = Field(gt=0)
    documentation_source: str = Field(min_length=1)
    documentation_review_date: date

    @field_validator("public_websocket_endpoint")
    @classmethod
    def endpoint_must_be_wss(cls, value: str) -> str:
        return _validate_wss_url(value)

    @field_validator("documentation_source")
    @classmethod
    def documentation_source_must_be_https(cls, value: str) -> str:
        return _validate_https_url(value, field_name="documentation_source")

    @model_validator(mode="after")
    def phase_one_channels_match_official_docs(self) -> VenueFeedConfig:
        if self.canonical_instrument != "BTC-USD":
            raise ValueError("Phase 01 venue feeds must use canonical BTC-USD")
        if self.base_asset != "BTC" or self.quote_asset != "USD":
            raise ValueError("Phase 01 venue feeds must be BTC/USD spot markets")
        if self.reconnect_initial_delay_seconds > self.reconnect_max_delay_seconds:
            raise ValueError("initial reconnect delay must not exceed max reconnect delay")
        if self.trade.channel == self.top_of_book.channel:
            raise ValueError("trade and top-of-book channels must be distinct")

        expected_by_venue = {
            Exchange.COINBASE: (
                "BTC-USD",
                ChannelFeedConfig(
                    channel="matches",
                    timestamp_field="time",
                    sequence_field="sequence",
                ),
                ChannelFeedConfig(
                    channel="ticker",
                    timestamp_field="time",
                    sequence_field="sequence",
                ),
            ),
            Exchange.KRAKEN: (
                "BTC/USD",
                ChannelFeedConfig(
                    channel="trade",
                    timestamp_field="timestamp",
                    sequence_field="trade_id",
                ),
                ChannelFeedConfig(
                    channel="ticker",
                    timestamp_field="timestamp",
                    event_trigger="bbo",
                ),
            ),
        }
        expected = expected_by_venue.get(self.venue_id)
        if expected is None:
            raise ValueError("unsupported venue")
        venue_symbol, trade_config, top_of_book_config = expected
        if self.venue_symbol != venue_symbol:
            raise ValueError(f"{self.venue_id} venue_symbol must be {venue_symbol}")
        if self.trade != trade_config:
            raise ValueError(f"{self.venue_id} trade channel config does not match Phase 01")
        if self.top_of_book != top_of_book_config:
            raise ValueError(f"{self.venue_id} top-of-book channel config does not match Phase 01")
        return self


class VenueCatalogConfig(BaseModel):
    """Validated catalog for the Phase 01 public market-data universe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venues: tuple[VenueFeedConfig, ...]

    @model_validator(mode="after")
    def venues_are_exactly_initial_universe(self) -> VenueCatalogConfig:
        venue_ids = [venue.venue_id for venue in self.venues]
        if len(set(venue_ids)) != len(venue_ids):
            raise ValueError("duplicate venue_id entries are not allowed")
        if set(venue_ids) != {Exchange.COINBASE, Exchange.KRAKEN}:
            raise ValueError("venue catalog must contain exactly coinbase and kraken")
        return self


class ResearchConfig(BaseModel):
    """Pre-registered Phase 01 research design for later empirical work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_instrument: str = Field(min_length=1)
    initiating_venues: tuple[Exchange, ...]
    response_horizons_ms: tuple[int, ...]
    event_threshold_ticks: int = Field(gt=0)
    target_type: TargetType
    sampling_method: SamplingMethod
    primary_baseline: Baseline
    data_quality_exclusions: tuple[str, ...] = ()
    random_seed: int = Field(ge=0)
    final_holdout_policy: HoldoutPolicy
    multiple_testing_policy: MultipleTestingPolicy

    @model_validator(mode="after")
    def research_design_is_phase_one_ready(self) -> ResearchConfig:
        if self.canonical_instrument != "BTC-USD":
            raise ValueError("research config must target BTC-USD")
        if len(set(self.initiating_venues)) != len(self.initiating_venues):
            raise ValueError("duplicate initiating venues are not allowed")
        if set(self.initiating_venues) != {Exchange.COINBASE, Exchange.KRAKEN}:
            raise ValueError("research config must include coinbase and kraken")
        if sorted(self.response_horizons_ms) != list(self.response_horizons_ms):
            raise ValueError("response horizons must be sorted ascending")
        if len(set(self.response_horizons_ms)) != len(self.response_horizons_ms):
            raise ValueError("response horizons must be unique")
        if any(horizon <= 0 for horizon in self.response_horizons_ms):
            raise ValueError("response horizons must be positive")
        return self


class MarketRule(BaseModel):
    """Market rules and cost assumptions for one venue/instrument pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue_id: Exchange
    market_type: MarketType = "spot"
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    maker_fee_rate: Decimal = Field(ge=Decimal("0"))
    taker_fee_rate: Decimal = Field(ge=Decimal("0"))
    fee_tier_assumption: str = Field(min_length=1)
    tick_size: Decimal = Field(gt=Decimal("0"))
    minimum_order_size: Decimal = Field(gt=Decimal("0"))
    effective_date: date
    source: str = Field(min_length=1)

    @field_validator("source")
    @classmethod
    def source_must_be_https(cls, value: str) -> str:
        return _validate_https_url(value, field_name="source")

    @model_validator(mode="after")
    def market_rule_matches_initial_universe(self) -> MarketRule:
        if self.canonical_instrument != "BTC-USD":
            raise ValueError("market rules must target BTC-USD")
        expected_symbols = {
            Exchange.COINBASE: "BTC-USD",
            Exchange.KRAKEN: "BTC/USD",
        }
        if self.venue_symbol != expected_symbols[self.venue_id]:
            raise ValueError(f"{self.venue_id} venue_symbol does not match Phase 01 universe")
        return self


class MarketRulesConfig(BaseModel):
    """Validated market-rule catalog for Phase 01."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: tuple[MarketRule, ...]

    @model_validator(mode="after")
    def rules_are_exactly_initial_universe(self) -> MarketRulesConfig:
        venue_ids = [rule.venue_id for rule in self.rules]
        if len(set(venue_ids)) != len(venue_ids):
            raise ValueError("duplicate market-rule venue entries are not allowed")
        if set(venue_ids) != {Exchange.COINBASE, Exchange.KRAKEN}:
            raise ValueError("market rules must contain exactly coinbase and kraken")
        return self


class TimestampPolicyConfig(BaseModel):
    """Point-in-time timestamp ordering policy for collection and simulation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timezone: str = "UTC"
    timezone_aware_required: bool = True
    preserve_exchange_timestamp: bool = True
    simulated_information_ordering: TimestampOrdering
    venue_reconstruction_ordering: TimestampOrdering
    equal_timestamp_tie_breaker: tuple[TieBreakerField, ...]
    clock_offset_jitter_audit_required: bool = True
    naive_datetime_policy: NaiveDatetimePolicy
    timestamp_precision: TimestampPrecision

    @field_validator("timezone")
    @classmethod
    def timestamp_timezone_must_exist(cls, value: str) -> str:
        return ProjectSettings.timezone_must_exist(value)

    @model_validator(mode="after")
    def policy_must_preserve_point_in_time_ordering(self) -> TimestampPolicyConfig:
        if not self.timezone_aware_required:
            raise ValueError("timezone-aware timestamps are required")
        if not self.preserve_exchange_timestamp:
            raise ValueError("exchange timestamps must be preserved")
        if not self.clock_offset_jitter_audit_required:
            raise ValueError("clock-offset jitter audits are required")
        expected_tie_breaker = ("local_receipt_ts", "venue", "sequence_number", "message_type")
        if self.equal_timestamp_tie_breaker != expected_tie_breaker:
            raise ValueError("equal timestamp tie breaker must be deterministic and documented")
        return self


def load_venue_catalog_config(path: Path) -> VenueCatalogConfig:
    """Load and validate public venue feed configuration."""

    return VenueCatalogConfig.model_validate(_load_toml(path))


def load_research_config(path: Path) -> ResearchConfig:
    """Load and validate pre-registered Phase 01 research design."""

    return ResearchConfig.model_validate(_load_toml(path))


def load_market_rules_config(path: Path) -> MarketRulesConfig:
    """Load and validate Phase 01 market-rule assumptions."""

    return MarketRulesConfig.model_validate(_load_toml(path))


def load_timestamp_policy_config(path: Path) -> TimestampPolicyConfig:
    """Load and validate timestamp semantics for point-in-time data handling."""

    return TimestampPolicyConfig.model_validate(_load_toml(path))


class StorageConfig(BaseModel):
    """Validated Phase 2C raw archive storage settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archive_root: Path = Path("data/raw")
    archive_format: ArchiveFormat = "jsonl"
    archive_schema_version: str = Field(min_length=1)
    writer_queue_capacity: int = Field(gt=0)
    writer_enqueue_timeout_seconds: float = Field(gt=0)
    flush_every_records: int = Field(gt=0)
    flush_interval_seconds: float = Field(gt=0)
    fsync_on_flush: bool = True
    rotate_max_records: int = Field(gt=0)
    rotate_max_uncompressed_bytes: int = Field(gt=0)
    rotate_max_seconds: float = Field(gt=0)
    checksum_algorithm: ChecksumAlgorithm = "sha256"
    manifest_checkpoint_every_records: int = Field(gt=0)
    manifest_checkpoint_interval_seconds: float = Field(gt=0)
    partial_file_suffix: str = Field(min_length=1)

    @field_validator("archive_root")
    @classmethod
    def archive_root_must_be_local(cls, value: Path) -> Path:
        text = str(value)
        if "://" in text:
            raise ValueError("archive_root must be a local filesystem path")
        return value.expanduser()

    @field_validator("partial_file_suffix")
    @classmethod
    def partial_suffix_must_be_safe(cls, value: str) -> str:
        if "/" in value or "\\" in value or value.strip() == "":
            raise ValueError("partial file suffix must be safe and nonempty")
        return value


def load_storage_config(path: Path) -> StorageConfig:
    """Load and validate Phase 2C storage configuration."""

    return StorageConfig.model_validate(_load_toml(path))


class QualityIntegrityConfig(BaseModel):
    """Archive-integrity gates for Phase 2D quality analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    require_archive_validation: bool
    require_all_checksums: bool
    allow_partial_shards: bool
    allow_writer_errors: bool
    allow_missing_manifest: bool
    allow_missing_quality_summary: bool


class QualityParsingConfig(BaseModel):
    """Parser and unsupported-message quality thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_parse_error_rate: float = Field(ge=0, le=1)
    max_unsupported_message_rate: float = Field(ge=0, le=1)
    max_wrong_symbol_messages: int = Field(ge=0)


class QualityTimestampConfig(BaseModel):
    """Receipt/exchange timestamp quality thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_nonmonotonic_receipt_events: int = Field(ge=0)
    max_missing_exchange_timestamp_rate: float = Field(ge=0, le=1)
    stale_quote_threshold_ms: int = Field(gt=0)


class QualityCoverageConfig(BaseModel):
    """Minimum coverage required before research promotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_session_duration_seconds: float = Field(gt=0)
    minimum_frames_per_venue: int = Field(ge=0)
    minimum_trades_per_venue: int = Field(ge=0)
    minimum_top_of_book_events_per_venue: int = Field(ge=0)
    minimum_cross_venue_overlap_seconds: float = Field(gt=0)
    maximum_start_skew_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def overlap_must_not_exceed_session_minimum(self) -> QualityCoverageConfig:
        if self.minimum_cross_venue_overlap_seconds > self.minimum_session_duration_seconds:
            raise ValueError("minimum overlap cannot exceed minimum session duration")
        return self


class QualityDuplicateConfig(BaseModel):
    """Duplicate diagnostic thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_exact_raw_duplicate_rate: float = Field(ge=0, le=1)
    max_duplicate_trade_id_rate: float = Field(ge=0, le=1)


class QualityExchangeReceiptDeltaConfig(BaseModel):
    """Pattern-aware observed exchange-receipt delta semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stable_offset_severity: QualitySeverityName = "info"
    low_variance_offset_severity: QualitySeverityName = "info"
    mixed_distribution_severity: QualitySeverityName = "warning"
    sporadic_outlier_severity: QualitySeverityName = "warning"
    unstable_offset_severity: QualitySeverityName = "warning"
    insufficient_evidence_severity: QualitySeverityName = "info"
    minimum_events_for_classification: int = Field(default=30, ge=1)
    stable_negative_rate: float = Field(default=0.8, ge=0, le=1)
    stable_max_iqr_ms: float = Field(default=1000.0, ge=0)
    low_variance_max_iqr_ms: float = Field(default=250.0, ge=0)
    sporadic_negative_rate: float = Field(default=0.05, ge=0, le=1)
    unstable_min_iqr_ms: float = Field(default=3000.0, ge=0)


class QualityCoinbaseContinuityConfig(BaseModel):
    """Coinbase partial-subscription continuity policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_sequence_jump_severity: QualitySeverityName = "info"
    duplicate_related_sequence_severity: QualitySeverityName = "info"
    nonmonotonic_sequence_severity: QualitySeverityName = "warning"
    heartbeat_missing_match_severity: QualitySeverityName = "warning"
    conflicting_trade_id_severity: QualitySeverityName = "error"
    match_ticker_correspondence_minimum: float = Field(default=0.95, ge=0, le=1)
    match_ticker_grace_ms: int = Field(default=5000, ge=0)


class QualityKrakenDuplicateSemanticsConfig(BaseModel):
    """Typed Kraken duplicate severity policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    heartbeat_duplicate_severity: QualitySeverityName = "info"
    status_duplicate_severity: QualitySeverityName = "info"
    subscription_ack_duplicate_severity: QualitySeverityName = "info"
    ticker_duplicate_severity: QualitySeverityName = "info"
    ticker_semantic_duplicate_severity: QualitySeverityName = "info"
    trade_raw_duplicate_severity: QualitySeverityName = "warning"
    identical_trade_duplicate_severity: QualitySeverityName = "warning"
    conflicting_trade_duplicate_severity: QualitySeverityName = "error"
    unsupported_duplicate_severity: QualitySeverityName = "info"
    other_duplicate_severity: QualitySeverityName = "warning"


class QualityQuoteFreshnessConfig(BaseModel):
    """Quote freshness semantics separated from feed liveness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quote_age_severity: QualitySeverityName = "info"
    heartbeat_healthy_quiet_severity: QualitySeverityName = "info"
    market_activity_without_bbo_change_severity: QualitySeverityName = "info"
    probable_feed_inactivity_severity: QualitySeverityName = "warning"
    connection_inactivity_severity: QualitySeverityName = "warning"
    coinbase_unmatched_trade_severity: QualitySeverityName = "warning"
    coinbase_conflicting_trade_severity: QualitySeverityName = "error"
    connection_inactivity_threshold_ms: int = Field(default=10_000, gt=0)
    coinbase_match_ticker_grace_ms: int = Field(default=5000, ge=0)


class QualityDecisionConfig(BaseModel):
    """Quarantine policy switches for noncritical findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quarantine_on_sequence_anomaly: bool
    quarantine_on_timestamp_outlier: bool
    quarantine_on_duplicate_warning: bool
    quarantine_on_stale_quote_warning: bool


class QualityConfigSections(BaseModel):
    """Nested Phase 2D quality-policy sections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    integrity: QualityIntegrityConfig
    parsing: QualityParsingConfig
    timestamps: QualityTimestampConfig
    coverage: QualityCoverageConfig
    duplicates: QualityDuplicateConfig
    decisions: QualityDecisionConfig
    exchange_receipt_delta: QualityExchangeReceiptDeltaConfig = Field(
        default_factory=QualityExchangeReceiptDeltaConfig
    )
    coinbase_continuity: QualityCoinbaseContinuityConfig = Field(
        default_factory=QualityCoinbaseContinuityConfig
    )
    kraken_duplicates: QualityKrakenDuplicateSemanticsConfig = Field(
        default_factory=QualityKrakenDuplicateSemanticsConfig
    )
    quote_freshness: QualityQuoteFreshnessConfig = Field(
        default_factory=QualityQuoteFreshnessConfig
    )


class DataQualityConfig(BaseModel):
    """Validated Phase 2D quality policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    effective_date: date
    report_root: Path = Path("data/quality")
    validated_manifest_root: Path = Path("data/validated/manifests")
    default_controlled_duration_seconds: float = Field(gt=0)
    max_controlled_duration_seconds: float = Field(gt=0)
    max_messages_per_venue: int = Field(gt=0)
    quality: QualityConfigSections

    @field_validator("report_root", "validated_manifest_root")
    @classmethod
    def output_roots_must_be_local(cls, value: Path) -> Path:
        text = str(value)
        if "://" in text:
            raise ValueError("quality output roots must be local filesystem paths")
        return value.expanduser()

    @model_validator(mode="after")
    def defaults_must_fit_hard_limits(self) -> DataQualityConfig:
        if self.default_controlled_duration_seconds > self.max_controlled_duration_seconds:
            raise ValueError("default controlled duration cannot exceed hard maximum")
        return self


def load_data_quality_config(path: Path) -> DataQualityConfig:
    """Load and validate Phase 2D data-quality policy."""

    return DataQualityConfig.model_validate(_load_toml(path))


class NormalizationConfig(BaseModel):
    """Validated Phase 3A deterministic normalization settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalization_schema_version: str = Field(min_length=1)
    output_root: Path = Path("data/normalized")
    parquet_compression: ParquetCompression = "zstd"
    parquet_compression_level: int | None = Field(default=6, ge=1)
    parquet_row_group_size: int = Field(gt=0)
    decimal_precision: int = Field(gt=0)
    decimal_scale: int = Field(ge=0)
    timestamp_unit: TimestampUnit = "ns"
    preserve_raw_duplicates: bool = True
    write_raw_record_outcomes: bool = True
    write_duckdb_catalog: bool = True
    require_validated_manifest: bool = True
    require_quality_policy_version: str = Field(min_length=1)
    require_clean_working_tree_for_final_run: bool = True
    dictionary_encoding: bool = True
    write_statistics: bool = True
    data_page_version: DataPageVersion = "2.0"
    use_compliant_nested_type: bool = True

    @field_validator("output_root")
    @classmethod
    def output_root_must_be_local(cls, value: Path) -> Path:
        text = str(value)
        if "://" in text:
            raise ValueError("normalization output root must be a local filesystem path")
        return value.expanduser()

    @model_validator(mode="after")
    def normalization_settings_are_phase_3a_safe(self) -> NormalizationConfig:
        if self.decimal_scale >= self.decimal_precision:
            raise ValueError("decimal scale must be less than precision")
        if not self.preserve_raw_duplicates:
            raise ValueError("Phase 3A must preserve raw duplicates")
        if not self.write_raw_record_outcomes:
            raise ValueError("Phase 3A must write raw-record outcomes")
        if not self.require_validated_manifest:
            raise ValueError("Phase 3A requires validated manifests")
        if self.parquet_compression == "none" and self.parquet_compression_level is not None:
            raise ValueError("compression level must be omitted when compression is none")
        return self


def load_normalization_config(path: Path) -> NormalizationConfig:
    """Load and validate Phase 3A normalization configuration."""

    return NormalizationConfig.model_validate(_load_toml(path))
