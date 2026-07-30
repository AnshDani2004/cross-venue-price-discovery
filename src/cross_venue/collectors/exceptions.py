"""Collector exception hierarchy."""

from __future__ import annotations

from collections.abc import Mapping


class CollectorError(Exception):
    """Base exception for collector contracts and parsers."""


class MessageParseError(CollectorError):
    """Raised when a supported public message is malformed."""

    def __init__(self, message: str, *, context: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.context = dict(context or {})


class UnsupportedMessageError(CollectorError):
    """Raised when a caller requests unsupported-message behavior as an exception."""


class InvalidCollectorStateTransitionError(CollectorError):
    """Raised when a lifecycle transition is not allowed."""


class LiveCollectorNotImplementedError(CollectorError):
    """Raised by Phase 2A stubs when live network collection is requested."""


InvalidCollectorStateTransition = InvalidCollectorStateTransitionError
LiveCollectorNotImplemented = LiveCollectorNotImplementedError
