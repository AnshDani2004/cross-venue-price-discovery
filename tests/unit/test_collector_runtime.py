from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from cross_venue.collectors.coinbase.collector import build_coinbase_runtime_spec
from cross_venue.collectors.kraken.collector import build_kraken_runtime_spec
from cross_venue.collectors.runtime import CollectorStopReason, RunLimits, run_collector
from cross_venue.collectors.sink import DiscardingEventSink, InMemoryEventSink
from cross_venue.config import StorageConfig, load_venue_catalog_config
from cross_venue.schemas import Exchange, NormalizedTopOfBook, RawMessageEnvelope
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.archive_writer import RotatingRawArchiveWriter


class FakeConnection:
    def __init__(
        self,
        frames: list[str],
        *,
        clock: "FakeClock | None" = None,
        seconds_per_recv: float = 0.0,
    ) -> None:
        self.frames = frames
        self.clock = clock
        self.seconds_per_recv = seconds_per_recv
        self.sent: list[str] = []
        self.closed = False
        self.recv_count = 0

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        self.recv_count += 1
        if self.clock is not None:
            self.clock.monotonic_time += self.seconds_per_recv
        if not self.frames:
            raise TimeoutError("no more frames")
        return self.frames.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeConnector:
    def __init__(self, connections: list[FakeConnection], *, fail_first: bool = False) -> None:
        self.connections = connections
        self.fail_first = fail_first
        self.connect_calls = 0
        self.urls: list[str] = []

    async def connect(
        self,
        url: str,
        *,
        open_timeout_seconds: float,
        max_message_bytes: int,
    ) -> FakeConnection:
        assert open_timeout_seconds > 0
        assert max_message_bytes > 0
        self.connect_calls += 1
        self.urls.append(url)
        if self.fail_first and self.connect_calls == 1:
            raise RuntimeError("temporary network failure")
        return self.connections.pop(0)


class FakeClock:
    def __init__(self) -> None:
        self.now_calls = 0
        self.monotonic_time = 0.0

    def now(self) -> datetime:
        self.now_calls += 1
        return datetime(2026, 7, 30, 21, 0, tzinfo=UTC) + timedelta(seconds=self.now_calls)

    def monotonic(self) -> float:
        return self.monotonic_time

    async def sleep(self, delay_seconds: float) -> None:
        self.monotonic_time += delay_seconds


def _coinbase_spec():
    catalog = load_venue_catalog_config(Path("configs/venues.toml"))
    config = next(venue for venue in catalog.venues if venue.venue_id == Exchange.COINBASE)
    return build_coinbase_runtime_spec(config)


def _kraken_spec():
    catalog = load_venue_catalog_config(Path("configs/venues.toml"))
    config = next(venue for venue in catalog.venues if venue.venue_id == Exchange.KRAKEN)
    return build_kraken_runtime_spec(config)


def _uuid() -> UUID:
    return UUID("00000000-0000-0000-0000-000000000001")


def _storage_config(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        archive_root=tmp_path,
        archive_schema_version="0.1.0",
        writer_queue_capacity=10,
        writer_enqueue_timeout_seconds=1,
        flush_every_records=1,
        flush_interval_seconds=1,
        fsync_on_flush=False,
        rotate_max_records=100,
        rotate_max_uncompressed_bytes=1_000_000,
        rotate_max_seconds=900,
        manifest_checkpoint_every_records=100,
        manifest_checkpoint_interval_seconds=10,
        partial_file_suffix=".partial",
    )


@pytest.mark.asyncio
async def test_runtime_routes_raw_control_and_market_events() -> None:
    frames = [
        (
            '{"type":"subscriptions","channels":['
            '{"name":"matches","product_ids":["BTC-USD"]},'
            '{"name":"ticker","product_ids":["BTC-USD"]},'
            '{"name":"heartbeat","product_ids":["BTC-USD"]}]}'
        ),
        (
            '{"type":"ticker","sequence":1,"product_id":"BTC-USD","best_bid":"100.00",'
            '"best_bid_size":"1.0","best_ask":"100.10","best_ask_size":"2.0",'
            '"time":"2026-07-30T21:00:00Z"}'
        ),
    ]
    connection = FakeConnection(frames)
    connector = FakeConnector([connection])
    clock = FakeClock()
    sink = InMemoryEventSink(max_items=10)

    summary = await run_collector(
        _coinbase_spec(),
        connector=connector,
        sink=sink,
        limits=RunLimits(max_messages=2),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    items = sink.drain()
    assert summary.completed_successfully
    assert summary.subscription_acknowledged
    assert summary.stats.frames_received == 2
    assert summary.stop_reason == CollectorStopReason.MESSAGE_LIMIT_REACHED
    assert summary.stats.raw_messages_created == 2
    assert summary.stats.control_messages == 1
    assert summary.stats.top_of_book_events == 1
    assert summary.stats.trade_events == 0
    assert connection.sent
    assert connection.closed
    assert isinstance(items[0], RawMessageEnvelope)
    assert any(isinstance(item, NormalizedTopOfBook) for item in items)


@pytest.mark.parametrize(
    ("venue", "spec_factory", "frames"),
    [
        (Exchange.COINBASE, _coinbase_spec, lambda count: _coinbase_frames(count)),
        (Exchange.KRAKEN, _kraken_spec, lambda count: _kraken_frames(count)),
    ],
)
@pytest.mark.asyncio
async def test_collector_message_limit_stops_at_exact_configured_frame_count(
    venue: Exchange,
    spec_factory,
    frames,
) -> None:
    clock = FakeClock()
    connection = FakeConnection(frames(10))
    summary = await run_collector(
        spec_factory(),
        connector=FakeConnector([connection]),
        sink=DiscardingEventSink(),
        limits=RunLimits(duration_seconds=1860, max_messages=5, max_phase_duration_seconds=3600),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.stats.venue == venue
    assert summary.stats.frames_received == 5
    assert connection.recv_count == 5
    assert summary.stop_reason == CollectorStopReason.MESSAGE_LIMIT_REACHED
    assert summary.effective_message_limit == 5


@pytest.mark.parametrize(
    ("venue", "spec_factory", "frames"),
    [
        (Exchange.COINBASE, _coinbase_spec, lambda count: _coinbase_frames(count)),
        (Exchange.KRAKEN, _kraken_spec, lambda count: _kraken_frames(count)),
    ],
)
@pytest.mark.asyncio
async def test_collector_5000_message_limit_does_not_stop_before_threshold(
    venue: Exchange,
    spec_factory,
    frames,
) -> None:
    clock = FakeClock()
    connection = FakeConnection(frames(5005))
    summary = await run_collector(
        spec_factory(),
        connector=FakeConnector([connection]),
        sink=DiscardingEventSink(),
        limits=RunLimits(duration_seconds=1860, max_messages=5000, max_phase_duration_seconds=3600),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.stats.venue == venue
    assert summary.stats.frames_received == 5000
    assert connection.recv_count == 5000
    assert summary.stop_reason == CollectorStopReason.MESSAGE_LIMIT_REACHED


@pytest.mark.parametrize(
    ("venue", "spec_factory", "frames"),
    [
        (Exchange.COINBASE, _coinbase_spec, lambda count: _coinbase_frames(count)),
        (Exchange.KRAKEN, _kraken_spec, lambda count: _kraken_frames(count)),
    ],
)
@pytest.mark.asyncio
async def test_collector_100000_message_limit_does_not_stop_at_5000(
    venue: Exchange,
    spec_factory,
    frames,
) -> None:
    clock = FakeClock()
    connection = FakeConnection(frames(5006), clock=clock, seconds_per_recv=0.1)
    summary = await run_collector(
        spec_factory(),
        connector=FakeConnector([connection]),
        sink=DiscardingEventSink(),
        limits=RunLimits(
            duration_seconds=501, max_messages=100_000, max_phase_duration_seconds=3600
        ),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.stats.venue == venue
    assert summary.stats.frames_received > 5000
    assert summary.effective_message_limit == 100_000
    assert summary.stop_reason == CollectorStopReason.REQUESTED_DURATION_REACHED


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        (
            RunLimits(duration_seconds=3, max_messages=100, max_phase_duration_seconds=10),
            CollectorStopReason.REQUESTED_DURATION_REACHED,
        ),
        (
            RunLimits(duration_seconds=100, max_messages=3, max_phase_duration_seconds=10),
            CollectorStopReason.MESSAGE_LIMIT_REACHED,
        ),
        (
            RunLimits(duration_seconds=100, max_messages=100, max_phase_duration_seconds=3),
            CollectorStopReason.PHASE_DURATION_LIMIT_REACHED,
        ),
    ],
)
@pytest.mark.asyncio
async def test_collector_stop_reason_reports_first_reached_runtime_bound(
    limits: RunLimits,
    expected: CollectorStopReason,
) -> None:
    clock = FakeClock()
    connection = FakeConnection(_coinbase_frames(100), clock=clock, seconds_per_recv=1.0)
    summary = await run_collector(
        _coinbase_spec(),
        connector=FakeConnector([connection]),
        sink=DiscardingEventSink(),
        limits=limits,
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.stop_reason == expected


@pytest.mark.asyncio
async def test_runtime_receipt_timestamp_is_captured_after_recv() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"subscriptions","channels":['
                '{"name":"matches","product_ids":["BTC-USD"]},'
                '{"name":"ticker","product_ids":["BTC-USD"]},'
                '{"name":"heartbeat","product_ids":["BTC-USD"]}]}'
            )
        ]
    )
    connector = FakeConnector([connection])
    clock = FakeClock()

    def now_after_recv() -> datetime:
        if clock.now_calls > 0:
            assert connection.recv_count == 1
        return clock.now()

    await run_collector(
        _coinbase_spec(),
        connector=connector,
        sink=InMemoryEventSink(max_items=10),
        limits=RunLimits(max_messages=1),
        now=now_after_recv,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )


@pytest.mark.asyncio
async def test_runtime_retries_retryable_connection_failure() -> None:
    connection = FakeConnection(
        [
            (
                '{"type":"subscriptions","channels":['
                '{"name":"matches","product_ids":["BTC-USD"]},'
                '{"name":"ticker","product_ids":["BTC-USD"]},'
                '{"name":"heartbeat","product_ids":["BTC-USD"]}]}'
            )
        ]
    )
    connector = FakeConnector([connection], fail_first=True)
    clock = FakeClock()

    summary = await run_collector(
        _coinbase_spec(),
        connector=connector,
        sink=InMemoryEventSink(max_items=10),
        limits=RunLimits(max_messages=1),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.completed_successfully
    assert summary.stats.reconnect_attempts == 1
    assert connector.connect_calls == 2
    assert clock.monotonic_time == 1.0


@pytest.mark.asyncio
async def test_runtime_records_parse_error_without_fabricating_event() -> None:
    connection = FakeConnection(["not-json"])
    connector = FakeConnector([connection])
    clock = FakeClock()

    summary = await run_collector(
        _coinbase_spec(),
        connector=connector,
        sink=InMemoryEventSink(max_items=10),
        limits=RunLimits(max_messages=1),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
    )

    assert summary.stats.parse_errors == 1
    assert summary.stats.trade_events == 0
    assert summary.stats.top_of_book_events == 0


@pytest.mark.asyncio
async def test_runtime_archives_exact_frame_before_json_decode(tmp_path: Path) -> None:
    connection = FakeConnection(["not-json"])
    connector = FakeConnector([connection])
    clock = FakeClock()
    writer = RotatingRawArchiveWriter(storage_config=_storage_config(tmp_path))

    summary = await run_collector(
        _coinbase_spec(),
        connector=connector,
        sink=InMemoryEventSink(max_items=10),
        limits=RunLimits(max_messages=1),
        now=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        uuid_factory=_uuid,
        archive_writer=writer,
    )

    assert summary.stats.frames_received == 1
    assert summary.stats.parse_errors == 1
    assert summary.archive_summary is not None
    assert summary.archive_summary.records_written == 1
    shard = summary.archive_summary.shards[0]
    shard_path = summary.archive_summary.session_paths.session_root / shard.relative_path
    record = RawArchiveRecord.from_json_line(shard_path.read_text(encoding="utf-8"))
    assert record.raw_frame == "not-json"
    assert record.local_receipt_ts == datetime(2026, 7, 30, 21, 0, 2, tzinfo=UTC)


def _coinbase_frames(count: int) -> list[str]:
    frames = [
        (
            '{"type":"subscriptions","channels":['
            '{"name":"matches","product_ids":["BTC-USD"]},'
            '{"name":"ticker","product_ids":["BTC-USD"]},'
            '{"name":"heartbeat","product_ids":["BTC-USD"]}]}'
        )
    ]
    for index in range(1, count):
        ts = (datetime(2026, 7, 30, 21, 0, tzinfo=UTC) + timedelta(seconds=index)).isoformat()
        frames.append(
            '{"type":"ticker","sequence":'
            f'{index},"product_id":"BTC-USD","best_bid":"100.00",'
            '"best_bid_size":"1.0","best_ask":"100.10","best_ask_size":"2.0",'
            f'"time":"{ts.replace("+00:00", "Z")}","trade_id":{index}'
            "}"
        )
    return frames


def _kraken_frames(count: int) -> list[str]:
    frames = [
        (
            '{"method":"subscribe","result":{"channel":"trade","symbol":"BTC/USD",'
            '"snapshot":true},"success":true,'
            '"time_in":"2026-07-30T21:00:00.000000Z",'
            '"time_out":"2026-07-30T21:00:00.001000Z"}'
        ),
        (
            '{"method":"subscribe","result":{"channel":"ticker","symbol":"BTC/USD",'
            '"snapshot":true},"success":true,'
            '"time_in":"2026-07-30T21:00:00.000000Z",'
            '"time_out":"2026-07-30T21:00:00.001000Z"}'
        ),
    ]
    for index in range(2, count):
        ts = (datetime(2026, 7, 30, 21, 0, tzinfo=UTC) + timedelta(seconds=index)).isoformat()
        frames.append(
            '{"channel":"ticker","type":"update","data":[{"symbol":"BTC/USD",'
            '"bid":"100.00","bid_qty":"1.0","ask":"100.10","ask_qty":"2.0",'
            f'"timestamp":"{ts.replace("+00:00", "Z")}"'
            "}]}"
        )
    return frames
