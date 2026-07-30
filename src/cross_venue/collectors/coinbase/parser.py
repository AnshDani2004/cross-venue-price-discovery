"""Offline parser for configured Coinbase Exchange public messages."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from cross_venue.collectors.base import (
    ExchangeErrorMessage,
    ParsedControlMessage,
    ParseResult,
    UnsupportedPublicMessage,
)
from cross_venue.collectors.parsing import (
    ensure_timezone_aware,
    parse_decimal,
    parse_intish,
    parse_rfc3339_timestamp,
    require_str,
)
from cross_venue.schemas import Exchange, NormalizedTopOfBook, NormalizedTrade, TradeSide
from cross_venue.schemas.raw import JsonValue

CANONICAL_INSTRUMENT = "BTC-USD"
VENUE_SYMBOL = "BTC-USD"
SCHEMA_VERSION = "0.1.0"


def parse_coinbase_message(
    payload: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> ParseResult:
    """Parse one Coinbase public payload without opening a network connection."""

    ensure_timezone_aware(local_receipt_ts, field_name="local_receipt_ts")
    message_type = require_str(payload, "type")

    if message_type in {"match", "last_match"}:
        product_id = require_str(payload, "product_id")
        if product_id != VENUE_SYMBOL:
            return _unsupported_wrong_product(product_id, local_receipt_ts, collector_session_id)
        return ParseResult(
            events=(
                _parse_trade(
                    payload,
                    local_receipt_ts=local_receipt_ts,
                    collector_session_id=collector_session_id,
                    raw_message_type=message_type,
                ),
            )
        )
    if message_type == "ticker":
        product_id = require_str(payload, "product_id")
        if product_id != VENUE_SYMBOL:
            return _unsupported_wrong_product(product_id, local_receipt_ts, collector_session_id)
        return ParseResult(
            events=(
                _parse_top_of_book(
                    payload,
                    local_receipt_ts=local_receipt_ts,
                    collector_session_id=collector_session_id,
                ),
            )
        )
    if message_type == "heartbeat":
        return _control_result(payload, local_receipt_ts, collector_session_id, "heartbeat")
    if message_type == "subscriptions":
        return _control_result(payload, local_receipt_ts, collector_session_id, "subscriptions")
    if message_type == "error":
        return ParseResult(
            exchange_error=ExchangeErrorMessage(
                venue=Exchange.COINBASE,
                channel="control",
                message_type="error",
                collector_session_id=collector_session_id,
                local_receipt_ts=local_receipt_ts,
                error_message=require_str(payload, "message"),
            )
        )
    return ParseResult(
        unsupported=UnsupportedPublicMessage(
            venue=Exchange.COINBASE,
            channel=_safe_channel(message_type),
            message_type=message_type,
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            reason="message type is outside Phase 2A Coinbase parser scope",
        )
    )


def _parse_trade(
    payload: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
    raw_message_type: str,
) -> NormalizedTrade:
    raw_sequence_value = parse_intish(payload, "sequence")
    trade_id = str(parse_intish(payload, "trade_id"))
    maker_side = require_str(payload, "side")
    aggressor_side = _coinbase_aggressor_side(maker_side)
    return NormalizedTrade(
        venue=Exchange.COINBASE,
        canonical_instrument=CANONICAL_INSTRUMENT,
        venue_symbol=VENUE_SYMBOL,
        exchange_ts=parse_rfc3339_timestamp(payload, "time"),
        local_receipt_ts=local_receipt_ts,
        collector_session_id=collector_session_id,
        source_channel="matches",
        schema_version=SCHEMA_VERSION,
        raw_message_type=raw_message_type,
        raw_sequence_value=raw_sequence_value,
        trade_id=trade_id,
        price=parse_decimal(payload, "price"),
        quantity=parse_decimal(payload, "size"),
        aggressor_side=aggressor_side,
    )


def _parse_top_of_book(
    payload: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> NormalizedTopOfBook:
    return NormalizedTopOfBook(
        venue=Exchange.COINBASE,
        canonical_instrument=CANONICAL_INSTRUMENT,
        venue_symbol=VENUE_SYMBOL,
        exchange_ts=parse_rfc3339_timestamp(payload, "time"),
        local_receipt_ts=local_receipt_ts,
        collector_session_id=collector_session_id,
        source_channel="ticker",
        schema_version=SCHEMA_VERSION,
        raw_message_type="ticker",
        raw_sequence_value=parse_intish(payload, "sequence"),
        best_bid_price=parse_decimal(payload, "best_bid"),
        best_bid_size=parse_decimal(payload, "best_bid_size"),
        best_ask_price=parse_decimal(payload, "best_ask"),
        best_ask_size=parse_decimal(payload, "best_ask_size"),
    )


def _control_result(
    payload: Mapping[str, JsonValue],
    local_receipt_ts: datetime,
    collector_session_id: str,
    message_type: str,
) -> ParseResult:
    product_id = payload.get("product_id")
    if product_id is not None and product_id != VENUE_SYMBOL:
        return _unsupported_wrong_product(str(product_id), local_receipt_ts, collector_session_id)
    return ParseResult(
        control=ParsedControlMessage(
            venue=Exchange.COINBASE,
            channel=message_type,
            message_type=message_type,
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            payload_summary=f"coinbase {message_type}",
        )
    )


def _coinbase_aggressor_side(maker_side: str) -> TradeSide:
    if maker_side == "sell":
        return TradeSide.BUY
    if maker_side == "buy":
        return TradeSide.SELL
    return TradeSide.UNKNOWN


def _safe_channel(message_type: str) -> str:
    return message_type or "unknown"


def _unsupported_wrong_product(
    product_id: str,
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> ParseResult:
    return ParseResult(
        unsupported=UnsupportedPublicMessage(
            venue=Exchange.COINBASE,
            channel="product_filter",
            message_type="wrong_product",
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            reason=f"product_id {product_id} is outside configured Coinbase scope",
        )
    )
