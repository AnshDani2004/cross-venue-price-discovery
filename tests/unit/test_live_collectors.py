import json
from datetime import UTC, datetime
from pathlib import Path

from cross_venue.collectors.coinbase.collector import build_coinbase_runtime_spec
from cross_venue.collectors.kraken.collector import build_kraken_runtime_spec
from cross_venue.config import load_venue_catalog_config
from cross_venue.schemas import Exchange


def _venue_config(exchange: Exchange):
    catalog = load_venue_catalog_config(Path("configs/venues.toml"))
    return next(venue for venue in catalog.venues if venue.venue_id == exchange)


def test_coinbase_runtime_spec_uses_configured_endpoint_and_channels() -> None:
    spec = build_coinbase_runtime_spec(_venue_config(Exchange.COINBASE))

    assert spec.endpoint == "wss://ws-feed.exchange.coinbase.com"
    assert spec.channels == ("matches", "ticker", "heartbeat")
    payload = json.loads(spec.subscription_payloads[0])
    assert payload["product_ids"] == ["BTC-USD"]
    assert payload["channels"] == ["matches", "ticker", "heartbeat"]


def test_kraken_runtime_spec_uses_configured_endpoint_and_channels() -> None:
    spec = build_kraken_runtime_spec(_venue_config(Exchange.KRAKEN))

    assert spec.endpoint == "wss://ws.kraken.com/v2"
    assert spec.channels == ("trade", "ticker")
    trade = json.loads(spec.subscription_payloads[0])
    ticker = json.loads(spec.subscription_payloads[1])
    assert trade["params"]["channel"] == "trade"
    assert ticker["params"]["channel"] == "ticker"
    assert ticker["params"]["event_trigger"] == "bbo"


def test_kraken_status_messages_are_control_liveness() -> None:
    spec = build_kraken_runtime_spec(_venue_config(Exchange.KRAKEN))
    payload = {"channel": "status", "type": "update", "data": [{"system": "online"}]}

    result = spec.parser(
        payload,
        local_receipt_ts=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        collector_session_id="kraken_test_session",
    )

    assert result.control is not None
    assert result.control.channel == "status"
