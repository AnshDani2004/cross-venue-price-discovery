from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cross_venue.config import VenueCatalogConfig, load_venue_catalog_config
from cross_venue.schemas import Exchange


def valid_catalog_data() -> dict[str, Any]:
    return {
        "venues": [
            {
                "venue_id": "coinbase",
                "enabled": True,
                "market_type": "spot",
                "canonical_instrument": "BTC-USD",
                "venue_symbol": "BTC-USD",
                "base_asset": "BTC",
                "quote_asset": "USD",
                "public_websocket_endpoint": "wss://ws-feed.exchange.coinbase.com",
                "heartbeat_channel_or_policy": "heartbeat",
                "reconnect_initial_delay_seconds": 1,
                "reconnect_max_delay_seconds": 30,
                "documentation_source": "https://docs.cdp.coinbase.com/exchange/websocket-feed/channels",
                "documentation_review_date": "2026-07-30",
                "trade": {
                    "channel": "matches",
                    "timestamp_field": "time",
                    "sequence_field": "sequence",
                },
                "top_of_book": {
                    "channel": "ticker",
                    "timestamp_field": "time",
                    "sequence_field": "sequence",
                },
            },
            {
                "venue_id": "kraken",
                "enabled": True,
                "market_type": "spot",
                "canonical_instrument": "BTC-USD",
                "venue_symbol": "BTC/USD",
                "base_asset": "BTC",
                "quote_asset": "USD",
                "public_websocket_endpoint": "wss://ws.kraken.com/v2",
                "heartbeat_channel_or_policy": "ping if idle",
                "reconnect_initial_delay_seconds": 5,
                "reconnect_max_delay_seconds": 60,
                "documentation_source": "https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker",
                "documentation_review_date": "2026-07-30",
                "trade": {
                    "channel": "trade",
                    "timestamp_field": "timestamp",
                    "sequence_field": "trade_id",
                },
                "top_of_book": {
                    "channel": "ticker",
                    "timestamp_field": "timestamp",
                    "event_trigger": "bbo",
                },
            },
        ]
    }


def test_venue_catalog_loads_coinbase_and_kraken() -> None:
    config = load_venue_catalog_config(Path("configs/venues.toml"))

    assert [venue.venue_id for venue in config.venues] == [
        Exchange.COINBASE,
        Exchange.KRAKEN,
    ]
    assert config.venues[0].trade.channel == "matches"
    assert config.venues[0].top_of_book.channel == "ticker"
    assert config.venues[1].trade.channel == "trade"
    assert config.venues[1].trade.sequence_field == "trade_id"
    assert config.venues[1].top_of_book.channel == "ticker"
    assert config.venues[1].top_of_book.event_trigger == "bbo"
    assert config.venues[1].top_of_book.sequence_field is None
    assert config.venues[1].top_of_book.checksum_field is None


def test_venue_catalog_rejects_unknown_venue() -> None:
    data = valid_catalog_data()
    data["venues"][1]["venue_id"] = "gemini"

    with pytest.raises(ValidationError, match="Input should be"):
        VenueCatalogConfig.model_validate(data)


def test_venue_catalog_rejects_duplicate_venue() -> None:
    data = valid_catalog_data()
    data["venues"][1]["venue_id"] = "coinbase"
    data["venues"][1]["venue_symbol"] = "BTC-USD"
    data["venues"][1]["trade"] = {
        "channel": "matches",
        "timestamp_field": "time",
        "sequence_field": "sequence",
    }
    data["venues"][1]["top_of_book"] = {
        "channel": "ticker",
        "timestamp_field": "time",
        "sequence_field": "sequence",
    }

    with pytest.raises(ValidationError, match="duplicate venue_id"):
        VenueCatalogConfig.model_validate(data)


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_error"),
    [
        ("public_websocket_endpoint", "https://example.com/ws", "must use wss://"),
        ("documentation_review_date", "not-a-date", "valid date"),
        ("documentation_source", "http://example.com", "https URL"),
        ("market_type", "perpetual", "Input should be"),
    ],
)
def test_venue_catalog_rejects_invalid_required_fields(
    field_name: str,
    bad_value: object,
    expected_error: str,
) -> None:
    data = valid_catalog_data()
    data["venues"][0][field_name] = bad_value

    with pytest.raises(ValidationError, match=expected_error):
        VenueCatalogConfig.model_validate(data)


@pytest.mark.parametrize("channel_key", ["trade", "top_of_book"])
def test_venue_catalog_rejects_missing_required_channel(channel_key: str) -> None:
    data = valid_catalog_data()
    del data["venues"][0][channel_key]

    with pytest.raises(ValidationError, match="Field required"):
        VenueCatalogConfig.model_validate(data)


@pytest.mark.parametrize("channel_key", ["trade", "top_of_book"])
def test_venue_catalog_rejects_empty_channel_name(channel_key: str) -> None:
    data = valid_catalog_data()
    data["venues"][0][channel_key]["channel"] = ""

    with pytest.raises(ValidationError, match="String should have at least 1 character"):
        VenueCatalogConfig.model_validate(data)


@pytest.mark.parametrize("channel_key", ["trade", "top_of_book"])
def test_venue_catalog_rejects_missing_channel_name(channel_key: str) -> None:
    data = valid_catalog_data()
    del data["venues"][0][channel_key]["channel"]

    with pytest.raises(ValidationError, match="Field required"):
        VenueCatalogConfig.model_validate(data)


@pytest.mark.parametrize("field_name", ["sequence_field", "checksum_field"])
def test_venue_catalog_rejects_venue_level_channel_metadata(field_name: str) -> None:
    data = valid_catalog_data()
    data["venues"][0][field_name] = "sequence"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VenueCatalogConfig.model_validate(data)


def test_venue_catalog_rejects_unknown_channel_field() -> None:
    data = valid_catalog_data()
    data["venues"][0]["trade"]["local_comment"] = "not public config"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VenueCatalogConfig.model_validate(data)


def test_venue_catalog_rejects_duplicate_channel_names() -> None:
    data = valid_catalog_data()
    data["venues"][0]["trade"]["channel"] = "ticker"
    data["venues"][0]["trade"]["sequence_field"] = "sequence"

    with pytest.raises(ValidationError, match="distinct"):
        VenueCatalogConfig.model_validate(data)


def test_venue_catalog_rejects_unknown_extra_field() -> None:
    data = valid_catalog_data()
    data["venues"][0]["private_note"] = "for local use only"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VenueCatalogConfig.model_validate(data)
