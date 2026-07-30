"""Market-data event schemas shared by collectors, storage, and research."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.schemas.identifiers import InstrumentId
from cross_venue.schemas.timestamps import EventClock


class TradeSide(StrEnum):
    """Aggressor side reported by a venue, where available."""

    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class PositiveDecimalModel(BaseModel):
    """Base model for fields that must be strictly positive."""

    model_config = ConfigDict(frozen=True)

    @field_validator("price", "size", "quantity", check_fields=False)
    @classmethod
    def decimal_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("decimal values must be positive")
        return value


class TradeEvent(PositiveDecimalModel):
    """Normalized representation of a trade observed on one venue."""

    instrument: InstrumentId
    clock: EventClock
    trade_id: str = Field(min_length=1)
    price: Decimal
    size: Decimal
    side: TradeSide = TradeSide.UNKNOWN
    raw_sequence: int | None = Field(
        default=None,
        description="Venue sequence number, if supplied by the feed.",
    )


class BookLevel(PositiveDecimalModel):
    """One visible price level in a limit order book."""

    price: Decimal
    quantity: Decimal


class OrderBookSnapshot(BaseModel):
    """Point-in-time top-of-book or depth snapshot for one venue."""

    model_config = ConfigDict(frozen=True)

    instrument: InstrumentId
    clock: EventClock
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    raw_sequence: int | None = Field(default=None)

    @model_validator(mode="after")
    def book_is_crossed_or_empty(self) -> "OrderBookSnapshot":
        if not self.bids or not self.asks:
            raise ValueError("order book snapshots must contain at least one bid and ask")
        best_bid = max(level.price for level in self.bids)
        best_ask = min(level.price for level in self.asks)
        if best_bid >= best_ask:
            raise ValueError("best bid must be strictly below best ask")
        return self

    @property
    def midpoint(self) -> Decimal:
        """Return the simple best-bid/best-ask midpoint."""

        best_bid = max(level.price for level in self.bids)
        best_ask = min(level.price for level in self.asks)
        return (best_bid + best_ask) / Decimal("2")
