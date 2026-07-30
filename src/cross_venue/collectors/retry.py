"""Bounded retry and backoff policy for public collectors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Validated exponential backoff settings."""

    initial_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    max_attempts: int = 5
    jitter_fraction: float = 0.0
    stable_reset_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial delay must be positive")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least 1")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("maximum delay must be at least the initial delay")
        if self.max_attempts < 0:
            raise ValueError("maximum attempts must be nonnegative")
        if not 0 <= self.jitter_fraction <= 1:
            raise ValueError("jitter fraction must be between 0 and 1")
        if self.stable_reset_seconds <= 0:
            raise ValueError("stable reset interval must be positive")

    def delay_for_attempt(
        self,
        attempt_number: int,
        *,
        jitter_source: Callable[[], float] = lambda: 0.0,
    ) -> float:
        """Return bounded delay for a 1-based retry attempt."""

        if attempt_number <= 0:
            raise ValueError("attempt number must be positive")
        delay = min(
            self.initial_delay_seconds * (self.multiplier ** (attempt_number - 1)),
            self.max_delay_seconds,
        )
        if self.jitter_fraction == 0:
            return delay
        jitter_value = min(max(jitter_source(), 0.0), 1.0)
        return delay + delay * self.jitter_fraction * jitter_value
