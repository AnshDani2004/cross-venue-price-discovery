from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cross_venue.collectors import (
    CollectorLifecycle,
    CollectorState,
    LiveCollectorNotImplemented,
    MarketDataCollector,
    ParseResult,
    UnsupportedPublicMessage,
)
from cross_venue.schemas import Exchange
from cross_venue.schemas.raw import JsonValue, RawMessageEnvelope


class DummyCollector(MarketDataCollector):
    def __init__(self) -> None:
        self._lifecycle = CollectorLifecycle()

    @property
    def venue(self) -> Exchange:
        return Exchange.COINBASE

    @property
    def instrument(self) -> str:
        return "BTC-USD"

    @property
    def venue_symbol(self) -> str:
        return "BTC-USD"

    @property
    def session_id(self) -> str:
        return "coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001"

    @property
    def state(self) -> CollectorState:
        return self._lifecycle.state

    def start(self) -> None:
        self._lifecycle = self._lifecycle.transition_to(CollectorState.STARTING)

    def stop(self) -> None:
        self._lifecycle = self._lifecycle.transition_to(CollectorState.STOPPED)

    def parse_message(
        self,
        payload: Mapping[str, JsonValue],
        *,
        local_receipt_ts: datetime,
    ) -> ParseResult:
        return ParseResult(
            unsupported=UnsupportedPublicMessage(
                venue=self.venue,
                channel=str(payload.get("type", "unknown")),
                message_type=str(payload.get("type", "unknown")),
                collector_session_id=self.session_id,
                local_receipt_ts=local_receipt_ts,
                reason="dummy collector does not parse payloads",
            )
        )


def aware_ts() -> datetime:
    return datetime(2026, 7, 30, 21, 0, tzinfo=UTC)


def test_collector_interface_shape_and_properties() -> None:
    collector = DummyCollector()

    assert isinstance(collector, MarketDataCollector)
    assert collector.venue is Exchange.COINBASE
    assert collector.instrument == "BTC-USD"
    assert collector.venue_symbol == "BTC-USD"
    assert collector.state is CollectorState.CREATED


def test_collector_parse_requires_explicit_local_receipt_ts() -> None:
    collector = DummyCollector()

    result = collector.parse_message({"type": "status"}, local_receipt_ts=aware_ts())

    assert result.unsupported is not None
    assert result.unsupported.local_receipt_ts == aware_ts()


def test_live_network_collection_is_not_implemented() -> None:
    collector = DummyCollector()

    with pytest.raises(LiveCollectorNotImplemented, match="Phase 2A"):
        collector.run_live()


def test_raw_message_envelope_preserves_payload_and_metadata() -> None:
    payload: dict[str, JsonValue] = {"type": "heartbeat", "product_id": "BTC-USD"}

    envelope = RawMessageEnvelope(
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        channel="heartbeat",
        message_type="heartbeat",
        payload=payload,
        local_receipt_ts=aware_ts(),
        collector_session_id="session-1",
        schema_version="0.1.0",
    )

    assert envelope.payload == payload
    assert envelope.local_receipt_ts == aware_ts()


def test_raw_message_envelope_rejects_naive_receipt_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        RawMessageEnvelope(
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            channel="heartbeat",
            message_type="heartbeat",
            payload={"type": "heartbeat"},
            local_receipt_ts=datetime(2026, 7, 30, 21, 0),  # noqa: DTZ001
            collector_session_id="session-1",
            schema_version="0.1.0",
        )


def test_raw_message_envelope_rejects_unknown_fields_and_sensitive_payload() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RawMessageEnvelope.model_validate(
            {
                "venue": "coinbase",
                "canonical_instrument": "BTC-USD",
                "venue_symbol": "BTC-USD",
                "channel": "heartbeat",
                "message_type": "heartbeat",
                "payload": {"type": "heartbeat"},
                "local_receipt_ts": aware_ts(),
                "collector_session_id": "session-1",
                "schema_version": "0.1.0",
                "private_note": "not part of the contract",
            }
        )

    with pytest.raises(ValidationError, match="credential fields"):
        RawMessageEnvelope(
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            channel="heartbeat",
            message_type="heartbeat",
            payload={"type": "heartbeat", "api_key": "not-allowed"},
            local_receipt_ts=aware_ts(),
            collector_session_id="session-1",
            schema_version="0.1.0",
        )
