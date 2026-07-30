"""Reusable bounded runtime for live public WebSocket collectors."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from cross_venue.collectors.base import ParseResult
from cross_venue.collectors.exceptions import CollectorError, MessageParseError
from cross_venue.collectors.lifecycle import CollectorLifecycle, CollectorState
from cross_venue.collectors.manifest import make_session_id
from cross_venue.collectors.retry import RetryPolicy
from cross_venue.collectors.sink import (
    AsyncSleeper,
    InMemoryEventSink,
    SinkBackpressureError,
    default_async_sleep,
)
from cross_venue.collectors.supervision import HeartbeatSupervisor, InactivityTimeoutError
from cross_venue.collectors.transport import (
    TransportError,
    WebSocketConnector,
    decode_text_frame,
    recv_with_timeout,
)
from cross_venue.schemas import Exchange, MarketEventType, RawMessageEnvelope
from cross_venue.schemas.raw import JsonValue
from cross_venue.storage.archive_writer import (
    ArchiveSessionContext,
    ArchiveSummary,
    RotatingRawArchiveWriter,
)
from cross_venue.storage.exceptions import ArchiveWriterError, StorageError


class UtcNow(Protocol):
    """Callable that returns the current timezone-aware UTC time."""

    def __call__(self) -> datetime:
        """Return current UTC time."""


class MonotonicClock(Protocol):
    """Callable that returns monotonic seconds."""

    def __call__(self) -> float:
        """Return monotonic seconds."""


class MessageParser(Protocol):
    """Venue parser callable reused from Phase 2A."""

    def __call__(
        self,
        payload: Mapping[str, JsonValue],
        *,
        local_receipt_ts: datetime,
        collector_session_id: str,
    ) -> ParseResult:
        """Parse one decoded public payload."""


class CollectorRuntimeError(CollectorError):
    """Base class for runtime failures."""


class RetryableCollectorRuntimeError(CollectorRuntimeError):
    """Failure that may be retried within the configured budget."""


class TerminalCollectorRuntimeError(CollectorRuntimeError):
    """Failure that must stop the collector run."""


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Bounded run limits for Phase 2B collectors."""

    duration_seconds: float = 30.0
    max_messages: int = 500
    max_phase_duration_seconds: float = 120.0
    open_timeout_seconds: float = 10.0
    receive_timeout_seconds: float = 5.0
    subscription_ack_timeout_seconds: float = 10.0
    inactivity_timeout_seconds: float = 15.0
    max_message_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration must be positive")
        if self.duration_seconds > self.max_phase_duration_seconds:
            raise ValueError("duration exceeds Phase 2B maximum")
        if self.max_messages <= 0:
            raise ValueError("message limit must be positive")
        if self.open_timeout_seconds <= 0:
            raise ValueError("open timeout must be positive")
        if self.receive_timeout_seconds <= 0:
            raise ValueError("receive timeout must be positive")
        if self.subscription_ack_timeout_seconds <= 0:
            raise ValueError("subscription acknowledgement timeout must be positive")
        if self.inactivity_timeout_seconds <= 0:
            raise ValueError("inactivity timeout must be positive")
        if self.max_message_bytes <= 0:
            raise ValueError("maximum message size must be positive")


@dataclass(frozen=True, slots=True)
class CollectorRuntimeSpec:
    """Venue-specific runtime behavior."""

    venue: Exchange
    canonical_instrument: str
    venue_symbol: str
    endpoint: str
    channels: tuple[str, ...]
    subscription_payloads: tuple[str, ...]
    expected_acknowledgements: frozenset[str]
    parser: MessageParser
    channel_from_payload: Callable[[Mapping[str, JsonValue]], str]
    message_type_from_payload: Callable[[Mapping[str, JsonValue]], str]
    raw_sequence_from_payload: Callable[[Mapping[str, JsonValue]], int | str | None]
    acknowledged_channels_from_payload: Callable[[Mapping[str, JsonValue]], frozenset[str]]
    is_heartbeat_payload: Callable[[Mapping[str, JsonValue]], bool]
    is_terminal_exchange_error: Callable[[ParseResult], bool]
    retry_policy: RetryPolicy

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("wss://"):
            raise ValueError("collector endpoint must use wss://")
        if not self.channels:
            raise ValueError("collector channels must be nonempty")
        if not self.subscription_payloads:
            raise ValueError("collector must send at least one subscription payload")


@dataclass(slots=True)
class SubscriptionState:
    """In-memory subscription state."""

    expected: frozenset[str]
    acknowledged: set[str] = field(default_factory=set)

    @property
    def acknowledged_all(self) -> bool:
        """Return whether all expected acknowledgements were observed."""

        return self.expected.issubset(self.acknowledged)

    def record(self, channels: frozenset[str]) -> None:
        """Record acknowledged channels."""

        self.acknowledged.update(channels & self.expected)


@dataclass(slots=True)
class SessionStatistics:
    """In-memory statistics accumulated during one bounded run."""

    venue: Exchange
    canonical_instrument: str
    venue_symbol: str
    configured_channels: tuple[str, ...]
    session_id: str
    started_at: datetime
    frames_received: int = 0
    raw_messages_created: int = 0
    trade_events: int = 0
    top_of_book_events: int = 0
    control_messages: int = 0
    unsupported_messages: int = 0
    exchange_errors: int = 0
    parse_errors: int = 0
    reconnect_attempts: int = 0
    connections_opened: int = 0
    subscription_requests: int = 0
    subscription_acknowledgements: int = 0
    heartbeat_messages: int = 0
    archive_records_enqueued: int = 0
    archive_records_written: int = 0
    archive_records_failed: int = 0
    maximum_writer_queue_depth: int = 0
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None
    first_exchange_ts: datetime | None = None
    last_exchange_ts: datetime | None = None
    final_state: CollectorState = CollectorState.CREATED
    failure_reason: str | None = None
    ended_at: datetime | None = None

    def record_receipt(self, timestamp: datetime) -> None:
        """Record local receipt timestamp bounds."""

        if self.first_local_receipt_ts is None:
            self.first_local_receipt_ts = timestamp
        self.last_local_receipt_ts = timestamp

    def record_result(self, result: ParseResult) -> None:
        """Record parser-result counters and exchange timestamp bounds."""

        if result.events:
            for event in result.events:
                if event.event_type == MarketEventType.TRADE:
                    self.trade_events += 1
                if event.event_type == MarketEventType.TOP_OF_BOOK:
                    self.top_of_book_events += 1
                if self.first_exchange_ts is None:
                    self.first_exchange_ts = event.exchange_ts
                if self.last_exchange_ts is None or event.exchange_ts > self.last_exchange_ts:
                    self.last_exchange_ts = event.exchange_ts
        if result.control is not None:
            self.control_messages += 1
        if result.unsupported is not None:
            self.unsupported_messages += 1
        if result.exchange_error is not None:
            self.exchange_errors += 1


@dataclass(frozen=True, slots=True)
class CollectorRunSummary:
    """Returned summary for a bounded live collector run."""

    stats: SessionStatistics
    subscription_acknowledged: bool
    stop_reason: str
    archive_summary: ArchiveSummary | None = None
    data_persisted: bool = False

    @property
    def completed_successfully(self) -> bool:
        """Return whether the bounded run stopped without terminal failure."""

        return (
            self.stats.final_state == CollectorState.STOPPED and self.stats.failure_reason is None
        )

    def to_text(self) -> str:
        """Render a concise safe CLI summary."""

        ack_text = "yes" if self.subscription_acknowledged else "no"
        connected_text = "yes" if self.stats.connections_opened > 0 else "no"
        return "\n".join(
            [
                f"Venue: {self.stats.venue.value}",
                f"Instrument: {self.stats.canonical_instrument}",
                f"Connection opened: {connected_text}",
                f"Subscription acknowledged: {ack_text}",
                f"Frames received: {self.stats.frames_received}",
                f"Trades normalized: {self.stats.trade_events}",
                f"Top-of-book events normalized: {self.stats.top_of_book_events}",
                f"Control messages: {self.stats.control_messages}",
                f"Unsupported messages: {self.stats.unsupported_messages}",
                f"Exchange errors: {self.stats.exchange_errors}",
                f"Parse errors: {self.stats.parse_errors}",
                f"Reconnect attempts: {self.stats.reconnect_attempts}",
                f"Data persisted: {'yes' if self.data_persisted else 'no'}",
                (
                    "Archive shards: "
                    f"{len(self.archive_summary.shards) if self.archive_summary else 0}"
                ),
                (
                    "Archive bytes: "
                    f"{self.archive_summary.total_archive_bytes if self.archive_summary else 0}"
                ),
                f"Final state: {self.stats.final_state.value}",
                f"Stop reason: {self.stop_reason}",
            ]
        )


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(UTC)


async def run_collector(
    spec: CollectorRuntimeSpec,
    *,
    connector: WebSocketConnector,
    sink: InMemoryEventSink,
    limits: RunLimits,
    now: UtcNow = utc_now,
    monotonic: MonotonicClock | None = None,
    sleeper: AsyncSleeper = default_async_sleep,
    jitter_source: Callable[[], float] = lambda: 0.0,
    uuid_factory: Callable[[], UUID] = uuid4,
    stop_event: asyncio.Event | None = None,
    archive_writer: RotatingRawArchiveWriter | None = None,
) -> CollectorRunSummary:
    """Run one bounded public collector session."""

    monotonic_clock = monotonic or asyncio.get_running_loop().time
    started_at = now()
    session_id = make_session_id(
        venue=spec.venue,
        canonical_instrument=spec.canonical_instrument,
        started_at=started_at,
        uuid_factory=uuid_factory,
    )
    stats = SessionStatistics(
        venue=spec.venue,
        canonical_instrument=spec.canonical_instrument,
        venue_symbol=spec.venue_symbol,
        configured_channels=spec.channels,
        session_id=session_id,
        started_at=started_at,
    )
    lifecycle = CollectorLifecycle()
    subscription_state = SubscriptionState(spec.expected_acknowledgements)
    stop_reason = "not started"
    archive_summary: ArchiveSummary | None = None
    if archive_writer is not None:
        await archive_writer.start(
            ArchiveSessionContext(
                venue=spec.venue,
                canonical_instrument=spec.canonical_instrument,
                venue_symbol=spec.venue_symbol,
                session_id=session_id,
                started_at=started_at,
                archive_schema_version="0.1.0",
            )
        )

    attempt = 0
    run_started_mono = monotonic_clock()
    while True:
        if stop_event is not None and stop_event.is_set():
            stop_reason = "external stop requested"
            break
        if monotonic_clock() - run_started_mono >= limits.duration_seconds:
            stop_reason = "duration reached"
            break
        if lifecycle.state == CollectorState.CREATED:
            lifecycle = lifecycle.transition_to(CollectorState.STARTING)
        try:
            stop_reason = await _run_connection_attempt(
                spec,
                connector=connector,
                sink=sink,
                limits=limits,
                stats=stats,
                lifecycle=lifecycle,
                subscription_state=subscription_state,
                now=now,
                monotonic=monotonic_clock,
                sleeper=sleeper,
                stop_event=stop_event,
                run_started_mono=run_started_mono,
                archive_writer=archive_writer,
            )
            break
        except RetryableCollectorRuntimeError as exc:
            attempt += 1
            if attempt > spec.retry_policy.max_attempts:
                stats.failure_reason = f"retry budget exhausted: {exc}"
                lifecycle = _fail_lifecycle(lifecycle)
                stop_reason = "retry budget exhausted"
                break
            stats.reconnect_attempts += 1
            delay = spec.retry_policy.delay_for_attempt(attempt, jitter_source=jitter_source)
            stopped = await _sleep_or_stop(delay, sleeper=sleeper, stop_event=stop_event)
            if stopped:
                stop_reason = "external stop requested during backoff"
                break
        except TerminalCollectorRuntimeError as exc:
            stats.failure_reason = str(exc)
            lifecycle = _fail_lifecycle(lifecycle)
            stop_reason = "terminal failure"
            break
        except StorageError as exc:
            stats.failure_reason = str(exc)
            lifecycle = _fail_lifecycle(lifecycle)
            stop_reason = "storage failure"
            break

    if stats.failure_reason is None:
        if lifecycle.state == CollectorState.CREATED:
            lifecycle = lifecycle.transition_to(CollectorState.STOPPED)
        elif lifecycle.state == CollectorState.STARTING and stats.connections_opened > 0:
            lifecycle = lifecycle.transition_to(CollectorState.RUNNING)
            lifecycle = lifecycle.transition_to(CollectorState.STOPPING).transition_to(
                CollectorState.STOPPED
            )
        elif lifecycle.state == CollectorState.STARTING:
            lifecycle = lifecycle.transition_to(CollectorState.FAILED)
            stats.failure_reason = "collector stopped before connection reached running state"
        elif lifecycle.state == CollectorState.RUNNING:
            lifecycle = lifecycle.transition_to(CollectorState.STOPPING).transition_to(
                CollectorState.STOPPED
            )
    stats.final_state = lifecycle.state
    stats.ended_at = now()
    if archive_writer is not None:
        try:
            archive_summary = await archive_writer.close(rotation_reason=stop_reason)
            stats.archive_records_enqueued = archive_summary.records_enqueued
            stats.archive_records_written = archive_summary.records_written
            stats.archive_records_failed = archive_summary.records_failed
            stats.maximum_writer_queue_depth = archive_summary.maximum_queue_depth
        except ArchiveWriterError as exc:
            stats.failure_reason = str(exc)
            stats.final_state = CollectorState.FAILED
            stop_reason = "archive close failure"
    return CollectorRunSummary(
        stats=stats,
        subscription_acknowledged=subscription_state.acknowledged_all,
        stop_reason=stop_reason,
        archive_summary=archive_summary,
        data_persisted=archive_writer is not None,
    )


async def _run_connection_attempt(
    spec: CollectorRuntimeSpec,
    *,
    connector: WebSocketConnector,
    sink: InMemoryEventSink,
    limits: RunLimits,
    stats: SessionStatistics,
    lifecycle: CollectorLifecycle,
    subscription_state: SubscriptionState,
    now: UtcNow,
    monotonic: MonotonicClock,
    sleeper: AsyncSleeper,
    stop_event: asyncio.Event | None,
    run_started_mono: float,
    archive_writer: RotatingRawArchiveWriter | None,
) -> str:
    connection = None
    ack_deadline = monotonic() + limits.subscription_ack_timeout_seconds
    try:
        connection = await connector.connect(
            spec.endpoint,
            open_timeout_seconds=limits.open_timeout_seconds,
            max_message_bytes=limits.max_message_bytes,
        )
        stats.connections_opened += 1
        for subscription_payload in spec.subscription_payloads:
            await connection.send(subscription_payload)
            stats.subscription_requests += 1
        if lifecycle.state == CollectorState.STARTING:
            lifecycle = lifecycle.transition_to(CollectorState.RUNNING)
        supervisor = HeartbeatSupervisor(
            inactivity_timeout_seconds=limits.inactivity_timeout_seconds,
            last_frame_monotonic=monotonic(),
        )
        while True:
            if stop_event is not None and stop_event.is_set():
                return "external stop requested"
            if monotonic() - run_started_mono >= limits.duration_seconds:
                return "duration reached"
            if stats.frames_received >= limits.max_messages:
                return "message limit reached"
            if not subscription_state.acknowledged_all and monotonic() > ack_deadline:
                raise RetryableCollectorRuntimeError("subscription acknowledgement timeout")
            try:
                supervisor.check(monotonic())
                frame = await recv_with_timeout(
                    connection,
                    receive_timeout_seconds=limits.receive_timeout_seconds,
                )
            except InactivityTimeoutError as exc:
                raise RetryableCollectorRuntimeError(str(exc)) from exc
            except TransportError as exc:
                raise RetryableCollectorRuntimeError(str(exc)) from exc

            local_receipt_ts = now()
            frame_monotonic = monotonic()
            supervisor.record_frame(frame_monotonic)
            stats.record_receipt(local_receipt_ts)
            stats.frames_received += 1
            await _handle_frame(
                frame,
                spec=spec,
                sink=sink,
                stats=stats,
                subscription_state=subscription_state,
                local_receipt_ts=local_receipt_ts,
                frame_monotonic=frame_monotonic,
                supervisor=supervisor,
                sleeper=sleeper,
                archive_writer=archive_writer,
            )
    except SinkBackpressureError as exc:
        raise TerminalCollectorRuntimeError(str(exc)) from exc
    except StorageError:
        raise
    except asyncio.CancelledError:
        raise
    except CollectorRuntimeError:
        raise
    except Exception as exc:
        raise RetryableCollectorRuntimeError(str(exc)) from exc
    finally:
        if connection is not None:
            await connection.close()


async def _handle_frame(
    frame: str | bytes,
    *,
    spec: CollectorRuntimeSpec,
    sink: InMemoryEventSink,
    stats: SessionStatistics,
    subscription_state: SubscriptionState,
    local_receipt_ts: datetime,
    frame_monotonic: float,
    supervisor: HeartbeatSupervisor,
    sleeper: AsyncSleeper,
    archive_writer: RotatingRawArchiveWriter | None,
) -> None:
    try:
        if archive_writer is not None:
            archive_record = archive_writer.make_record(frame, local_receipt_ts=local_receipt_ts)
            await archive_writer.append(archive_record)
        text = decode_text_frame(frame)
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise MessageParseError("decoded WebSocket frame must be a JSON object")
        parsed_payload: dict[str, JsonValue] = payload
        raw_envelope = RawMessageEnvelope(
            venue=spec.venue,
            canonical_instrument=spec.canonical_instrument,
            venue_symbol=spec.venue_symbol,
            channel=spec.channel_from_payload(parsed_payload),
            message_type=spec.message_type_from_payload(parsed_payload),
            payload=parsed_payload,
            local_receipt_ts=local_receipt_ts,
            collector_session_id=stats.session_id,
            schema_version="0.1.0",
            raw_sequence_value=spec.raw_sequence_from_payload(parsed_payload),
        )
        stats.raw_messages_created += 1
        await sink.append(raw_envelope, sleeper=sleeper)
        result = spec.parser(
            parsed_payload,
            local_receipt_ts=local_receipt_ts,
            collector_session_id=stats.session_id,
        )
    except (json.JSONDecodeError, MessageParseError, ValueError) as exc:
        stats.parse_errors += 1
        if stats.parse_errors > 10:
            raise TerminalCollectorRuntimeError("repeated parser-contract violations") from exc
        return

    acknowledged = spec.acknowledged_channels_from_payload(parsed_payload)
    previous_ack_count = len(subscription_state.acknowledged)
    subscription_state.record(acknowledged)
    stats.subscription_acknowledgements += len(subscription_state.acknowledged) - previous_ack_count

    if spec.is_heartbeat_payload(parsed_payload):
        stats.heartbeat_messages += 1
    if result.control is not None:
        supervisor.record_control(frame_monotonic)
        await sink.append(result.control, sleeper=sleeper)
    if result.unsupported is not None:
        await sink.append(result.unsupported, sleeper=sleeper)
    if result.exchange_error is not None:
        await sink.append(result.exchange_error, sleeper=sleeper)
    for event in result.events:
        supervisor.record_market_event(frame_monotonic)
        await sink.append(event, sleeper=sleeper)
    stats.record_result(result)
    if spec.is_terminal_exchange_error(result):
        raise TerminalCollectorRuntimeError("terminal exchange error received")


async def _sleep_or_stop(
    delay_seconds: float,
    *,
    sleeper: AsyncSleeper,
    stop_event: asyncio.Event | None,
) -> bool:
    if stop_event is None:
        await sleeper(delay_seconds)
        return False
    sleep_task = asyncio.create_task(sleeper(delay_seconds))
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, pending = await asyncio.wait(
            {sleep_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        return stop_task in done
    finally:
        for task in (sleep_task, stop_task):
            if not task.done():
                task.cancel()


def _fail_lifecycle(lifecycle: CollectorLifecycle) -> CollectorLifecycle:
    if lifecycle.state in {
        CollectorState.STARTING,
        CollectorState.RUNNING,
        CollectorState.STOPPING,
    }:
        return lifecycle.transition_to(CollectorState.FAILED)
    if lifecycle.state == CollectorState.CREATED:
        return lifecycle.transition_to(CollectorState.STARTING).transition_to(CollectorState.FAILED)
    return lifecycle
