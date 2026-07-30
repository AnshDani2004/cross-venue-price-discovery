from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cross_venue.schemas import (
    BookLevel,
    EventClock,
    Exchange,
    InstrumentId,
    OrderBookSnapshot,
    TradeEvent,
    TradeSide,
)


def btc_coinbase() -> InstrumentId:
    return InstrumentId(
        exchange=Exchange.COINBASE,
        venue_symbol="BTC-USD",
        base_asset="BTC",
        quote_asset="USD",
    )


def valid_clock() -> EventClock:
    exchange_ts = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)
    return EventClock(
        exchange_ts=exchange_ts,
        local_receipt_ts=exchange_ts + timedelta(milliseconds=4),
        processing_ts=exchange_ts + timedelta(milliseconds=5),
    )


def test_instrument_normalized_symbol_is_venue_independent() -> None:
    instrument = btc_coinbase()

    assert instrument.normalized_symbol == "BTC-USD"


def test_trade_event_accepts_positive_price_and_size() -> None:
    trade = TradeEvent(
        instrument=btc_coinbase(),
        clock=valid_clock(),
        trade_id="123",
        price=Decimal("68000.01"),
        size=Decimal("0.025"),
        side=TradeSide.BUY,
        raw_sequence=42,
    )

    assert trade.price == Decimal("68000.01")
    assert trade.side is TradeSide.BUY


def test_trade_event_rejects_non_positive_size() -> None:
    with pytest.raises(ValidationError, match="decimal values must be positive"):
        TradeEvent(
            instrument=btc_coinbase(),
            clock=valid_clock(),
            trade_id="123",
            price=Decimal("68000.01"),
            size=Decimal("0"),
        )


def test_clock_rejects_local_receipt_before_exchange_timestamp() -> None:
    exchange_ts = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(ValidationError, match="local_receipt_ts"):
        EventClock(
            exchange_ts=exchange_ts,
            local_receipt_ts=exchange_ts - timedelta(milliseconds=1),
            processing_ts=exchange_ts + timedelta(milliseconds=1),
        )


def test_order_book_snapshot_rejects_crossed_book() -> None:
    with pytest.raises(ValidationError, match="best bid"):
        OrderBookSnapshot(
            instrument=btc_coinbase(),
            clock=valid_clock(),
            bids=(BookLevel(price=Decimal("101"), quantity=Decimal("1")),),
            asks=(BookLevel(price=Decimal("100"), quantity=Decimal("1")),),
        )


def test_order_book_snapshot_midpoint_uses_best_prices() -> None:
    snapshot = OrderBookSnapshot(
        instrument=btc_coinbase(),
        clock=valid_clock(),
        bids=(
            BookLevel(price=Decimal("99"), quantity=Decimal("1")),
            BookLevel(price=Decimal("100"), quantity=Decimal("1")),
        ),
        asks=(
            BookLevel(price=Decimal("101"), quantity=Decimal("1")),
            BookLevel(price=Decimal("102"), quantity=Decimal("1")),
        ),
    )

    assert snapshot.midpoint == Decimal("100.5")

