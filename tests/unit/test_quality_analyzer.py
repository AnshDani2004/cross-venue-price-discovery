from pathlib import Path

import pytest
from quality_helpers import (
    coinbase_ticker,
    coinbase_trade,
    kraken_ticker,
    kraken_trade,
    make_session,
)

from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.models import QualityDisposition
from cross_venue.schemas import Exchange


@pytest.mark.asyncio
async def test_session_quality_accepts_clean_synthetic_archive(tmp_path: Path) -> None:
    session_path, storage_config, quality_config = await make_session(tmp_path)

    report = analyze_session_quality(
        session_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert report.disposition == QualityDisposition.ACCEPTED
    assert report.archive_validation_passed
    assert report.metrics.coverage.raw_records == 2
    assert report.metrics.continuity.kraken_ticker_sequence_checks_skipped


@pytest.mark.asyncio
async def test_duplicate_raw_frame_quarantines_session(tmp_path: Path) -> None:
    duplicate = coinbase_ticker(2, 1)
    session_path, storage_config, quality_config = await make_session(
        tmp_path,
        frames=(coinbase_trade(1, 1, 0), duplicate, duplicate),
    )

    report = analyze_session_quality(
        session_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert report.disposition == QualityDisposition.QUARANTINED
    assert report.metrics.duplicates.exact_raw_duplicate_count == 1
    assert any(finding.finding_id == "DUPLICATES_RAW_FRAME_RATE" for finding in report.findings)


@pytest.mark.asyncio
async def test_locked_quote_rejects_session_without_rewriting_raw(tmp_path: Path) -> None:
    session_path, storage_config, quality_config = await make_session(
        tmp_path,
        frames=(coinbase_trade(1, 1, 0), coinbase_ticker(2, 1, bid="100.00", ask="100.00")),
    )

    report = analyze_session_quality(
        session_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert report.disposition == QualityDisposition.REJECTED
    assert report.metrics.quotes.locked_market_count == 1
    assert any(finding.finding_id == "QUOTES_LOCKED_OR_CROSSED" for finding in report.findings)


@pytest.mark.asyncio
async def test_checksum_mismatch_forces_rejection(tmp_path: Path) -> None:
    session_path, storage_config, quality_config = await make_session(tmp_path)
    shard_path = next((session_path / "raw").glob("*.jsonl"))
    with shard_path.open("a", encoding="utf-8") as file_handle:
        file_handle.write("\n")

    report = analyze_session_quality(
        session_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert report.disposition == QualityDisposition.REJECTED
    assert not report.archive_validation_passed


@pytest.mark.asyncio
async def test_kraken_trade_id_duplicates_are_trade_specific(tmp_path: Path) -> None:
    session_path, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        frames=(kraken_trade(1, 0), kraken_ticker(1), kraken_trade(1, 2)),
    )

    report = analyze_session_quality(
        session_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert report.metrics.continuity.kraken_duplicate_trade_id_count == 1
    assert report.metrics.continuity.kraken_ticker_sequence_checks_skipped
