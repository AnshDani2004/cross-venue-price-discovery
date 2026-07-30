import os

import pytest

from cross_venue.collectors.coinbase.collector import load_coinbase_live_collector
from cross_venue.collectors.kraken.collector import load_kraken_live_collector
from cross_venue.collectors.runtime import RunLimits

pytestmark = pytest.mark.live


def _live_enabled() -> bool:
    return os.environ.get("CROSS_VENUE_ENABLE_LIVE_SMOKE") == "1"


@pytest.mark.asyncio
async def test_coinbase_public_smoke() -> None:
    if not _live_enabled():
        pytest.skip("set CROSS_VENUE_ENABLE_LIVE_SMOKE=1 to run public Coinbase smoke test")

    collector = load_coinbase_live_collector()
    summary = await collector.collect(limits=RunLimits(duration_seconds=30, max_messages=500))

    assert summary.stats.connections_opened >= 1
    assert summary.subscription_acknowledged
    assert summary.stats.frames_received >= 1
    assert summary.stats.failure_reason is None


@pytest.mark.asyncio
async def test_kraken_public_smoke() -> None:
    if not _live_enabled():
        pytest.skip("set CROSS_VENUE_ENABLE_LIVE_SMOKE=1 to run public Kraken smoke test")

    collector = load_kraken_live_collector()
    summary = await collector.collect(limits=RunLimits(duration_seconds=30, max_messages=500))

    assert summary.stats.connections_opened >= 1
    assert summary.subscription_acknowledged
    assert summary.stats.frames_received >= 1
    assert summary.stats.failure_reason is None
