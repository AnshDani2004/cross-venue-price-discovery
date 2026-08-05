"""Shared finite runtime safety limits."""

from __future__ import annotations

MAX_PAIRED_COLLECTION_DURATION_SECONDS = 3600.0
MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE = 100_000


def validate_paired_collection_duration(duration_seconds: float) -> float:
    """Validate a paired public collection duration without clamping."""

    if duration_seconds <= 0:
        raise ValueError("requested collection duration must be positive")
    if duration_seconds > MAX_PAIRED_COLLECTION_DURATION_SECONDS:
        requested = f"{duration_seconds:g}"
        allowed = f"{MAX_PAIRED_COLLECTION_DURATION_SECONDS:g}"
        raise ValueError(
            f"requested collection duration {requested} seconds exceeds "
            f"the configured maximum of {allowed} seconds"
        )
    return duration_seconds


def validate_paired_collection_message_limit(max_messages_per_venue: int) -> int:
    """Validate a paired public collection per-venue message limit."""

    if max_messages_per_venue <= 0:
        raise ValueError("paired collection message limit must be positive")
    if max_messages_per_venue > MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE:
        raise ValueError(
            f"requested paired collection message limit {max_messages_per_venue} exceeds "
            f"the configured maximum of {MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE}"
        )
    return max_messages_per_venue
