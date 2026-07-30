"""Normalized public market-data event contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.schemas.identifiers import Exchange
from cross_venue.schemas.market_data import TradeSide


class MarketEventType(StrEnum):
    """Normalized market-event kinds emitted by Phase 2A parsers."""

    TRADE = "trade"
    TOP_OF_BOOK = "top_of_book"


class NormalizedEventBase(BaseModel):
    """Fields shared by normalized public market-data events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    event_type: MarketEventType
    exchange_ts: datetime
    local_receipt_ts: datetime
    collector_session_id: str = Field(min_length=1)
    source_channel: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    raw_message_type: str = Field(min_length=1)
    raw_sequence_value: int | str | None = None
    raw_checksum_value: str | None = Field(default=None, min_length=1)

    @field_validator("exchange_ts", "local_receipt_ts")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class NormalizedTrade(NormalizedEventBase):
    """Normalized trade event emitted from configured trade channels."""

    event_type: Literal[MarketEventType.TRADE] = MarketEventType.TRADE
    trade_id: str = Field(min_length=1)
    price: Decimal
    quantity: Decimal
    aggressor_side: TradeSide = TradeSide.UNKNOWN

    @field_validator("price", "quantity")
    @classmethod
    def decimal_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("price and quantity must be positive")
        return value


class NormalizedTopOfBook(NormalizedEventBase):
    """Normalized top-of-book event emitted from configured ticker channels."""

    event_type: Literal[MarketEventType.TOP_OF_BOOK] = MarketEventType.TOP_OF_BOOK
    best_bid_price: Decimal
    best_bid_size: Decimal
    best_ask_price: Decimal
    best_ask_size: Decimal

    @field_validator("best_bid_price", "best_ask_price")
    @classmethod
    def prices_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0"):
            raise ValueError("top-of-book prices must be positive")
        return value

    @field_validator("best_bid_size", "best_ask_size")
    @classmethod
    def sizes_must_be_nonnegative(cls, value: Decimal) -> Decimal:
        if value < Decimal("0"):
            raise ValueError("top-of-book sizes must be nonnegative")
        return value

    @model_validator(mode="after")
    def best_bid_must_be_below_best_ask(self) -> NormalizedTopOfBook:
        if self.best_bid_price >= self.best_ask_price:
            raise ValueError("best bid must be strictly below best ask")
        return self


type NormalizedMarketEvent = NormalizedTrade | NormalizedTopOfBook
