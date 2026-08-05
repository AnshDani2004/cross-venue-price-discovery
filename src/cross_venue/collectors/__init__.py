"""Offline collector contracts for public market-data ingestion."""

from cross_venue.collectors.base import (
    ExchangeErrorMessage,
    MarketDataCollector,
    ParsedControlMessage,
    ParseResult,
    UnsupportedPublicMessage,
)
from cross_venue.collectors.exceptions import (
    CollectorError,
    InvalidCollectorStateTransition,
    InvalidCollectorStateTransitionError,
    LiveCollectorNotImplemented,
    LiveCollectorNotImplementedError,
    MessageParseError,
    UnsupportedMessageError,
)
from cross_venue.collectors.lifecycle import CollectorLifecycle, CollectorState
from cross_venue.collectors.manifest import SessionManifest, make_session_id
from cross_venue.collectors.retry import RetryPolicy
from cross_venue.collectors.runtime import (
    CollectorRunSummary,
    CollectorRuntimeSpec,
    CollectorStopReason,
    RunLimits,
    SessionStatistics,
    SubscriptionState,
    run_collector,
)
from cross_venue.collectors.sink import InMemoryEventSink, SinkBackpressureError
from cross_venue.collectors.supervision import HeartbeatSupervisor, InactivityTimeoutError
from cross_venue.collectors.transport import WebSocketConnection, WebSocketConnector

__all__ = [
    "CollectorError",
    "CollectorLifecycle",
    "CollectorRunSummary",
    "CollectorRuntimeSpec",
    "CollectorState",
    "CollectorStopReason",
    "ExchangeErrorMessage",
    "HeartbeatSupervisor",
    "InMemoryEventSink",
    "InactivityTimeoutError",
    "InvalidCollectorStateTransition",
    "InvalidCollectorStateTransitionError",
    "LiveCollectorNotImplemented",
    "LiveCollectorNotImplementedError",
    "MarketDataCollector",
    "MessageParseError",
    "ParseResult",
    "ParsedControlMessage",
    "RetryPolicy",
    "RunLimits",
    "SessionManifest",
    "SessionStatistics",
    "SinkBackpressureError",
    "SubscriptionState",
    "UnsupportedMessageError",
    "UnsupportedPublicMessage",
    "WebSocketConnection",
    "WebSocketConnector",
    "make_session_id",
    "run_collector",
]
