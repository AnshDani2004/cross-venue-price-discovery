"""Offline collector contracts for public market-data ingestion."""

from typing import TYPE_CHECKING, Any

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
from cross_venue.collectors.sink import InMemoryEventSink, SinkBackpressureError
from cross_venue.collectors.supervision import HeartbeatSupervisor, InactivityTimeoutError
from cross_venue.collectors.transport import WebSocketConnection, WebSocketConnector

if TYPE_CHECKING:
    from cross_venue.collectors.runtime import CollectorRunSummary as CollectorRunSummary
    from cross_venue.collectors.runtime import CollectorRuntimeSpec as CollectorRuntimeSpec
    from cross_venue.collectors.runtime import CollectorStopReason as CollectorStopReason
    from cross_venue.collectors.runtime import RunLimits as RunLimits
    from cross_venue.collectors.runtime import SessionStatistics as SessionStatistics
    from cross_venue.collectors.runtime import SubscriptionState as SubscriptionState
    from cross_venue.collectors.runtime import run_collector as run_collector

_RUNTIME_EXPORTS = frozenset(
    {
        "CollectorRunSummary",
        "CollectorRuntimeSpec",
        "CollectorStopReason",
        "RunLimits",
        "SessionStatistics",
        "SubscriptionState",
        "run_collector",
    }
)


def __getattr__(name: str) -> Any:
    if name in _RUNTIME_EXPORTS:
        from importlib import import_module

        runtime_module = import_module("cross_venue.collectors.runtime")
        value = getattr(runtime_module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
