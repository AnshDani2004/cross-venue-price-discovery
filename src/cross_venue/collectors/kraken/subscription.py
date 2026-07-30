"""Kraken Spot WebSocket v2 public subscription payloads and acknowledgement helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from cross_venue.schemas.raw import JsonValue


def kraken_trade_subscription_payload(*, symbol: str) -> str:
    """Return the configured public Kraken trade subscription JSON."""

    _validate_symbol(symbol)
    return json.dumps(
        {"method": "subscribe", "params": {"channel": "trade", "symbol": [symbol]}},
        separators=(",", ":"),
    )


def kraken_ticker_subscription_payload(*, symbol: str, event_trigger: str) -> str:
    """Return the configured public Kraken ticker subscription JSON."""

    _validate_symbol(symbol)
    if event_trigger != "bbo":
        raise ValueError("Kraken Phase 2B ticker subscription requires event_trigger=bbo")
    return json.dumps(
        {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": [symbol],
                "event_trigger": event_trigger,
            },
        },
        separators=(",", ":"),
    )


def kraken_acknowledged_channels(
    payload: Mapping[str, JsonValue],
    *,
    symbol: str,
    expected_channels: frozenset[str],
) -> frozenset[str]:
    """Return configured channels acknowledged by a Kraken subscribe response."""

    if payload.get("method") != "subscribe":
        return frozenset()
    success = payload.get("success", True)
    if success is False:
        return frozenset()
    result = payload.get("result")
    if not isinstance(result, dict):
        return frozenset()
    channel = result.get("channel")
    acknowledged_symbol = result.get("symbol")
    if channel in expected_channels and acknowledged_symbol == symbol:
        return frozenset({str(channel)})
    return frozenset()


def _validate_symbol(symbol: str) -> None:
    if symbol != "BTC/USD":
        raise ValueError("Kraken Phase 2B collector supports BTC/USD only")
