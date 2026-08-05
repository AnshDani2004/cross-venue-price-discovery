"""Bounded in-memory sink for dry-run collector output."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from cross_venue.collectors.base import (
    ExchangeErrorMessage,
    ParsedControlMessage,
    UnsupportedPublicMessage,
)
from cross_venue.collectors.exceptions import CollectorError
from cross_venue.schemas import NormalizedMarketEvent, RawMessageEnvelope


class SinkBackpressureError(CollectorError):
    """Raised when the bounded sink cannot accept an item in time."""


class AsyncSleeper(Protocol):
    """Injectable async sleep callable."""

    async def __call__(self, delay_seconds: float) -> None:
        """Sleep for ``delay_seconds``."""


async def default_async_sleep(delay_seconds: float) -> None:
    """Typed wrapper around ``asyncio.sleep`` for strict callable injection."""

    await asyncio.sleep(delay_seconds)


type SinkItem = (
    RawMessageEnvelope
    | NormalizedMarketEvent
    | ParsedControlMessage
    | UnsupportedPublicMessage
    | ExchangeErrorMessage
)


class EventSink(Protocol):
    """Collector diagnostic sink contract."""

    async def append(
        self,
        item: SinkItem,
        *,
        sleeper: AsyncSleeper = default_async_sleep,
    ) -> None:
        """Append, drop, or otherwise handle one diagnostic sink item."""


@dataclass(slots=True)
class InMemoryEventSink:
    """Bounded FIFO sink with explicit backpressure."""

    max_items: int
    backpressure_timeout_seconds: float = 0.05
    _items: list[SinkItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_items <= 0:
            raise ValueError("sink capacity must be positive")
        if self.backpressure_timeout_seconds < 0:
            raise ValueError("backpressure timeout must be nonnegative")

    @property
    def size(self) -> int:
        """Return the number of buffered items."""

        return len(self._items)

    async def append(
        self,
        item: SinkItem,
        *,
        sleeper: AsyncSleeper = default_async_sleep,
    ) -> None:
        """Append an item or raise if bounded capacity remains unavailable."""

        if len(self._items) < self.max_items:
            self._items.append(item)
            return

        if self.backpressure_timeout_seconds > 0:
            await sleeper(self.backpressure_timeout_seconds)
        if len(self._items) >= self.max_items:
            raise SinkBackpressureError("in-memory sink capacity exhausted")
        self._items.append(item)

    def drain(self) -> tuple[SinkItem, ...]:
        """Return buffered items in order and clear the sink."""

        drained = tuple(self._items)
        self._items.clear()
        return drained


@dataclass(frozen=True, slots=True)
class DiscardingEventSink:
    """Production sink that keeps no diagnostic payloads in memory."""

    async def append(
        self,
        item: SinkItem,
        *,
        sleeper: AsyncSleeper = default_async_sleep,
    ) -> None:
        """Accept and discard an item without in-memory backpressure."""

        _ = (item, sleeper)
