from datetime import UTC, datetime

import pytest

from cross_venue.collectors.sink import InMemoryEventSink, SinkBackpressureError
from cross_venue.schemas import Exchange, RawMessageEnvelope


async def _no_sleep(_delay_seconds: float) -> None:
    return None


def _raw_envelope() -> RawMessageEnvelope:
    return RawMessageEnvelope(
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        channel="heartbeat",
        message_type="heartbeat",
        payload={"type": "heartbeat"},
        local_receipt_ts=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        collector_session_id="coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001",
        schema_version="0.1.0",
    )


@pytest.mark.asyncio
async def test_sink_accepts_and_drains_items_in_order() -> None:
    sink = InMemoryEventSink(max_items=2)
    item = _raw_envelope()

    await sink.append(item)

    assert sink.size == 1
    assert sink.drain() == (item,)
    assert sink.size == 0


@pytest.mark.asyncio
async def test_sink_capacity_is_explicit_backpressure() -> None:
    sink = InMemoryEventSink(max_items=1)
    await sink.append(_raw_envelope())

    with pytest.raises(SinkBackpressureError, match="capacity exhausted"):
        await sink.append(_raw_envelope(), sleeper=_no_sleep)

    assert sink.size == 1


def test_sink_rejects_unbounded_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        InMemoryEventSink(max_items=0)
