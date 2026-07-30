"""Project configuration models and TOML loading helpers."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.schemas import Exchange, InstrumentId

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    with path.open("rb") as config_file:
        data: dict[str, Any] = tomllib.load(config_file)
    return UniverseConfig.model_validate(data)


def load_project_settings(path: Path | None = None) -> ProjectSettings:
    """Load project settings from TOML, then apply safe environment overrides."""

    settings = ProjectSettings()
    if path is not None:
        with path.open("rb") as config_file:
            settings = ProjectSettings.model_validate(tomllib.load(config_file))
    return ProjectSettings.from_environment(base_settings=settings)
