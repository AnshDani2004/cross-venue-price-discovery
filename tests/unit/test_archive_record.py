from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cross_venue.schemas import Exchange
from cross_venue.storage.archive_record import RawArchiveRecord


def _timestamp() -> datetime:
    return datetime(2026, 7, 30, 21, 0, tzinfo=UTC)


def test_raw_archive_record_preserves_exact_text_frame() -> None:
    frame = '{"type":"ticker","product_id":"BTC-USD","note":"line\\nkept"}'

    record = RawArchiveRecord.from_frame(
        frame,
        archive_schema_version="0.1.0",
        record_index=7,
        collector_session_id="session-1",
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        local_receipt_ts=_timestamp(),
    )

    assert record.frame_type == "text"
    assert record.frame_encoding == "utf-8"
    assert record.raw_frame == frame
    assert record.frame_bytes() == frame.encode("utf-8")
    assert record.raw_frame_byte_length == len(frame.encode("utf-8"))


def test_raw_archive_record_preserves_binary_frame_losslessly() -> None:
    frame = b"\x00\xffbinary-json-ish"

    record = RawArchiveRecord.from_frame(
        frame,
        archive_schema_version="0.1.0",
        record_index=0,
        collector_session_id="session-1",
        venue=Exchange.KRAKEN,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC/USD",
        local_receipt_ts=_timestamp(),
    )

    assert record.frame_type == "binary"
    assert record.frame_encoding == "base64"
    assert record.frame_bytes() == frame
    assert record.raw_frame_byte_length == len(frame)


def test_raw_archive_record_jsonl_round_trip_is_one_line() -> None:
    record = RawArchiveRecord.from_frame(
        '{"event":"synthetic"}',
        archive_schema_version="0.1.0",
        record_index=0,
        collector_session_id="session-1",
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        local_receipt_ts=_timestamp(),
    )

    line = record.to_json_line()
    assert line.endswith("\n")
    assert line.count("\n") == 1
    assert RawArchiveRecord.from_json_line(line) == record


def test_raw_archive_record_rejects_naive_timestamps_and_extra_fields() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        RawArchiveRecord.from_frame(
            "{}",
            archive_schema_version="0.1.0",
            record_index=0,
            collector_session_id="session-1",
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            local_receipt_ts=datetime(2026, 7, 30, 21, 0),  # noqa: DTZ001
        )

    payload = {
        "archive_schema_version": "0.1.0",
        "record_index": 0,
        "collector_session_id": "session-1",
        "venue": "coinbase",
        "canonical_instrument": "BTC-USD",
        "venue_symbol": "BTC-USD",
        "local_receipt_ts": _timestamp().isoformat(),
        "frame_type": "text",
        "frame_encoding": "utf-8",
        "raw_frame": "{}",
        "raw_frame_byte_length": 2,
        "unexpected": "field",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RawArchiveRecord.model_validate(payload)
