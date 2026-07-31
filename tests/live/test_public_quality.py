import os
from pathlib import Path

import pytest

from cross_venue.config import load_data_quality_config, load_storage_config
from cross_venue.quality.collection import collect_paired_quality
from cross_venue.quality.promotion import PromotionError, promote_dataset

pytestmark = pytest.mark.live_quality


def _live_quality_enabled() -> bool:
    return os.environ.get("CROSS_VENUE_ENABLE_LIVE_QUALITY") == "1"


@pytest.mark.asyncio
async def test_public_paired_quality_collection() -> None:
    if not _live_quality_enabled():
        pytest.skip("set CROSS_VENUE_ENABLE_LIVE_QUALITY=1 to run paired public quality test")

    storage_config = load_storage_config(Path("configs/storage.toml"))
    quality_config = load_data_quality_config(Path("configs/data_quality.toml"))
    result = await collect_paired_quality(
        storage_config=storage_config,
        quality_config=quality_config,
        duration_seconds=quality_config.default_controlled_duration_seconds,
        max_messages_per_venue=quality_config.max_messages_per_venue,
    )
    promotion_result = "not attempted"
    try:
        _manifest, promotion_result = promote_dataset(
            result.paired_report,
            quality_config=quality_config,
            apply=False,
        )
    except PromotionError as exc:
        promotion_result = f"blocked: {exc}"

    print(result.to_text())
    print(f"Promotion dry-run result: {promotion_result}")
    print(f"Coinbase findings: {len(result.paired_report.coinbase_report.findings)}")
    print(f"Kraken findings: {len(result.paired_report.kraken_report.findings)}")
    print(f"Paired findings: {len(result.paired_report.findings)}")

    assert result.coinbase_summary.archive_summary is not None
    assert result.kraken_summary.archive_summary is not None
    assert result.paired_report.coinbase_report.archive_validation_passed
    assert result.paired_report.kraken_report.archive_validation_passed
    assert result.paired_report.overlap.requested_duration_seconds <= 300
    assert promotion_result != "not attempted"
