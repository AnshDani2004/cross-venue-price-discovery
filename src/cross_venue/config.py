"""Project configuration models and TOML loading helpers."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cross_venue.schemas import Exchange, InstrumentId


class UniverseVenueConfig(BaseModel):
    """Configured market for one venue in the research universe."""

    model_config = ConfigDict(frozen=True)

    exchange: Exchange
    venue_symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    market_type: str = Field(default="spot")

    @model_validator(mode="after")
    def market_type_must_be_spot(self) -> "UniverseVenueConfig":
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

    model_config = ConfigDict(frozen=True)

    venues: dict[str, UniverseVenueConfig]

    @model_validator(mode="after")
    def initial_universe_contains_required_spot_markets(self) -> "UniverseConfig":
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
