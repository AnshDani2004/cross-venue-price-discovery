"""Collector interface and parser result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cross_venue.collectors.exceptions import LiveCollectorNotImplemented
from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.schemas import Exchange, NormalizedMarketEvent
from cross_venue.schemas.raw import JsonValue


class ParsedControlMessage(BaseModel):
    """A valid public control message such as heartbeat or subscription ack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Exchange
    channel: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    collector_session_id: str = Field(min_length=1)
    local_receipt_ts: datetime
    payload_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamp_must_be_timezone_aware(self) -> ParsedControlMessage:
        if self.local_receipt_ts.tzinfo is None:
            raise ValueError("local_receipt_ts must be timezone-aware")
        return self


class UnsupportedPublicMessage(BaseModel):
    """A valid public message outside the configured Phase 2A parser scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Exchange
    channel: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    collector_session_id: str = Field(min_length=1)
    local_receipt_ts: datetime
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamp_must_be_timezone_aware(self) -> UnsupportedPublicMessage:
        if self.local_receipt_ts.tzinfo is None:
            raise ValueError("local_receipt_ts must be timezone-aware")
        return self


class ExchangeErrorMessage(BaseModel):
    """A valid exchange error/control message, not a market event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Exchange
    channel: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    collector_session_id: str = Field(min_length=1)
    local_receipt_ts: datetime
    error_message: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamp_must_be_timezone_aware(self) -> ExchangeErrorMessage:
        if self.local_receipt_ts.tzinfo is None:
            raise ValueError("local_receipt_ts must be timezone-aware")
        return self


type ParserOutput = (
    NormalizedMarketEvent | ParsedControlMessage | UnsupportedPublicMessage | ExchangeErrorMessage
)


class ParseResult(BaseModel):
    """Explicit parser output with no ambiguous ``None`` result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[NormalizedMarketEvent, ...] = ()
    control: ParsedControlMessage | None = None
    unsupported: UnsupportedPublicMessage | None = None
    exchange_error: ExchangeErrorMessage | None = None

    @model_validator(mode="after")
    def exactly_one_result_kind(self) -> ParseResult:
        result_count = sum(
            bool(value)
            for value in (
                self.events,
                self.control,
                self.unsupported,
                self.exchange_error,
            )
        )
        if result_count != 1:
            raise ValueError("parse result must contain exactly one result kind")
        return self


@runtime_checkable
class MarketDataCollector(Protocol):
    """Minimal future collector contract without network implementation."""

    @property
    def venue(self) -> Exchange:
        """Return the normalized venue identifier."""

    @property
    def instrument(self) -> str:
        """Return the canonical research instrument."""

    @property
    def venue_symbol(self) -> str:
        """Return the venue-native market symbol."""

    @property
    def session_id(self) -> str:
        """Return the deterministic collector session ID."""

    @property
    def state(self) -> CollectorState:
        """Return the current lifecycle state."""

    def start(self) -> None:
        """Advance the lifecycle toward running without opening a network connection."""

    def stop(self) -> None:
        """Advance the lifecycle toward stopped without opening a network connection."""

    def parse_message(
        self,
        payload: Mapping[str, JsonValue],
        *,
        local_receipt_ts: datetime,
    ) -> ParseResult:
        """Parse one already-received public payload using caller-supplied receipt time."""

    def run_live(self) -> None:
        """Raise because live networking is intentionally outside Phase 2A."""

        raise LiveCollectorNotImplemented("live collection is not available in Phase 2A")
