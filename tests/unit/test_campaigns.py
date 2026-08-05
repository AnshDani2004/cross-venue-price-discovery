from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from quality_helpers import make_session

from cross_venue.campaigns.config import load_campaign_config
from cross_venue.campaigns.exceptions import CampaignLockError, CampaignValidationError
from cross_venue.campaigns.ledger import read_ledger
from cross_venue.campaigns.locking import CampaignLock
from cross_venue.campaigns.manifest import finalize_campaign_manifest
from cross_venue.campaigns.models import (
    AcceptedPairManifestReference,
    CampaignConfig,
    MissedReason,
    ValidatedCampaignManifest,
)
from cross_venue.campaigns.paths import ledger_path
from cross_venue.campaigns.registry import initialize_campaign, mark_slot_missed
from cross_venue.campaigns.schedule import evaluate_slot_window
from cross_venue.config import NormalizationConfig
from cross_venue.normalization.catalog import build_normalized_catalog
from cross_venue.normalization.determinism import verify_normalization_determinism
from cross_venue.normalization.normalizer import normalize_dataset
from cross_venue.normalization.validation import validate_normalized_dataset
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.io import model_sha256, persist_model_json, portable_relative_path, utc_now
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import build_validated_dataset_manifest
from cross_venue.schemas import Exchange
from cross_venue.storage.checksum import sha256_file


def test_campaign_config_loads_fixed_schedule() -> None:
    config = load_campaign_config(Path("configs/campaigns/phase_3b_btc_usd.toml"))

    assert config.campaign_id == "btc-usd-coinbase-kraken-2026-07-31-v1"
    assert len(config.slots) == 15
    assert config.slots[0].slot_id == "P01"
    assert config.slots[-1].slot_id == "R05"
    assert config.minimum_accepted_sessions == 10


def test_campaign_config_rejects_unknown_and_duplicate_slot(tmp_path: Path) -> None:
    source = Path("configs/campaigns/phase_3b_btc_usd.toml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(source + "\nunknown = true\n", encoding="utf-8")
    with pytest.raises(Exception, match="Extra inputs"):
        load_campaign_config(bad)

    bad.write_text(source.replace('slot_id = "P02"', 'slot_id = "P01"', 1), encoding="utf-8")
    with pytest.raises(Exception, match="duplicate campaign slot IDs"):
        load_campaign_config(bad)


def test_slot_window_boundaries() -> None:
    config = load_campaign_config(Path("configs/campaigns/phase_3b_btc_usd.toml"))
    slot = config.slot_by_id("P01")

    before = evaluate_slot_window(config, slot, now=slot.planned_start_utc - timedelta(seconds=301))
    early = evaluate_slot_window(config, slot, now=slot.planned_start_utc - timedelta(seconds=300))
    exact = evaluate_slot_window(config, slot, now=slot.planned_start_utc)
    late = evaluate_slot_window(config, slot, now=slot.planned_start_utc + timedelta(seconds=900))
    after = evaluate_slot_window(config, slot, now=slot.planned_start_utc + timedelta(seconds=901))

    assert not before.executable
    assert early.executable
    assert exact.executable
    assert late.executable
    assert not after.executable
    assert after.passed


def test_campaign_initialize_mark_missed_and_ledger_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    config = _temp_campaign_config(tmp_path)

    registry = initialize_campaign(
        config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml")
    )
    assert registry.campaign_status.value == "IN_PROGRESS"

    registry = mark_slot_missed(config, slot_id="P01", reason=MissedReason.IMPLEMENTATION_NOT_READY)
    assert registry.planned_slots["P01"].status.value == "MISSED"

    events = read_ledger(ledger_path(config))
    assert events[0].event_type.value == "CAMPAIGN_INITIALIZED"
    assert events[1].event_type.value == "SLOT_MARKED_MISSED"

    ledger = ledger_path(config)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    with pytest.raises(CampaignValidationError):
        read_ledger(ledger)


def test_campaign_lock_rejects_concurrent(tmp_path: Path) -> None:
    config = _temp_campaign_config(tmp_path)
    with (
        CampaignLock(config, slot_id="P01", campaign_attempt_id="attempt-1"),
        pytest.raises(CampaignLockError),
    ):
        _acquire_second_lock(config)


def test_incomplete_campaign_manifest_finalization_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    config = _temp_campaign_config(tmp_path)
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))

    with pytest.raises(Exception, match="incomplete campaign"):
        finalize_campaign_manifest(config)


def test_synthetic_campaign_manifest_normalizes_two_pairs(tmp_path: Path) -> None:
    manifest_path, storage_config, quality_config, normalization_config = asyncio.run(
        _campaign_manifest_fixture(tmp_path, pair_count=2)
    )

    result = normalize_dataset(
        manifest_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )

    assert not isinstance(result, dict)
    assert result.manifest["validated_campaign_manifest_id"] == (
        "validated-campaign-btc-usd-coinbase-kraken-2026-07-31-v1"
    )
    assert (
        result.manifest["raw_record_outcome_row_count"]
        == result.manifest["source_raw_record_count"]
    )
    validation = validate_normalized_dataset(result.normalization_manifest_path)
    assert validation["validation_status"] == "VALID"
    catalog = build_normalized_catalog(result.normalization_manifest_path)
    assert catalog["catalog_status"] == "BUILT"
    determinism = verify_normalization_determinism(
        manifest_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
    )
    assert determinism["determinism_status"] == "PASSED"


@pytest.mark.local_campaign_data
def test_local_campaign_data_opt_in_marker() -> None:
    if os.getenv("CROSS_VENUE_ENABLE_LOCAL_CAMPAIGN_DATA") != "1":
        pytest.skip("local campaign-data validation is opt-in")
    assert Path("data/quality/paired").exists()


@pytest.mark.campaign_smoke
def test_campaign_smoke_opt_in_marker() -> None:
    if os.getenv("CROSS_VENUE_ENABLE_CAMPAIGN_SMOKE") != "1":
        pytest.skip("campaign smoke collection is opt-in")
    pytest.skip("run CLI smoke collection manually after infrastructure commit is frozen")


def _temp_campaign_config(tmp_path: Path) -> CampaignConfig:
    config = load_campaign_config(Path("configs/campaigns/phase_3b_btc_usd.toml"))
    payload = config.model_dump(mode="python")
    payload.update(
        {
            "registry_root": tmp_path / "campaigns",
            "validated_manifest_root": tmp_path / "validated",
            "normalized_output_root": tmp_path / "normalized",
        }
    )
    return CampaignConfig.model_validate(payload)


def _acquire_second_lock(config: CampaignConfig) -> None:
    with CampaignLock(config, slot_id="P01", campaign_attempt_id="attempt-2"):
        pass


async def _campaign_manifest_fixture(
    tmp_path: Path,
    *,
    pair_count: int,
) -> tuple[Path, object, object, NormalizationConfig]:
    pair_entries: list[AcceptedPairManifestReference] = []
    storage_config = None
    quality_config = None
    for index in range(pair_count):
        coinbase_session, storage_config, quality_config = await make_session(
            tmp_path,
            venue=Exchange.COINBASE,
            session_id=f"coinbase-campaign-{index}",
        )
        kraken_session, _, _ = await make_session(
            tmp_path,
            venue=Exchange.KRAKEN,
            session_id=f"kraken-campaign-{index}",
        )
        quality_config = quality_config.model_copy(update={"policy_version": "2d.2"})
        pair_id = f"paired-campaign-{index}"
        pair_root = quality_config.report_root / "paired" / pair_id
        coinbase_path = pair_root / "coinbase.json"
        kraken_path = pair_root / "kraken.json"
        paired_path = pair_root / "paired_quality_report.json"
        coinbase_report = analyze_session_quality(
            coinbase_session,
            storage_config=storage_config,
            quality_config=quality_config,
            report_path=coinbase_path,
        ).model_copy(
            update={
                "report_relative_path": portable_relative_path(
                    quality_config.report_root, coinbase_path
                )
            }
        )
        kraken_report = analyze_session_quality(
            kraken_session,
            storage_config=storage_config,
            quality_config=quality_config,
            report_path=kraken_path,
        ).model_copy(
            update={
                "report_relative_path": portable_relative_path(
                    quality_config.report_root, kraken_path
                )
            }
        )
        persist_model_json(coinbase_path, coinbase_report)
        persist_model_json(kraken_path, kraken_report)
        paired_report = build_paired_quality_report(
            paired_collection_id=pair_id,
            requested_duration_seconds=2,
            start_skew_seconds=0,
            coinbase_report=coinbase_report,
            kraken_report=kraken_report,
            quality_config=quality_config,
        ).model_copy(
            update={
                "paired_report_relative_path": portable_relative_path(
                    quality_config.report_root, paired_path
                )
            }
        )
        persist_model_json(paired_path, paired_report)
        validated = build_validated_dataset_manifest(paired_report, quality_config=quality_config)
        validated_path = (
            quality_config.validated_manifest_root / f"{validated.dataset_manifest_id}.json"
        )
        persist_model_json(validated_path, validated)
        pair_entries.append(
            # The synthetic dates only prove deterministic campaign ordering; they are not
            # research evidence.
            AcceptedPairManifestReference(
                slot_id=f"P{index + 1:02d}",
                campaign_attempt_id=f"attempt-{index + 1:03d}",
                planned_start_utc=datetime(2026, 7, 31, 14, tzinfo=UTC) + timedelta(days=index),
                actual_start_utc=datetime(2026, 7, 31, 14, tzinfo=UTC) + timedelta(days=index),
                time_bucket="MORNING",
                paired_collection_id=pair_id,
                validated_pair_manifest_id=validated.dataset_manifest_id,
                validated_pair_manifest_relative_path=portable_relative_path(
                    quality_config.validated_manifest_root, validated_path
                ),
                validated_pair_manifest_sha256=sha256_file(validated_path),
                paired_overlap_seconds=paired_report.overlap.market_event_overlap_duration_seconds,
                coinbase_session_id=coinbase_report.session_id,
                kraken_session_id=kraken_report.session_id,
                source_manifest_hashes=validated.raw_manifest_hashes,
                source_shard_checksums={
                    coinbase_report.session_id: dict(coinbase_report.input_shard_checksums),
                    kraken_report.session_id: dict(kraken_report.input_shard_checksums),
                },
                quality_report_hashes=validated.session_quality_report_hashes,
            )
        )
    assert storage_config is not None
    assert quality_config is not None
    campaign = ValidatedCampaignManifest(
        validated_campaign_manifest_version="3b.1",
        validated_campaign_manifest_id="validated-campaign-btc-usd-coinbase-kraken-2026-07-31-v1",
        campaign_id="btc-usd-coinbase-kraken-2026-07-31-v1",
        campaign_schema_version="3b.1",
        created_at=utc_now(),
        campaign_runtime_commit="synthetic",
        finalization_commit="synthetic",
        campaign_config_sha256="0" * 64,
        quality_policy_version="2d.2",
        quality_policy_sha256="0" * 64,
        campaign_registry_sha256="0" * 64,
        campaign_ledger_sha256="0" * 64,
        instrument="BTC-USD",
        venues=(Exchange.COINBASE, Exchange.KRAKEN),
        timezone="America/New_York",
        accepted_attempt_count=len(pair_entries),
        accepted_overlap_seconds=sum(entry.paired_overlap_seconds for entry in pair_entries),
        accepted_calendar_dates=("2026-07-31", "2026-08-01"),
        accepted_time_buckets=("MORNING",),
        all_attempt_counts_by_status={"ACCEPTED": len(pair_entries)},
        all_slot_counts_by_status={"ACCEPTED": len(pair_entries)},
        accepted_pair_manifests=tuple(pair_entries),
        excluded_attempt_summary=(),
        minimum_requirements={},
        completion_evidence={"label": "NON_RESEARCH_SMOKE"},
    )
    campaign = campaign.model_copy(update={"content_hash": model_sha256(campaign)})
    campaign_path = (
        quality_config.validated_manifest_root / f"{campaign.validated_campaign_manifest_id}.json"
    )
    persist_model_json(campaign_path, campaign)
    normalization_config = NormalizationConfig(
        normalization_schema_version="3a.1",
        output_root=tmp_path / "normalized",
        parquet_compression="zstd",
        parquet_compression_level=6,
        parquet_row_group_size=50_000,
        decimal_precision=38,
        decimal_scale=18,
        timestamp_unit="ns",
        preserve_raw_duplicates=True,
        write_raw_record_outcomes=True,
        write_duckdb_catalog=True,
        require_validated_manifest=True,
        require_quality_policy_version="2d.2",
        require_clean_working_tree_for_final_run=True,
    )
    return campaign_path, storage_config, quality_config, normalization_config
