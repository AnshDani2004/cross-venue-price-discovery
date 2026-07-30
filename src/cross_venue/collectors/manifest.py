"""Session identifiers and manifest models for future collector runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.schemas import Exchange


class SessionManifest(BaseModel):
    """Typed summary of one collector session.

    This model intentionally performs no file I/O in Phase 2A.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    channels: tuple[str, ...] = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    final_state: CollectorState
    collector_version: str = Field(min_length=1)
    git_commit: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    message_count: int = Field(ge=0)
    trade_event_count: int = Field(ge=0)
    top_of_book_event_count: int = Field(ge=0)
    control_message_count: int = Field(ge=0)
    unsupported_message_count: int = Field(ge=0)
    parse_error_count: int = Field(ge=0)
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None
    first_exchange_ts: datetime | None = None
    last_exchange_ts: datetime | None = None

    @field_validator(
        "started_at",
        "ended_at",
        "first_local_receipt_ts",
        "last_local_receipt_ts",
        "first_exchange_ts",
        "last_exchange_ts",
    )
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("manifest timestamps must be timezone-aware")
        return value

    @field_validator("channels")
    @classmethod
    def channels_must_be_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(channel.strip() == "" for channel in value):
            raise ValueError("channels must be nonempty")
        return value

    @model_validator(mode="after")
    def timestamps_must_be_ordered(self) -> SessionManifest:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        if (
            self.first_local_receipt_ts is not None
            and self.last_local_receipt_ts is not None
            and self.last_local_receipt_ts < self.first_local_receipt_ts
        ):
            raise ValueError("last_local_receipt_ts must not be before first_local_receipt_ts")
        if (
            self.first_exchange_ts is not None
            and self.last_exchange_ts is not None
            and self.last_exchange_ts < self.first_exchange_ts
        ):
            raise ValueError("last_exchange_ts must not be before first_exchange_ts")
        return self


def make_session_id(
    *,
    venue: Exchange,
    canonical_instrument: str,
    started_at: datetime,
    uuid_factory: Callable[[], UUID],
) -> str:
    """Return a deterministic, filesystem-safe, collision-resistant session ID."""

    if started_at.tzinfo is None:
        raise ValueError("started_at must be timezone-aware")
    started_at_utc = started_at.astimezone(UTC)
    timestamp = started_at_utc.strftime("%Y%m%dT%H%M%SZ")
    safe_instrument = canonical_instrument.replace("/", "-").replace(" ", "-")
    return f"{venue.value}_{safe_instrument}_{timestamp}_{uuid_factory()}"
