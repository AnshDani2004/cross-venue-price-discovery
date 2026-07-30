from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from cross_venue.collectors import CollectorState, SessionManifest, make_session_id
from cross_venue.schemas import Exchange


def aware_ts() -> datetime:
    return datetime(2026, 7, 30, 21, 0, tzinfo=UTC)


def valid_manifest(**overrides: object) -> SessionManifest:
    start = aware_ts()
    data = {
        "session_id": "coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001",
        "venue": Exchange.COINBASE,
        "canonical_instrument": "BTC-USD",
        "venue_symbol": "BTC-USD",
        "channels": ("matches", "ticker", "heartbeat"),
        "started_at": start,
        "ended_at": start + timedelta(minutes=5),
        "final_state": CollectorState.STOPPED,
        "collector_version": "0.1.0",
        "git_commit": "7c4ec6f",
        "schema_version": "0.1.0",
        "message_count": 10,
        "trade_event_count": 3,
        "top_of_book_event_count": 4,
        "control_message_count": 2,
        "unsupported_message_count": 1,
        "parse_error_count": 0,
        "first_local_receipt_ts": start,
        "last_local_receipt_ts": start + timedelta(minutes=5),
        "first_exchange_ts": start,
        "last_exchange_ts": start + timedelta(minutes=5),
    }
    data.update(overrides)
    return SessionManifest.model_validate(data)


def test_valid_completed_session_manifest() -> None:
    manifest = valid_manifest()

    assert manifest.final_state is CollectorState.STOPPED
    assert manifest.message_count == 10


def test_valid_failed_session_manifest_can_be_incomplete() -> None:
    manifest = valid_manifest(
        final_state=CollectorState.FAILED,
        ended_at=None,
        parse_error_count=2,
        first_exchange_ts=None,
        last_exchange_ts=None,
    )

    assert manifest.final_state is CollectorState.FAILED
    assert manifest.ended_at is None


def test_manifest_rejects_negative_counters() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        valid_manifest(message_count=-1)


def test_manifest_rejects_invalid_time_ranges() -> None:
    start = aware_ts()
    with pytest.raises(ValidationError, match="ended_at"):
        valid_manifest(started_at=start, ended_at=start - timedelta(seconds=1))

    with pytest.raises(ValidationError, match="last_local_receipt_ts"):
        valid_manifest(
            first_local_receipt_ts=start,
            last_local_receipt_ts=start - timedelta(seconds=1),
        )

    with pytest.raises(ValidationError, match="last_exchange_ts"):
        valid_manifest(first_exchange_ts=start, last_exchange_ts=start - timedelta(seconds=1))


def test_manifest_rejects_missing_session_id_and_invalid_channels() -> None:
    with pytest.raises(ValidationError, match="String should have at least 1 character"):
        valid_manifest(session_id="")

    with pytest.raises(ValidationError, match="at least 1 item"):
        valid_manifest(channels=())

    with pytest.raises(ValidationError, match="channels must be nonempty"):
        valid_manifest(channels=("trade", ""))


def test_make_session_id_is_deterministic_and_filesystem_safe() -> None:
    session_id = make_session_id(
        venue=Exchange.KRAKEN,
        canonical_instrument="BTC-USD",
        started_at=aware_ts(),
        uuid_factory=lambda: UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert session_id == "kraken_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001"


def test_make_session_id_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_session_id(
            venue=Exchange.KRAKEN,
            canonical_instrument="BTC-USD",
            started_at=datetime(2026, 7, 30, 21, 0),  # noqa: DTZ001
            uuid_factory=lambda: UUID("00000000-0000-0000-0000-000000000001"),
        )
