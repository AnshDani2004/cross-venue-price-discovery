from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from quality_helpers import make_session

from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.calibration import reanalyze_calibrated_pair
from cross_venue.quality.exceptions import QualityError
from cross_venue.quality.io import persist_model_json
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.schemas import Exchange


def test_reanalyze_calibrated_pair_writes_before_after(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)

    result = reanalyze_calibrated_pair(
        paired_path,
        storage_config=storage_config,
        quality_config=quality_config,
        require_clean=False,
    )

    assert result.paired_report.quality_policy_version == "2d.2"
    assert result.comparison_json_path.exists()
    assert result.comparison["old_policy_version"] == "2d.1"
    assert result.comparison["new_policy_version"] == "2d.2"
    assert result.promotion_dry_run_path.exists()


def test_reanalyze_calibrated_pair_rejects_dirty_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)
    monkeypatch.setattr("cross_venue.quality.calibration._working_tree_clean", lambda: False)

    with pytest.raises(QualityError, match="clean working tree"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
        )


def test_reanalyze_calibrated_pair_rejects_wrong_expected_commit(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)

    with pytest.raises(QualityError, match="expected commit"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
            require_clean=False,
            expected_commit="not-the-current-commit",
        )


def test_reanalyze_calibrated_pair_rejects_changed_manifest_hash(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _paired_fixture(tmp_path)
    manifest_path = next(storage_config.archive_root.rglob("session_manifest.json"))
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "coinbase-calibration",
            "coinbase-calibration-mutated",
        ),
        encoding="utf-8",
    )

    with pytest.raises(QualityError, match="source manifest changed"):
        reanalyze_calibrated_pair(
            paired_path,
            storage_config=storage_config,
            quality_config=quality_config,
            require_clean=False,
        )


def _paired_fixture(tmp_path: Path) -> tuple[Path, StorageConfig, DataQualityConfig]:
    coinbase_session, storage_config, original_policy = asyncio.run(
        make_session(tmp_path, venue=Exchange.COINBASE, session_id="coinbase-calibration")
    )
    original_policy = original_policy.model_copy(update={"policy_version": "2d.1"})
    kraken_session, _, _ = asyncio.run(
        make_session(tmp_path, venue=Exchange.KRAKEN, session_id="kraken-calibration")
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=original_policy,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=original_policy,
    )
    paired_report = build_paired_quality_report(
        paired_collection_id="calibration-fixture",
        requested_duration_seconds=2,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=original_policy,
    )
    paired_path = original_policy.report_root / "paired" / "calibration-fixture" / "paired.json"
    persist_model_json(paired_path, paired_report)
    calibrated_policy = original_policy.model_copy(update={"policy_version": "2d.2"})
    return paired_path, storage_config, calibrated_policy
