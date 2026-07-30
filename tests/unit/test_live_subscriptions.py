import json

import pytest

from cross_venue.collectors.coinbase.subscription import (
    coinbase_acknowledged_channels,
    coinbase_subscription_payload,
)
from cross_venue.collectors.kraken.subscription import (
    kraken_acknowledged_channels,
    kraken_ticker_subscription_payload,
    kraken_trade_subscription_payload,
)


def test_coinbase_subscription_payload_is_configured_public_scope() -> None:
    payload = json.loads(
        coinbase_subscription_payload(
            product_id="BTC-USD",
            channels=("matches", "ticker", "heartbeat"),
        )
    )

    assert payload == {
        "type": "subscribe",
        "product_ids": ["BTC-USD"],
        "channels": ["matches", "ticker", "heartbeat"],
    }


def test_coinbase_acknowledgement_tracks_expected_channels() -> None:
    ack = {
        "type": "subscriptions",
        "channels": [
            {"name": "matches", "product_ids": ["BTC-USD"]},
            {"name": "ticker", "product_ids": ["BTC-USD"]},
            {"name": "heartbeat", "product_ids": ["BTC-USD"]},
        ],
    }

    assert coinbase_acknowledged_channels(
        ack,
        product_id="BTC-USD",
        expected_channels=frozenset({"matches", "ticker", "heartbeat"}),
    ) == frozenset({"matches", "ticker", "heartbeat"})


def test_kraken_subscription_payloads_are_configured_public_scope() -> None:
    trade = json.loads(kraken_trade_subscription_payload(symbol="BTC/USD"))
    ticker = json.loads(kraken_ticker_subscription_payload(symbol="BTC/USD", event_trigger="bbo"))

    assert trade == {"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"]}}
    assert ticker == {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": ["BTC/USD"],
            "event_trigger": "bbo",
        },
    }


def test_kraken_acknowledgement_tracks_expected_channel() -> None:
    payload = {
        "method": "subscribe",
        "result": {"channel": "ticker", "symbol": "BTC/USD"},
        "success": True,
    }

    assert kraken_acknowledged_channels(
        payload,
        symbol="BTC/USD",
        expected_channels=frozenset({"trade", "ticker"}),
    ) == frozenset({"ticker"})


def test_wrong_symbols_are_rejected_by_subscription_builders() -> None:
    with pytest.raises(ValueError, match="BTC-USD"):
        coinbase_subscription_payload(
            product_id="ETH-USD", channels=("matches", "ticker", "heartbeat")
        )
    with pytest.raises(ValueError, match="BTC/USD"):
        kraken_trade_subscription_payload(symbol="XBT/USD")
    with pytest.raises(ValueError, match="event_trigger=bbo"):
        kraken_ticker_subscription_payload(symbol="BTC/USD", event_trigger="trades")
