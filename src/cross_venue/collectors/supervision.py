"""Heartbeat and liveness supervision for live public collectors."""

from __future__ import annotations

from dataclasses import dataclass


class InactivityTimeoutError(TimeoutError):
    """Raised when no frame arrives within the configured liveness window."""


@dataclass(slots=True)
class HeartbeatSupervisor:
    """Track monotonic liveness timestamps."""

    inactivity_timeout_seconds: float
    last_frame_monotonic: float
    last_control_monotonic: float | None = None
    last_market_event_monotonic: float | None = None

    def __post_init__(self) -> None:
        if self.inactivity_timeout_seconds <= 0:
            raise ValueError("inactivity timeout must be positive")

    def record_frame(self, monotonic_time: float) -> None:
        """Record any received frame."""

        self.last_frame_monotonic = monotonic_time

    def record_control(self, monotonic_time: float) -> None:
        """Record heartbeat, subscription, status, or other control liveness."""

        self.last_control_monotonic = monotonic_time

    def record_market_event(self, monotonic_time: float) -> None:
        """Record normalized market-event liveness."""

        self.last_market_event_monotonic = monotonic_time

    def check(self, monotonic_time: float) -> None:
        """Raise if the connection has been inactive for too long."""

        if monotonic_time - self.last_frame_monotonic > self.inactivity_timeout_seconds:
            raise InactivityTimeoutError("no WebSocket frames within inactivity timeout")
