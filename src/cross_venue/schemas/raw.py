"""Raw public market-data message envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cross_venue.schemas.identifiers import Exchange

type JsonValue = object
type JsonObject = dict[str, JsonValue]

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "passphrase",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


def _is_json_compatible(value: object) -> bool:
    if value is None or isinstance(value, bool | int | float | str):
        return True
    if isinstance(value, list):
        return all(_is_json_compatible(child) for child in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_compatible(child) for key, child in value.items()
        )
    return False


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in _SENSITIVE_KEYS or _contains_sensitive_key(child):
                return True
    if isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


class RawMessageEnvelope(BaseModel):
    """Immutable wrapper around one original public exchange payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Exchange
    canonical_instrument: str = Field(min_length=1)
    venue_symbol: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    payload: dict[str, Any]
    local_receipt_ts: datetime
    collector_session_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    exchange_ts: datetime | None = None
    raw_sequence_value: int | str | None = None

    @field_validator("local_receipt_ts", "exchange_ts")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @field_validator("payload")
    @classmethod
    def payload_must_be_safe_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not _is_json_compatible(value):
            raise ValueError("raw payload must be JSON-compatible")
        if _contains_sensitive_key(value):
            raise ValueError("raw public payload must not contain credential fields")
        return value
