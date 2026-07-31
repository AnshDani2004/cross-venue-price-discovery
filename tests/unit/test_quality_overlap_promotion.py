from pathlib import Path

import pytest
from quality_helpers import make_session

from cross_venue.quality.aggregation import aggregate_quality_reports
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.models import QualityDisposition
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import PromotionError, promote_dataset
from cross_venue.schemas import Exchange


@pytest.mark.asyncio
async def test_paired_overlap_accepts_clean_pair_and_promotion_dry_run(tmp_path: Path) -> None:
    coinbase_session, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-session",
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-session",
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    paired = build_paired_quality_report(
        paired_collection_id="pair-1",
        requested_duration_seconds=2,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    )
    manifest, message = promote_dataset(paired, quality_config=quality_config, apply=False)

    assert paired.disposition == QualityDisposition.ACCEPTED
    assert paired.overlap.market_event_overlap_duration_seconds == 1
    assert manifest is not None
    assert "dry-run" in message
    applied_manifest, applied_message = promote_dataset(
        paired,
        quality_config=quality_config,
        apply=True,
    )
    assert applied_manifest is not None
    assert "created" in applied_message
    assert (quality_config.validated_manifest_root / "validated-pair-1.json").exists()


@pytest.mark.asyncio
async def test_promotion_blocks_quarantined_or_rejected_pair(tmp_path: Path) -> None:
    coinbase_session, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-session",
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-session",
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )
    paired = build_paired_quality_report(
        paired_collection_id="pair-2",
        requested_duration_seconds=2,
        start_skew_seconds=60,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    )

    assert paired.disposition == QualityDisposition.QUARANTINED
    with pytest.raises(PromotionError, match="paired report is not accepted"):
        promote_dataset(paired, quality_config=quality_config)


@pytest.mark.asyncio
async def test_aggregate_quality_reports_counts_dispositions(tmp_path: Path) -> None:
    coinbase_session, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-session",
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-session",
    )
    reports = (
        analyze_session_quality(
            coinbase_session,
            storage_config=storage_config,
            quality_config=quality_config,
        ),
        analyze_session_quality(
            kraken_session,
            storage_config=storage_config,
            quality_config=quality_config,
        ),
    )

    aggregate = aggregate_quality_reports(reports, quality_config=quality_config)

    assert aggregate.session_count == 2
    assert aggregate.accepted_count == 2
    assert aggregate.total_frames == 4
