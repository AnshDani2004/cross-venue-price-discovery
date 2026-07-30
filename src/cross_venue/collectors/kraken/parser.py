"""Offline parser for configured Kraken Spot WebSocket v2 public messages."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from cross_venue.collectors.base import (
    ExchangeErrorMessage,
    ParsedControlMessage,
    ParseResult,
    UnsupportedPublicMessage,
)
from cross_venue.collectors.exceptions import MessageParseError
from cross_venue.collectors.parsing import (
    ensure_timezone_aware,
    parse_decimal,
    parse_intish,
    parse_rfc3339_timestamp,
    require_list,
    require_mapping,
    require_str,
)
from cross_venue.schemas import Exchange, NormalizedTopOfBook, NormalizedTrade, TradeSide
from cross_venue.schemas.raw import JsonValue

CANONICAL_INSTRUMENT = "BTC-USD"
VENUE_SYMBOL = "BTC/USD"
SCHEMA_VERSION = "0.1.0"


def parse_kraken_message(
    payload: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> ParseResult:
    """Parse one Kraken public payload without opening a network connection."""

    ensure_timezone_aware(local_receipt_ts, field_name="local_receipt_ts")

    method = payload.get("method")
    if method == "subscribe":
        return _subscription_ack(payload, local_receipt_ts, collector_session_id)
    if method == "error":
        return ParseResult(
            exchange_error=ExchangeErrorMessage(
                venue=Exchange.KRAKEN,
                channel="control",
                message_type="error",
                collector_session_id=collector_session_id,
                local_receipt_ts=local_receipt_ts,
                error_message=require_str(payload, "error"),
            )
        )

    channel = require_str(payload, "channel")
    message_type = str(payload.get("type", "update"))
    if channel == "trade":
        records = _data_records(payload)
        if all(_record_symbol(record) != VENUE_SYMBOL for record in records):
            return _unsupported_wrong_symbol(
                _record_symbol(records[0]),
                channel,
                local_receipt_ts,
                collector_session_id,
            )
        return ParseResult(
            events=tuple(
                _parse_trade_record(
                    record,
                    local_receipt_ts=local_receipt_ts,
                    collector_session_id=collector_session_id,
                    raw_message_type=message_type,
                )
                for record in records
                if _record_symbol(record) == VENUE_SYMBOL
            )
        )
    if channel == "ticker":
        records = _data_records(payload)
        if all(_record_symbol(record) != VENUE_SYMBOL for record in records):
            return _unsupported_wrong_symbol(
                _record_symbol(records[0]),
                channel,
                local_receipt_ts,
                collector_session_id,
            )
        return ParseResult(
            events=tuple(
                _parse_ticker_record(
                    record,
                    local_receipt_ts=local_receipt_ts,
                    collector_session_id=collector_session_id,
                    raw_message_type=message_type,
                )
                for record in records
                if _record_symbol(record) == VENUE_SYMBOL
            )
        )
    if channel == "heartbeat":
        return ParseResult(
            control=ParsedControlMessage(
                venue=Exchange.KRAKEN,
                channel="heartbeat",
                message_type=message_type,
                collector_session_id=collector_session_id,
                local_receipt_ts=local_receipt_ts,
                payload_summary="kraken heartbeat",
            )
        )
    if channel == "status":
        return ParseResult(
            control=ParsedControlMessage(
                venue=Exchange.KRAKEN,
                channel="status",
                message_type=message_type,
                collector_session_id=collector_session_id,
                local_receipt_ts=local_receipt_ts,
                payload_summary="kraken status",
            )
        )
    return ParseResult(
        unsupported=UnsupportedPublicMessage(
            venue=Exchange.KRAKEN,
            channel=channel,
            message_type=message_type,
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            reason="message type or channel is outside Phase 2A Kraken parser scope",
        )
    )


def _data_records(payload: Mapping[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    records = require_list(payload, "data")
    parsed: list[dict[str, JsonValue]] = []
    for record in records:
        if not isinstance(record, dict):
            raise MessageParseError("Kraken data entries must be objects")
        parsed.append(record)
    if not parsed:
        raise MessageParseError("Kraken data must contain at least one entry")
    return tuple(parsed)


def _record_symbol(record: Mapping[str, JsonValue]) -> str:
    return require_str(record, "symbol")


def _parse_trade_record(
    record: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
    raw_message_type: str,
) -> NormalizedTrade:
    side = require_str(record, "side")
    return NormalizedTrade(
        venue=Exchange.KRAKEN,
        canonical_instrument=CANONICAL_INSTRUMENT,
        venue_symbol=VENUE_SYMBOL,
        exchange_ts=parse_rfc3339_timestamp(record, "timestamp"),
        local_receipt_ts=local_receipt_ts,
        collector_session_id=collector_session_id,
        source_channel="trade",
        schema_version=SCHEMA_VERSION,
        raw_message_type=raw_message_type,
        raw_sequence_value=parse_intish(record, "trade_id"),
        trade_id=str(parse_intish(record, "trade_id")),
        price=parse_decimal(record, "price"),
        quantity=parse_decimal(record, "qty"),
        aggressor_side=_kraken_side(side),
    )


def _parse_ticker_record(
    record: Mapping[str, JsonValue],
    *,
    local_receipt_ts: datetime,
    collector_session_id: str,
    raw_message_type: str,
) -> NormalizedTopOfBook:
    return NormalizedTopOfBook(
        venue=Exchange.KRAKEN,
        canonical_instrument=CANONICAL_INSTRUMENT,
        venue_symbol=VENUE_SYMBOL,
        exchange_ts=parse_rfc3339_timestamp(record, "timestamp"),
        local_receipt_ts=local_receipt_ts,
        collector_session_id=collector_session_id,
        source_channel="ticker",
        schema_version=SCHEMA_VERSION,
        raw_message_type=raw_message_type,
        raw_sequence_value=None,
        raw_checksum_value=None,
        best_bid_price=parse_decimal(record, "bid"),
        best_bid_size=parse_decimal(record, "bid_qty"),
        best_ask_price=parse_decimal(record, "ask"),
        best_ask_size=parse_decimal(record, "ask_qty"),
    )


def _subscription_ack(
    payload: Mapping[str, JsonValue],
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> ParseResult:
    result = require_mapping(payload, "result")
    channel = require_str(result, "channel")
    symbol = result.get("symbol")
    if symbol is not None and symbol != VENUE_SYMBOL:
        return _unsupported_wrong_symbol(
            str(symbol),
            channel,
            local_receipt_ts,
            collector_session_id,
        )
    success = payload.get("success", result.get("success", True))
    if success is False:
        error = payload.get("error", result.get("error", "kraken subscription error"))
        return ParseResult(
            exchange_error=ExchangeErrorMessage(
                venue=Exchange.KRAKEN,
                channel=channel,
                message_type="subscribe",
                collector_session_id=collector_session_id,
                local_receipt_ts=local_receipt_ts,
                error_message=str(error),
            )
        )
    return ParseResult(
        control=ParsedControlMessage(
            venue=Exchange.KRAKEN,
            channel=channel,
            message_type="subscribe",
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            payload_summary=f"kraken subscription ack for {channel}",
        )
    )


def _kraken_side(side: str) -> TradeSide:
    if side == "buy":
        return TradeSide.BUY
    if side == "sell":
        return TradeSide.SELL
    return TradeSide.UNKNOWN


def _unsupported_wrong_symbol(
    symbol: str,
    channel: str,
    local_receipt_ts: datetime,
    collector_session_id: str,
) -> ParseResult:
    return ParseResult(
        unsupported=UnsupportedPublicMessage(
            venue=Exchange.KRAKEN,
            channel=channel,
            message_type="wrong_symbol",
            collector_session_id=collector_session_id,
            local_receipt_ts=local_receipt_ts,
            reason=f"symbol {symbol} is outside configured Kraken scope",
        )
    )
