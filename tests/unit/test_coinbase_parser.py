import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cross_venue.collectors import MessageParseError
from cross_venue.collectors.coinbase import parse_coinbase_message
from cross_venue.schemas import Exchange, MarketEventType, NormalizedTopOfBook, NormalizedTrade
from cross_venue.schemas.market_data import TradeSide
from cross_venue.schemas.raw import JsonObject

FIXTURE_ROOT = Path("tests/fixtures/coinbase")
SESSION_ID = "coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001"


def aware_ts() -> datetime:
    return datetime(2026, 7, 30, 21, 0, 2, tzinfo=UTC)


def load_fixture(name: str) -> JsonObject:
    with (FIXTURE_ROOT / name).open() as fixture_file:
        return json.load(fixture_file)


def test_coinbase_valid_trade_parsing_preserves_receipt_timestamp() -> None:
    result = parse_coinbase_message(
        load_fixture("trade_match.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    event = result.events[0]
    assert isinstance(event, NormalizedTrade)
    assert event.venue is Exchange.COINBASE
    assert event.event_type is MarketEventType.TRADE
    assert event.canonical_instrument == "BTC-USD"
    assert event.venue_symbol == "BTC-USD"
    assert event.source_channel == "matches"
    assert event.trade_id == "10"
    assert event.price == Decimal("68000.25")
    assert event.quantity == Decimal("0.125")
    assert event.aggressor_side is TradeSide.BUY
    assert event.raw_sequence_value == 50
    assert event.local_receipt_ts == aware_ts()


def test_coinbase_valid_top_of_book_parsing() -> None:
    result = parse_coinbase_message(
        load_fixture("ticker_bbo.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    event = result.events[0]
    assert isinstance(event, NormalizedTopOfBook)
    assert event.source_channel == "ticker"
    assert event.best_bid_price == Decimal("68000.24")
    assert event.best_bid_size == Decimal("0.46688654")
    assert event.best_ask_price == Decimal("68000.27")
    assert event.best_ask_size == Decimal("1.56637040")
    assert event.raw_sequence_value == 37475248783


def test_coinbase_wrong_product_returns_unsupported_result() -> None:
    result = parse_coinbase_message(
        load_fixture("wrong_product.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.unsupported is not None
    assert "ETH-USD" in result.unsupported.reason


def test_coinbase_heartbeat_and_subscription_ack_are_control_messages() -> None:
    heartbeat = parse_coinbase_message(
        load_fixture("heartbeat.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )
    subscription = parse_coinbase_message(
        load_fixture("subscription_ack.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert heartbeat.control is not None
    assert heartbeat.control.channel == "heartbeat"
    assert subscription.control is not None
    assert subscription.control.message_type == "subscriptions"


def test_coinbase_exchange_error_is_not_market_event() -> None:
    result = parse_coinbase_message(
        load_fixture("error_message.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.exchange_error is not None
    assert not result.events


def test_coinbase_unsupported_valid_message_is_explicit() -> None:
    result = parse_coinbase_message(
        load_fixture("unsupported_message.json"),
        local_receipt_ts=aware_ts(),
        collector_session_id=SESSION_ID,
    )

    assert result.unsupported is not None
    assert result.unsupported.message_type == "status"


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("malformed_trade.json", "size"),
        ("invalid_numeric.json", "best_bid"),
        ("invalid_timestamp.json", "time"),
    ],
)
def test_coinbase_malformed_supported_messages_raise(
    fixture_name: str,
    expected: str,
) -> None:
    with pytest.raises(MessageParseError, match=expected):
        parse_coinbase_message(
            load_fixture(fixture_name),
            local_receipt_ts=aware_ts(),
            collector_session_id=SESSION_ID,
        )


def test_coinbase_parser_rejects_naive_local_receipt_timestamp() -> None:
    with pytest.raises(MessageParseError, match="local_receipt_ts"):
        parse_coinbase_message(
            load_fixture("trade_match.json"),
            local_receipt_ts=datetime(2026, 7, 30, 21, 0, 2),  # noqa: DTZ001
            collector_session_id=SESSION_ID,
        )
