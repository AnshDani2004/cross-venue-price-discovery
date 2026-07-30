import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cross_venue.collectors import MessageParseError
from cross_venue.collectors.kraken import parse_kraken_message
from cross_venue.schemas import Exchange, MarketEventType, NormalizedTopOfBook, NormalizedTrade
from cross_venue.schemas.market_data import TradeSide
from cross_venue.schemas.raw import JsonObject

FIXTURE_ROOT = Path("tests/fixtures/kraken")
SESSION_ID = "kraken_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001"


def aware_ts() -> datetime:
    return datetime(2026, 7, 30, 21, 0, 2, tzinfo=UTC)


def load_fixture(name: str) -> JsonObject:
    with (FIXTURE_ROOT / name).open() as fixture_file:
        return json.load(fixture_file)


def test_kraken_single_trade_parsing() -> None:
    result = parse_kraken_message(
        load_fixture("trade_update.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    event = result.events[0]
    assert isinstance(event, NormalizedTrade)
    assert event.venue is Exchange.KRAKEN
    assert event.event_type is MarketEventType.TRADE
    assert event.source_channel == "trade"
    assert event.trade_id == "102"
    assert event.raw_sequence_value == 102
    assert event.price == Decimal("68000.1")
    assert event.quantity == Decimal("0.05")
    assert event.aggressor_side is TradeSide.SELL
    assert event.local_receipt_ts == aware_ts()


def test_kraken_trade_snapshot_and_multiple_trade_parsing_preserve_source_order() -> None:
    snapshot = parse_kraken_message(
        load_fixture("trade_snapshot.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )
    multiple = parse_kraken_message(
        load_fixture("trade_multiple.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert snapshot.events[0].raw_message_type == "snapshot"
    assert [event.trade_id for event in multiple.events if isinstance(event, NormalizedTrade)] == [
        "103",
        "104",
    ]


def test_kraken_trade_id_is_scoped_to_trade_events_only() -> None:
    trade_result = parse_kraken_message(
        load_fixture("trade_update.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )
    ticker_result = parse_kraken_message(
        load_fixture("ticker_update.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert trade_result.events[0].raw_sequence_value == 102
    assert ticker_result.events[0].raw_sequence_value is None
    assert ticker_result.events[0].raw_checksum_value is None


def test_kraken_ticker_snapshot_and_update_parsing() -> None:
    snapshot = parse_kraken_message(
        load_fixture("ticker_snapshot.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )
    update = parse_kraken_message(
        load_fixture("ticker_update.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    snapshot_event = snapshot.events[0]
    update_event = update.events[0]
    assert isinstance(snapshot_event, NormalizedTopOfBook)
    assert snapshot_event.best_bid_price == Decimal("68000.2")
    assert snapshot_event.best_ask_price == Decimal("68000.3")
    assert update_event.raw_message_type == "update"
    assert update_event.local_receipt_ts == aware_ts()


def test_kraken_wrong_symbol_returns_unsupported_result() -> None:
    result = parse_kraken_message(
        load_fixture("wrong_symbol.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.unsupported is not None
    assert "ETH/USD" in result.unsupported.reason


def test_kraken_heartbeat_and_subscription_ack_are_control_messages() -> None:
    heartbeat = parse_kraken_message(
        load_fixture("heartbeat.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )
    subscription = parse_kraken_message(
        load_fixture("subscription_ack.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert heartbeat.control is not None
    assert heartbeat.control.channel == "heartbeat"
    assert subscription.control is not None
    assert subscription.control.message_type == "subscribe"


def test_kraken_exchange_error_is_not_market_event() -> None:
    result = parse_kraken_message(
        load_fixture("error_message.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.exchange_error is not None
    assert not result.events


def test_kraken_unsupported_valid_message_is_explicit() -> None:
    result = parse_kraken_message(
        load_fixture("unsupported_message.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.unsupported is not None
    assert result.unsupported.channel == "instruments"


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("malformed_trade.json", "qty"),
        ("invalid_numeric.json", "qty"),
        ("invalid_timestamp.json", "timestamp"),
    ],
)
def test_kraken_malformed_supported_messages_raise(fixture_name: str, expected: str) -> None:
    with pytest.raises(MessageParseError, match=expected):
        parse_kraken_message(
            load_fixture(fixture_name),
            local_receipt_ts=aware_ts(),
            collector_session_id=SESSION_ID,
        )


def test_kraken_parser_rejects_naive_local_receipt_timestamp() -> None:
    with pytest.raises(MessageParseError, match="local_receipt_ts"):
        parse_kraken_message(
            load_fixture("trade_update.json"),
            local_receipt_ts=datetime(2026, 7, 30, 21, 0, 2),  # noqa: DTZ001
            collector_session_id=SESSION_ID,
        )
