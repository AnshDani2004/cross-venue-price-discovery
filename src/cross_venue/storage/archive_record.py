"""Typed exact raw WebSocket frame archival records."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cross_venue.schemas import Exchange

FrameType = Literal["text", "binary"]
FrameEncoding = Literal["utf-8", "base64"]


class RawArchiveRecord(BaseModel):
    """One exact received WebSocket frame plus collection metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archive_schema_version: str = Field(min_length=1)
    record_index: int = Field(ge=0)
    collector_session_id: str = Field(min_length=1)
    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    local_receipt_ts: datetime
    frame_type: FrameType
    frame_encoding: FrameEncoding
    raw_frame: str
    raw_frame_byte_length: int = Field(ge=0)
    message_type: str | None = Field(default=None, min_length=1)
    source_channel: str | None = Field(default=None, min_length=1)
    exchange_ts: datetime | None = None

    @field_validator("local_receipt_ts", "exchange_ts")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("archive timestamps must be timezone-aware")
        return value

    @classmethod
    def from_frame(
        cls,
        frame: str | bytes,
        *,
        archive_schema_version: str,
        record_index: int,
        collector_session_id: str,
        venue: Exchange,
        canonical_instrument: str,
        venue_symbol: str,
        local_receipt_ts: datetime,
    ) -> RawArchiveRecord:
        """Create a record while preserving the exact text or binary frame."""

        if isinstance(frame, str):
            return cls(
                archive_schema_version=archive_schema_version,
                record_index=record_index,
                collector_session_id=collector_session_id,
                venue=venue,
                canonical_instrument=canonical_instrument,
                venue_symbol=venue_symbol,
                local_receipt_ts=local_receipt_ts,
                frame_type="text",
                frame_encoding="utf-8",
                raw_frame=frame,
                raw_frame_byte_length=len(frame.encode("utf-8")),
            )
        return cls(
            archive_schema_version=archive_schema_version,
            record_index=record_index,
            collector_session_id=collector_session_id,
            venue=venue,
            canonical_instrument=canonical_instrument,
            venue_symbol=venue_symbol,
            local_receipt_ts=local_receipt_ts,
            frame_type="binary",
            frame_encoding="base64",
            raw_frame=base64.b64encode(frame).decode("ascii"),
            raw_frame_byte_length=len(frame),
        )

    def frame_bytes(self) -> bytes:
        """Return the archived frame bytes exactly."""

        if self.frame_type == "text":
            return self.raw_frame.encode("utf-8")
        return base64.b64decode(self.raw_frame.encode("ascii"), validate=True)

    def to_json_line(self) -> str:
        """Serialize as one newline-delimited JSON record."""

        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )

    @classmethod
    def from_json_line(cls, line: str) -> RawArchiveRecord:
        """Parse one archive line."""

        return cls.model_validate_json(line)
