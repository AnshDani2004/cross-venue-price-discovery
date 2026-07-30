"""Small deterministic parsing helpers for offline venue parsers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from cross_venue.collectors.exceptions import MessageParseError
from cross_venue.schemas.raw import JsonValue


def require_str(payload: Mapping[str, JsonValue], field_name: str) -> str:
    """Return a required string field or raise a parse error."""

    value = payload.get(field_name)
    if not isinstance(value, str) or value == "":
        raise MessageParseError(
            f"missing or invalid field: {field_name}",
            context={"field": field_name},
        )
    return value


def require_mapping(payload: Mapping[str, JsonValue], field_name: str) -> dict[str, JsonValue]:
    """Return a required object field or raise a parse error."""

    value = payload.get(field_name)
    if not isinstance(value, dict):
        raise MessageParseError(
            f"missing or invalid field: {field_name}",
            context={"field": field_name},
        )
    return value


def require_list(payload: Mapping[str, JsonValue], field_name: str) -> list[JsonValue]:
    """Return a required list field or raise a parse error."""

    value = payload.get(field_name)
    if not isinstance(value, list):
        raise MessageParseError(
            f"missing or invalid field: {field_name}",
            context={"field": field_name},
        )
    return value


def parse_decimal(payload: Mapping[str, JsonValue], field_name: str) -> Decimal:
    """Parse a required decimal from a JSON scalar."""

    value = payload.get(field_name)
    if not isinstance(value, int | float | str):
        raise MessageParseError(
            f"missing or invalid decimal field: {field_name}",
            context={"field": field_name},
        )
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise MessageParseError(
            f"invalid decimal field: {field_name}",
            context={"field": field_name},
        ) from exc


def parse_intish(payload: Mapping[str, JsonValue], field_name: str) -> int | str:
    """Return an integer-like identifier while preserving large string IDs."""

    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise MessageParseError(
            f"missing or invalid identifier field: {field_name}",
            context={"field": field_name},
        )
    if isinstance(value, str) and value == "":
        raise MessageParseError(
            f"missing or invalid identifier field: {field_name}",
            context={"field": field_name},
        )
    return value


def parse_rfc3339_timestamp(payload: Mapping[str, JsonValue], field_name: str) -> datetime:
    """Parse an RFC3339 timestamp and require timezone information."""

    timestamp_text = require_str(payload, field_name)
    normalized = timestamp_text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MessageParseError(
            f"invalid timestamp field: {field_name}",
            context={"field": field_name},
        ) from exc
    if parsed.tzinfo is None:
        raise MessageParseError(
            f"timestamp field is timezone-naive: {field_name}",
            context={"field": field_name},
        )
    return parsed


def ensure_timezone_aware(value: datetime, *, field_name: str) -> datetime:
    """Require caller-supplied timestamps to be timezone-aware."""

    if value.tzinfo is None:
        raise MessageParseError(
            f"timestamp field is timezone-naive: {field_name}",
            context={"field": field_name},
        )
    return value
