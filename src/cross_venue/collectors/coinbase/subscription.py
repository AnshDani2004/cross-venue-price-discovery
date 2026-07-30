"""Coinbase public subscription payloads and acknowledgement helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from cross_venue.schemas.raw import JsonValue


def coinbase_subscription_payload(
    *,
    product_id: str,
    channels: tuple[str, ...],
) -> str:
    """Return the configured public Coinbase subscription JSON."""

    if product_id != "BTC-USD":
        raise ValueError("Coinbase Phase 2B collector supports BTC-USD only")
    if set(channels) != {"matches", "ticker", "heartbeat"}:
        raise ValueError("Coinbase Phase 2B channels must be matches, ticker, and heartbeat")
    return json.dumps(
        {
            "type": "subscribe",
            "product_ids": [product_id],
            "channels": list(channels),
        },
        separators=(",", ":"),
    )


def coinbase_acknowledged_channels(
    payload: Mapping[str, JsonValue],
    *,
    product_id: str,
    expected_channels: frozenset[str],
) -> frozenset[str]:
    """Return configured channels acknowledged by a Coinbase subscriptions message."""

    if payload.get("type") != "subscriptions":
        return frozenset()
    channels = payload.get("channels")
    if not isinstance(channels, list):
        return frozenset()
    acknowledged: set[str] = set()
    for entry in channels:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        product_ids = entry.get("product_ids")
        if (
            isinstance(name, str)
            and isinstance(product_ids, list)
            and product_id in product_ids
            and name in expected_channels
        ):
            acknowledged.add(name)
    return frozenset(acknowledged)
