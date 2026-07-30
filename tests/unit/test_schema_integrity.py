from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from cross_venue.config import UniverseConfig, load_universe_config
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


def test_clock_rejects_timezone_naive_timestamps() -> None:
    exchange_ts = datetime(2026, 7, 30, 12, 0, 0)  # noqa: DTZ001

    with pytest.raises(ValidationError, match="exchange_ts must be timezone-aware"):
        EventClock(
            exchange_ts=exchange_ts,
            local_receipt_ts=exchange_ts + timedelta(milliseconds=1),
            processing_ts=exchange_ts + timedelta(milliseconds=2),
        )


def test_clock_accepts_equal_timezone_aware_timestamps() -> None:
    timestamp = datetime(2026, 7, 30, 12, 0, 0, 123456, tzinfo=UTC)

    clock = EventClock(
        exchange_ts=timestamp,
        local_receipt_ts=timestamp,
        processing_ts=timestamp,
        decision_ts=timestamp,
        simulated_order_submission_ts=timestamp,
        simulated_order_arrival_ts=timestamp,
        simulated_fill_ts=timestamp,
    )

    assert clock.exchange_ts.microsecond == 123456
    assert clock.simulated_order_arrival_ts == timestamp


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


def test_initial_universe_config_loads_required_spot_markets() -> None:
    config = load_universe_config(Path("configs/initial_universe.example.toml"))

    assert [instrument.exchange for instrument in config.instruments] == [
        Exchange.COINBASE,
        Exchange.KRAKEN,
    ]
    assert {instrument.normalized_symbol for instrument in config.instruments} == {"BTC-USD"}


def test_initial_universe_rejects_extra_venue() -> None:
    with pytest.raises(ValidationError, match="exactly coinbase and kraken"):
        UniverseConfig.model_validate(
            {
                "venues": {
                    "coinbase": {
                        "exchange": "coinbase",
                        "venue_symbol": "BTC-USD",
                        "base_asset": "BTC",
                        "quote_asset": "USD",
                    },
                    "kraken": {
                        "exchange": "kraken",
                        "venue_symbol": "BTC/USD",
                        "base_asset": "BTC",
                        "quote_asset": "USD",
                    },
                    "other": {
                        "exchange": "coinbase",
                        "venue_symbol": "ETH-USD",
                        "base_asset": "ETH",
                        "quote_asset": "USD",
                    },
                }
            }
        )
