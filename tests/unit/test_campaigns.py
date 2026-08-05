from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from quality_helpers import make_session

from cross_venue.campaigns.config import load_campaign_config
from cross_venue.campaigns.exceptions import CampaignLockError, CampaignValidationError
from cross_venue.campaigns.ledger import read_ledger
from cross_venue.campaigns.locking import CampaignLock
from cross_venue.campaigns.manifest import finalize_campaign_manifest
from cross_venue.campaigns.migration import migrate_campaign_runtime
from cross_venue.campaigns.models import (
    AcceptedPairManifestReference,
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    CampaignRole,
    LedgerEventType,
    MissedReason,
    RuntimeMigrationReason,
    SlotType,
    ValidatedCampaignManifest,
    validate_campaign_id,
)
from cross_venue.campaigns.paths import ledger_path, lock_path, registry_path
from cross_venue.campaigns.registry import (
    initialize_campaign,
    mark_slot_missed,
    record_attempt_event,
)
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
    assert config.campaign_role == CampaignRole.MULTI_DAY_VALIDATION
    assert len(config.slots) == 15
    assert config.slots[0].slot_id == "P01"
    assert config.slots[-1].slot_id == "R05"
    assert config.minimum_accepted_sessions == 10


@pytest.mark.parametrize(
    "campaign_id",
    [
        "btc-usd-coinbase-kraken-2026-07-31-v1",
        "btc-usd-coinbase-kraken-2026-07-31-intraday-v1",
        "eth-usd-example-2026-08-01-v2",
    ],
)
def test_campaign_id_validation_accepts_safe_ids(campaign_id: str) -> None:
    assert validate_campaign_id(campaign_id) == campaign_id


@pytest.mark.parametrize(
    "campaign_id",
    [
        "",
        "ABc",
        "/absolute",
        "btc/usd",
        "btc\\usd",
        "../btc",
        "btc..usd",
        "-btc",
        "btc-",
        "a" * 129,
    ],
)
def test_campaign_id_validation_rejects_unsafe_ids(campaign_id: str) -> None:
    with pytest.raises(ValidationError):
        validate_campaign_id(campaign_id)


def test_generic_slot_invariants_accept_multiple_campaign_shapes(tmp_path: Path) -> None:
    CampaignConfig.model_validate(_campaign_payload(tmp_path, primary_count=10, reserve_count=5))
    intraday = CampaignConfig.model_validate(
        _campaign_payload(
            tmp_path,
            campaign_id="btc-usd-coinbase-kraken-2026-07-31-intraday-v1",
            role=CampaignRole.EXPLORATORY_INTRADAY,
            primary_count=10,
            reserve_count=2,
            minimum_calendar_dates=1,
            minimum_time_buckets=1,
        )
    )
    assert intraday.campaign_role == CampaignRole.EXPLORATORY_INTRADAY
    assert len(intraday.slots) == 12
    CampaignConfig.model_validate(
        _campaign_payload(
            tmp_path,
            campaign_id="development-smoke-2026-07-31",
            role=CampaignRole.DEVELOPMENT_SMOKE,
            primary_count=1,
            reserve_count=0,
            minimum_accepted_sessions=1,
            minimum_calendar_dates=1,
            minimum_time_buckets=1,
        )
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload.update({"minimum_accepted_sessions": 16}), "total planned slots"),
        (
            lambda payload: payload["slots"][1].update({"slot_id": "P01"}),
            "duplicate campaign slot IDs",
        ),
        (
            lambda payload: payload["slots"][1].update(
                {"planned_start_utc": payload["slots"][0]["planned_start_utc"]}
            ),
            "duplicate campaign slot timestamps",
        ),
        (
            lambda payload: [
                slot.update({"slot_type": SlotType.RESERVE}) for slot in payload["slots"]
            ],
            "at least one primary",
        ),
        (lambda payload: payload.update({"maximum_attempts": 14}), "maximum attempts"),
    ],
)
def test_generic_slot_invariants_reject_invalid_shapes(
    tmp_path: Path,
    mutation: Any,
    match: str,
) -> None:
    payload = _campaign_payload(tmp_path)
    mutation(payload)
    with pytest.raises(Exception, match=match):
        CampaignConfig.model_validate(payload)


def test_campaign_roles_are_typed_and_legacy_role_defaults(tmp_path: Path) -> None:
    legacy = _campaign_payload(tmp_path)
    legacy.pop("campaign_role")
    assert CampaignConfig.model_validate(legacy).campaign_role == CampaignRole.MULTI_DAY_VALIDATION

    unknown = _campaign_payload(tmp_path)
    unknown["campaign_role"] = "UNKNOWN"
    with pytest.raises(ValidationError):
        CampaignConfig.model_validate(unknown)

    smoke = _campaign_payload(
        tmp_path,
        campaign_id="development-smoke-2026-07-31",
        role=CampaignRole.DEVELOPMENT_SMOKE,
    )
    with pytest.raises(Exception, match="development smoke"):
        CampaignConfig.model_validate(smoke)


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


def test_two_campaigns_are_isolated_in_one_registry_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    validation_config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    intraday_config = CampaignConfig.model_validate(
        _campaign_payload(
            tmp_path,
            campaign_id="btc-usd-coinbase-kraken-2026-07-31-intraday-v1",
            role=CampaignRole.EXPLORATORY_INTRADAY,
            primary_count=10,
            reserve_count=2,
            minimum_calendar_dates=1,
            minimum_time_buckets=1,
        )
    )

    validation = initialize_campaign(
        validation_config,
        config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"),
    )
    intraday = initialize_campaign(
        intraday_config,
        config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"),
    )

    assert registry_path(validation_config) != registry_path(intraday_config)
    assert ledger_path(validation_config) != ledger_path(intraday_config)
    assert lock_path(validation_config) != lock_path(intraday_config)
    assert validation.campaign_role == CampaignRole.MULTI_DAY_VALIDATION
    assert intraday.campaign_role == CampaignRole.EXPLORATORY_INTRADAY

    mark_slot_missed(
        validation_config,
        slot_id="P01",
        reason=MissedReason.USER_UNAVAILABLE,
    )
    mark_slot_missed(
        intraday_config,
        slot_id="P01",
        reason=MissedReason.CAMPAIGN_INITIALIZED_AFTER_SLOT_WINDOW,
    )

    validation_events = read_ledger(ledger_path(validation_config))
    intraday_events = read_ledger(ledger_path(intraday_config))
    assert {event.campaign_id for event in validation_events} == {validation_config.campaign_id}
    assert {event.campaign_id for event in intraday_events} == {intraday_config.campaign_id}


def test_runtime_migration_allowed_after_missed_slot_before_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    mark_slot_missed(config, slot_id="P01", reason=MissedReason.USER_UNAVAILABLE)

    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "1" * 40)
    report = migrate_campaign_runtime(
        config,
        reason=RuntimeMigrationReason.GENERIC_ENGINE_BEFORE_FIRST_COLLECTION,
    )

    assert report["old_runtime_commit"] == "0" * 40
    assert report["new_runtime_commit"] == "1" * 40
    events = read_ledger(ledger_path(config))
    assert events[-1].event_type == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED
    with pytest.raises(Exception, match="already been migrated"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.GENERIC_ENGINE_BEFORE_FIRST_COLLECTION,
        )


def test_runtime_migration_blocked_after_attempt_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "1" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    record_attempt_event(
        config,
        event_type=LedgerEventType.ATTEMPT_STARTED,
        attempt=_started_attempt(config),
    )

    with pytest.raises(Exception, match="after an attempt starts"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.GENERIC_ENGINE_BEFORE_FIRST_COLLECTION,
        )


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


def _campaign_payload(
    tmp_path: Path,
    *,
    campaign_id: str = "btc-usd-coinbase-kraken-2026-07-31-v1",
    role: CampaignRole = CampaignRole.MULTI_DAY_VALIDATION,
    primary_count: int = 10,
    reserve_count: int = 5,
    minimum_accepted_sessions: int = 10,
    minimum_calendar_dates: int = 3,
    minimum_time_buckets: int = 3,
) -> dict[str, Any]:
    config = load_campaign_config(Path("configs/campaigns/phase_3b_btc_usd.toml"))
    payload = config.model_dump(mode="python")
    total_slots = primary_count + reserve_count
    starts = [
        datetime(2026, 7, 31, 14, tzinfo=UTC) + timedelta(hours=index)
        for index in range(total_slots)
    ]
    slots: list[dict[str, Any]] = []
    buckets = ("MORNING", "AFTERNOON", "EVENING")
    for index, planned_start in enumerate(starts):
        is_primary = index < primary_count
        slot_id = f"P{index + 1:02d}" if is_primary else f"R{index - primary_count + 1:02d}"
        slots.append(
            {
                "slot_id": slot_id,
                "slot_type": SlotType.PRIMARY if is_primary else SlotType.RESERVE,
                "planned_start_utc": planned_start,
                "planned_start_local": f"{planned_start.date().isoformat()} 10:00 America/New_York",
                "time_bucket": buckets[index % len(buckets)],
            }
        )
    payload.update(
        {
            "campaign_schema_version": "3b.2",
            "campaign_id": campaign_id,
            "campaign_role": role,
            "minimum_accepted_sessions": minimum_accepted_sessions,
            "minimum_calendar_dates": minimum_calendar_dates,
            "minimum_time_buckets": minimum_time_buckets,
            "maximum_attempts": total_slots,
            "registry_root": tmp_path / "campaigns",
            "validated_manifest_root": tmp_path / "validated",
            "normalized_output_root": tmp_path / "normalized",
            "slots": slots,
        }
    )
    return deepcopy(payload)


def _started_attempt(config: CampaignConfig) -> AttemptSummary:
    slot = config.slot_by_id("P01")
    return AttemptSummary(
        campaign_id=config.campaign_id,
        slot_id=slot.slot_id,
        attempt_number=1,
        campaign_attempt_id=f"{config.campaign_id}-P01-001",
        slot_type=slot.slot_type,
        planned_start_utc=slot.planned_start_utc,
        planned_start_local=slot.planned_start_local,
        time_bucket=slot.time_bucket,
        actual_started_at=slot.planned_start_utc,
        requested_duration_seconds=config.requested_duration_seconds,
        attempt_status=AttemptStatus.STARTED,
        exclusion_reason="attempt not complete",
    )


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
