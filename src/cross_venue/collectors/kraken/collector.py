"""Kraken Spot WebSocket v2 public live collector wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from cross_venue.collectors.base import ParseResult
from cross_venue.collectors.kraken.parser import parse_kraken_message
from cross_venue.collectors.kraken.subscription import (
    kraken_acknowledged_channels,
    kraken_ticker_subscription_payload,
    kraken_trade_subscription_payload,
)
from cross_venue.collectors.retry import RetryPolicy
from cross_venue.collectors.runtime import (
    CollectorRunSummary,
    CollectorRuntimeSpec,
    RunLimits,
    run_collector,
)
from cross_venue.collectors.sink import DiscardingEventSink, EventSink, InMemoryEventSink
from cross_venue.collectors.transport import WebSocketConnector, WebsocketsConnector
from cross_venue.config import VenueFeedConfig, load_venue_catalog_config
from cross_venue.schemas import Exchange
from cross_venue.schemas.raw import JsonValue
from cross_venue.storage.archive_writer import RotatingRawArchiveWriter


def build_kraken_runtime_spec(config: VenueFeedConfig) -> CollectorRuntimeSpec:
    """Build the Kraken runtime spec from validated venue config."""

    channels = (config.trade.channel, config.top_of_book.channel)
    expected = frozenset(channels)
    return CollectorRuntimeSpec(
        venue=Exchange.KRAKEN,
        canonical_instrument=config.canonical_instrument,
        venue_symbol=config.venue_symbol,
        endpoint=config.public_websocket_endpoint,
        channels=channels,
        subscription_payloads=(
            kraken_trade_subscription_payload(symbol=config.venue_symbol),
            kraken_ticker_subscription_payload(
                symbol=config.venue_symbol,
                event_trigger=str(config.top_of_book.event_trigger),
            ),
        ),
        expected_acknowledgements=expected,
        parser=parse_kraken_message,
        channel_from_payload=_channel_from_payload,
        message_type_from_payload=_message_type_from_payload,
        raw_sequence_from_payload=_raw_sequence_from_payload,
        acknowledged_channels_from_payload=lambda payload: kraken_acknowledged_channels(
            payload,
            symbol=config.venue_symbol,
            expected_channels=expected,
        ),
        is_heartbeat_payload=lambda payload: payload.get("channel") == "heartbeat",
        is_terminal_exchange_error=_is_terminal_exchange_error,
        retry_policy=RetryPolicy(
            initial_delay_seconds=float(config.reconnect_initial_delay_seconds),
            max_delay_seconds=float(config.reconnect_max_delay_seconds),
            max_attempts=5,
        ),
    )


class KrakenLiveCollector:
    """Bounded public Kraken collector."""

    def __init__(
        self,
        *,
        config: VenueFeedConfig,
        connector: WebSocketConnector | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self.spec = build_kraken_runtime_spec(config)
        self.connector = connector or WebsocketsConnector()
        self.sink = sink

    def parse_message(
        self,
        payload: Mapping[str, JsonValue],
        *,
        local_receipt_ts: datetime,
    ) -> ParseResult:
        """Delegate to the Phase 2A Kraken parser."""

        return parse_kraken_message(
            payload,
            local_receipt_ts=local_receipt_ts,
            collector_session_id="kraken_live_parser_delegate",
        )

    async def collect(
        self,
        *,
        limits: RunLimits,
        stop_event: asyncio.Event | None = None,
        archive_writer: RotatingRawArchiveWriter | None = None,
    ) -> CollectorRunSummary:
        """Run a bounded public collection session."""

        sink = self.sink or (
            DiscardingEventSink()
            if archive_writer is not None
            else InMemoryEventSink(max_items=10_000)
        )
        return await run_collector(
            self.spec,
            connector=self.connector,
            sink=sink,
            limits=limits,
            stop_event=stop_event,
            archive_writer=archive_writer,
        )


def load_kraken_live_collector(
    *,
    config_path: Path = Path("configs/venues.toml"),
    connector: WebSocketConnector | None = None,
    sink: EventSink | None = None,
) -> KrakenLiveCollector:
    """Load Kraken collector from repository config."""

    catalog = load_venue_catalog_config(config_path)
    config = next(venue for venue in catalog.venues if venue.venue_id == Exchange.KRAKEN)
    return KrakenLiveCollector(config=config, connector=connector, sink=sink)


def _channel_from_payload(payload: Mapping[str, JsonValue]) -> str:
    method = payload.get("method")
    if method == "subscribe":
        result = payload.get("result")
        if isinstance(result, dict):
            return str(result.get("channel", "subscribe"))
        return "subscribe"
    return str(payload.get("channel", "unknown"))


def _message_type_from_payload(payload: Mapping[str, JsonValue]) -> str:
    method = payload.get("method")
    if isinstance(method, str):
        return method
    return str(payload.get("type", "update"))


def _raw_sequence_from_payload(payload: Mapping[str, JsonValue]) -> int | str | None:
    if payload.get("channel") != "trade":
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    trade_id = first.get("trade_id")
    if isinstance(trade_id, int | str):
        return trade_id
    return None


def _is_terminal_exchange_error(result: ParseResult) -> bool:
    if result.exchange_error is None:
        return False
    message = result.exchange_error.error_message.lower()
    return any(
        term in message
        for term in ("currency pair not supported", "invalid", "unsupported", "auth")
    )
