from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cross_venue.schemas import Exchange, MarketEventType, NormalizedTopOfBook, NormalizedTrade
from cross_venue.schemas.market_data import TradeSide


def aware_ts() -> datetime:
    return datetime(2026, 7, 30, 21, 0, tzinfo=UTC)


def valid_trade(**overrides: object) -> NormalizedTrade:
    data = {
        "venue": Exchange.COINBASE,
        "canonical_instrument": "BTC-USD",
        "venue_symbol": "BTC-USD",
        "exchange_ts": aware_ts(),
        "local_receipt_ts": aware_ts(),
        "collector_session_id": "session-1",
        "source_channel": "matches",
        "schema_version": "0.1.0",
        "raw_message_type": "match",
        "trade_id": "10",
        "price": Decimal("68000.25"),
        "quantity": Decimal("0.125"),
        "aggressor_side": TradeSide.BUY,
    }
    data.update(overrides)
    return NormalizedTrade.model_validate(data)


def valid_top_of_book(**overrides: object) -> NormalizedTopOfBook:
    data = {
        "venue": Exchange.COINBASE,
        "canonical_instrument": "BTC-USD",
        "venue_symbol": "BTC-USD",
        "exchange_ts": aware_ts(),
        "local_receipt_ts": aware_ts(),
        "collector_session_id": "session-1",
        "source_channel": "ticker",
        "schema_version": "0.1.0",
        "raw_message_type": "ticker",
        "best_bid_price": Decimal("68000.24"),
        "best_bid_size": Decimal("0"),
        "best_ask_price": Decimal("68000.27"),
        "best_ask_size": Decimal("1.5"),
    }
    data.update(overrides)
    return NormalizedTopOfBook.model_validate(data)


def test_valid_normalized_trade() -> None:
    trade = valid_trade()

    assert trade.event_type is MarketEventType.TRADE
    assert trade.price == Decimal("68000.25")
    assert trade.aggressor_side is TradeSide.BUY


def test_normalized_trade_rejects_invalid_price_and_quantity() -> None:
    with pytest.raises(ValidationError, match="positive"):
        valid_trade(price=Decimal("0"))

    with pytest.raises(ValidationError, match="positive"):
        valid_trade(quantity=Decimal("-0.1"))


def test_normalized_trade_accepts_unknown_side() -> None:
    trade = valid_trade(aggressor_side=TradeSide.UNKNOWN)

    assert trade.aggressor_side is TradeSide.UNKNOWN


def test_valid_top_of_book_allows_zero_size() -> None:
    top = valid_top_of_book()

    assert top.event_type is MarketEventType.TOP_OF_BOOK
    assert top.best_bid_size == Decimal("0")


def test_top_of_book_rejects_crossed_and_locked_markets() -> None:
    with pytest.raises(ValidationError, match="strictly below"):
        valid_top_of_book(best_bid_price=Decimal("68000.30"))

    with pytest.raises(ValidationError, match="strictly below"):
        valid_top_of_book(best_bid_price=Decimal("68000.27"))


def test_normalized_events_reject_naive_timestamps_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        valid_trade(local_receipt_ts=datetime(2026, 7, 30, 21, 0))  # noqa: DTZ001

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        valid_top_of_book(local_note="not part of schema")
