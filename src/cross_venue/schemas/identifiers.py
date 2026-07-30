"""Stable identifiers for venues and instruments."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Exchange(StrEnum):
    """Supported exchange identifiers for the initial research universe."""

    COINBASE = "coinbase"
    KRAKEN = "kraken"


class InstrumentId(BaseModel):
    """Venue-specific market identifier plus normalized base/quote symbols."""

    model_config = ConfigDict(frozen=True)

    exchange: Exchange
    venue_symbol: str = Field(min_length=1, examples=["BTC-USD", "BTC/USD"])
    base_asset: str = Field(min_length=1, examples=["BTC"])
    quote_asset: str = Field(min_length=1, examples=["USD"])

    @property
    def normalized_symbol(self) -> str:
        """Return the venue-independent symbol used in research outputs."""

        return f"{self.base_asset.upper()}-{self.quote_asset.upper()}"

