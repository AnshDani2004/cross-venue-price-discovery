"""Atomic persistent data-quality summaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cross_venue.storage.exceptions import QualityPersistenceError
from cross_venue.storage.manifest_store import atomic_write_json


class QualitySummary(BaseModel):
    """Observed quality counters for one raw archive session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frames_received: int = Field(ge=0)
    json_decode_failures: int = Field(ge=0)
    parse_failures: int = Field(ge=0)
    unsupported_messages: int = Field(ge=0)
    wrong_symbol_messages: int = Field(ge=0)
    exchange_errors: int = Field(ge=0)
    timestamp_validation_failures: int = Field(ge=0)
    nonmonotonic_local_receipt_timestamps: int = Field(ge=0)
    coinbase_sequence_observations: int = Field(ge=0)
    coinbase_sequence_gaps: int = Field(ge=0)
    kraken_trade_id_observations: int = Field(ge=0)
    duplicate_sequence_values: int = Field(ge=0)
    first_local_receipt_ts: datetime | None = None
    last_local_receipt_ts: datetime | None = None
    session_duration_seconds: float = Field(ge=0)
    frame_rate_per_second: float = Field(ge=0)
    trade_event_rate_per_second: float = Field(ge=0)
    top_of_book_event_rate_per_second: float = Field(ge=0)
    reconnect_count: int = Field(ge=0)
    partial_shard_count: int = Field(ge=0)
    checksum_failures: int = Field(ge=0)
    writer_failures: int = Field(ge=0)
    recovery_actions: int = Field(ge=0)

    @field_validator("first_local_receipt_ts", "last_local_receipt_ts")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("quality timestamps must be timezone-aware")
        return value


def persist_quality_summary(path: Path, summary: QualitySummary) -> None:
    """Persist a quality summary atomically."""

    try:
        atomic_write_json(path, summary.model_dump(mode="json"))
    except Exception as exc:
        raise QualityPersistenceError(f"could not persist {path.name}") from exc


def load_quality_summary(path: Path) -> QualitySummary:
    """Load and validate a quality summary."""

    return QualitySummary.model_validate_json(path.read_text(encoding="utf-8"))
