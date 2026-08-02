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

from cross_venue.campaigns.composite import (
    COMPOSITE_EXPLORATORY_LABEL,
    build_composite_exploratory_dataset,
)
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
    FailureClassification,
    InclusionStatus,
    LedgerEventType,
    MissedReason,
    RuntimeMigrationReason,
    SlotType,
    ValidatedCampaignManifest,
    validate_campaign_id,
)
from cross_venue.campaigns.paths import ledger_path, lock_path, registry_path
from cross_venue.campaigns.registry import (
    campaign_status_payload,
    initialize_campaign,
    mark_slot_missed,
    record_attempt_event,
)
from cross_venue.campaigns.schedule import evaluate_slot_window
from cross_venue.campaigns.validation import validate_campaign
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


def test_intraday_continuation_config_loads_supplemental_schedule() -> None:
    config = load_campaign_config(
        Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml")
    )

    assert config.campaign_id == ("btc-usd-coinbase-kraken-2026-08-intraday-continuation-v1")
    assert config.campaign_role == CampaignRole.EXPLORATORY_INTRADAY
    assert config.requested_duration_seconds == 1860
    assert config.maximum_messages_per_venue == 100_000
    assert config.minimum_overlap_seconds_per_accepted_session == 1800
    assert config.minimum_accepted_sessions == 2
    assert config.minimum_total_accepted_overlap_seconds == 3600
    assert config.minimum_calendar_dates == 2
    assert config.minimum_time_buckets == 2
    assert sum(slot.slot_type == SlotType.PRIMARY for slot in config.slots) == 3
    assert sum(slot.slot_type == SlotType.RESERVE for slot in config.slots) == 2
    assert [slot.slot_id for slot in config.slots] == ["S01", "S02", "S03", "R01", "R02"]
    assert {slot.time_bucket.value for slot in config.slots} == {"MORNING", "EVENING"}


def test_intraday_continuation_schedule_avoids_remaining_multi_day_slots() -> None:
    config = load_campaign_config(
        Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml")
    )
    remaining_multi_day_chicago_slots_utc = [
        datetime(2026, 8, 2, 20, tzinfo=UTC),
        datetime(2026, 8, 3, 2, tzinfo=UTC),
        datetime(2026, 8, 3, 14, tzinfo=UTC),
        datetime(2026, 8, 3, 20, tzinfo=UTC),
        datetime(2026, 8, 4, 2, tzinfo=UTC),
        datetime(2026, 8, 4, 14, tzinfo=UTC),
        datetime(2026, 8, 4, 20, tzinfo=UTC),
        datetime(2026, 8, 5, 2, tzinfo=UTC),
    ]
    conservative_buffer = timedelta(hours=2)

    for supplemental_slot in config.slots:
        for multi_day_start in remaining_multi_day_chicago_slots_utc:
            assert abs(supplemental_slot.planned_start_utc - multi_day_start) >= (
                timedelta(minutes=31) + conservative_buffer
            )


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


def test_supplemental_campaign_initialization_preserves_original_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    original = CampaignConfig.model_validate(
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
    supplemental = _temp_supplemental_config(tmp_path)
    initialize_campaign(original, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    original_ledger_before = ledger_path(original).read_bytes()

    supplemental_registry = initialize_campaign(
        supplemental,
        config_path=Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml"),
    )
    validation = validate_campaign(supplemental)

    assert supplemental_registry.campaign_id != original.campaign_id
    assert supplemental_registry.campaign_role == CampaignRole.EXPLORATORY_INTRADAY
    assert ledger_path(original).read_bytes() == original_ledger_before
    assert (
        read_ledger(ledger_path(supplemental))[0].event_type == LedgerEventType.CAMPAIGN_INITIALIZED
    )
    assert validation["validation_status"] == "VALID"
    assert validation["attempt_count"] == 0
    assert (
        campaign_status_payload(supplemental, supplemental_registry)["next_scheduled_slot"][
            "slot_id"
        ]
        == "S01"
    )


def test_composite_exploratory_dataset_preserves_source_campaign_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    original = CampaignConfig.model_validate(
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
    supplemental = _temp_supplemental_config(tmp_path)
    initialize_campaign(original, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    initialize_campaign(
        supplemental,
        config_path=Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml"),
    )
    for index, slot_id in enumerate([f"P{slot_number:02d}" for slot_number in range(1, 9)]):
        accepted = _accepted_attempt(original, slot_id=slot_id, index=index, overlap=1800)
        record_attempt_event(
            original,
            event_type=LedgerEventType.ATTEMPT_STARTED,
            attempt=_started_from_accepted(accepted),
        )
        record_attempt_event(
            original,
            event_type=LedgerEventType.ATTEMPT_ACCEPTED,
            attempt=accepted,
        )
    for index, slot_id in enumerate(["S01", "S02"], start=8):
        accepted = _accepted_attempt(supplemental, slot_id=slot_id, index=index, overlap=1800)
        record_attempt_event(
            supplemental,
            event_type=LedgerEventType.ATTEMPT_STARTED,
            attempt=_started_from_accepted(accepted),
        )
        record_attempt_event(
            supplemental,
            event_type=LedgerEventType.ATTEMPT_ACCEPTED,
            attempt=accepted,
        )
    output_path = tmp_path / "composite" / "supplemental_intraday_exploratory_dataset.json"

    manifest, path = build_composite_exploratory_dataset(
        (original, supplemental),
        output_path=output_path,
    )

    assert path == output_path
    assert output_path.exists()
    assert manifest.composite_dataset_label == COMPOSITE_EXPLORATORY_LABEL
    assert manifest.source_campaign_ids == (original.campaign_id, supplemental.campaign_id)
    assert manifest.aggregate_accepted_session_count == 10
    assert manifest.aggregate_paired_overlap_seconds == 18_000
    assert manifest.requirements_satisfied is True
    assert [source.accepted_attempt_count for source in manifest.sources] == [8, 2]
    assert {entry.source_campaign_id for entry in manifest.accepted_attempts} == {
        original.campaign_id,
        supplemental.campaign_id,
    }
    assert all(entry.inclusion_status == "INCLUDED" for entry in manifest.accepted_attempts)
    assert all(entry.validated_pair_manifest_sha256 for entry in manifest.accepted_attempts)
    assert "not a substitute for the multi-day validation campaign" in manifest.warning


def test_composite_exploratory_dataset_rejects_non_exploratory_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    validation_config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    supplemental = _temp_supplemental_config(tmp_path)
    initialize_campaign(
        validation_config,
        config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"),
    )
    initialize_campaign(
        supplemental,
        config_path=Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml"),
    )

    with pytest.raises(CampaignValidationError, match="not exploratory intraday"):
        build_composite_exploratory_dataset(
            (validation_config, supplemental),
            output_path=tmp_path / "composite.json",
        )


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
    with pytest.raises(Exception, match="target matches existing runtime"):
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

    with pytest.raises(Exception, match="collected attempt evidence"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.GENERIC_ENGINE_BEFORE_FIRST_COLLECTION,
        )


def test_runtime_migration_allowed_after_zero_data_failed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "2" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    started = _started_attempt(config)
    failed = _zero_data_failed_attempt(config)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=started)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_FAILED, attempt=failed)

    report = migrate_campaign_runtime(
        config,
        reason=RuntimeMigrationReason.LONG_DURATION_PREFLIGHT_FIX,
    )

    assert report["old_runtime_commit"] == "0" * 40
    assert report["new_runtime_commit"] == "2" * 40
    assert (
        report["migration_event_type"]
        == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE.value
    )
    events = read_ledger(ledger_path(config))
    assert events[-2].event_type == LedgerEventType.ATTEMPT_FAILED
    assert (
        events[-1].event_type == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE
    )


def test_runtime_migration_blocked_after_collected_failed_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "2" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    record_attempt_event(
        config,
        event_type=LedgerEventType.ATTEMPT_STARTED,
        attempt=_started_attempt(config),
    )
    record_attempt_event(
        config,
        event_type=LedgerEventType.ATTEMPT_FAILED,
        attempt=_zero_data_failed_attempt(config).model_copy(update={"coinbase_frame_count": 1}),
    )

    with pytest.raises(Exception, match="corrective excluded-attempt reason"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.LONG_DURATION_PREFLIGHT_FIX,
        )


def test_runtime_migration_allowed_after_excluded_attempts_for_message_limit_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "3" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    started = _started_attempt(config)
    rejected = _excluded_rejected_attempt(config)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=started)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_REJECTED, attempt=rejected)

    report = migrate_campaign_runtime(
        config,
        reason=RuntimeMigrationReason.CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX,
    )

    assert report["old_runtime_commit"] == "0" * 40
    assert report["new_runtime_commit"] == "3" * 40
    assert (
        report["migration_event_type"]
        == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS.value
    )
    events = read_ledger(ledger_path(config))
    assert (
        events[-1].event_type == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS
    )
    assert events[-1].payload["migration_reason"] == (
        RuntimeMigrationReason.CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX.value
    )
    assert events[-1].payload["excluded_attempt_ids"] == [rejected.campaign_attempt_id]
    assert events[-1].payload["no_accepted_dataset_membership"] is True
    assert events[-1].payload["attempt_source_hashes"][rejected.campaign_attempt_id] == {
        "source_session_manifest_hashes": rejected.source_session_manifest_hashes,
        "source_raw_shard_checksums": rejected.source_raw_shard_checksums,
        "session_quality_report_hashes": rejected.session_quality_report_hashes,
        "paired_quality_report_hash": rejected.paired_quality_report_hash,
        "validated_pair_manifest_sha256": None,
    }


def test_runtime_migration_blocked_after_excluded_attempt_with_wrong_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "3" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    started = _started_attempt(config)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=started)
    record_attempt_event(
        config,
        event_type=LedgerEventType.ATTEMPT_REJECTED,
        attempt=_excluded_rejected_attempt(config),
    )

    with pytest.raises(Exception, match="corrective excluded-attempt reason"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.LONG_DURATION_PREFLIGHT_FIX,
        )


def test_runtime_migration_blocked_after_included_or_manifest_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "3" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    started = _started_attempt(config)
    included = _excluded_rejected_attempt(config).model_copy(
        update={
            "inclusion_status": InclusionStatus.INCLUDED,
            "validated_pair_manifest_id": "validated-pair-test",
            "validated_pair_manifest_path": "validated-pair-test.json",
            "validated_pair_manifest_sha256": "a" * 64,
        }
    )
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=started)
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_REJECTED, attempt=included)

    with pytest.raises(Exception, match="collected attempt evidence"):
        migrate_campaign_runtime(
            config,
            reason=RuntimeMigrationReason.CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX,
        )


def test_attempt_runtime_lineage_validator_reconstructs_migrations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.migration.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "0" * 40)
    monkeypatch.setattr("cross_venue.campaigns.migration.current_git_commit", lambda: "3" * 40)
    config = CampaignConfig.model_validate(_campaign_payload(tmp_path))
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    record_attempt_event(
        config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=_started_attempt(config)
    )
    record_attempt_event(
        config,
        event_type=LedgerEventType.ATTEMPT_FAILED,
        attempt=_zero_data_failed_attempt(config),
    )
    migrate_campaign_runtime(config, reason=RuntimeMigrationReason.LONG_DURATION_PREFLIGHT_FIX)
    second = _started_attempt(config).model_copy(
        update={
            "slot_id": "P02",
            "campaign_attempt_id": f"{config.campaign_id}-P02-001",
            "attempt_runtime_git_commit": "3" * 40,
        }
    )
    record_attempt_event(config, event_type=LedgerEventType.ATTEMPT_STARTED, attempt=second)

    report = validate_campaign(config)

    assert report["validation_status"] == "VALID"


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


def _temp_supplemental_config(tmp_path: Path) -> CampaignConfig:
    config = load_campaign_config(
        Path("configs/campaigns/intraday_continuation_btc_usd_2026_08.toml")
    )
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


def _accepted_attempt(
    config: CampaignConfig,
    *,
    slot_id: str,
    index: int,
    overlap: float,
) -> AttemptSummary:
    slot = config.slot_by_id(slot_id)
    return AttemptSummary(
        campaign_id=config.campaign_id,
        slot_id=slot.slot_id,
        attempt_number=1,
        campaign_attempt_id=f"{config.campaign_id}-{slot.slot_id}-001",
        slot_type=slot.slot_type,
        planned_start_utc=slot.planned_start_utc,
        planned_start_local=slot.planned_start_local,
        time_bucket=slot.time_bucket,
        actual_started_at=slot.planned_start_utc,
        actual_completed_at=slot.planned_start_utc + timedelta(seconds=1860),
        requested_duration_seconds=config.requested_duration_seconds,
        maximum_messages_per_venue=config.maximum_messages_per_venue,
        attempt_runtime_git_commit=f"{index:040x}"[-40:],
        actual_collection_duration_seconds=1860,
        paired_overlap_seconds=overlap,
        paired_collection_id=f"paired-{index:02d}",
        coinbase_session_id=f"coinbase-{index:02d}",
        kraken_session_id=f"kraken-{index:02d}",
        coinbase_frame_count=6000 + index,
        kraken_frame_count=5900 + index,
        coinbase_effective_duration_limit_seconds=1860,
        kraken_effective_duration_limit_seconds=1860,
        coinbase_effective_message_limit=100_000,
        kraken_effective_message_limit=100_000,
        coinbase_stop_reason="REQUESTED_DURATION_REACHED",
        kraken_stop_reason="REQUESTED_DURATION_REACHED",
        coinbase_trade_count=1000,
        kraken_trade_count=1000,
        coinbase_bbo_count=1000,
        kraken_bbo_count=1000,
        coinbase_archive_valid=True,
        kraken_archive_valid=True,
        coinbase_disposition="ACCEPTED",
        kraken_disposition="ACCEPTED",
        paired_disposition="ACCEPTED",
        promotion_dry_run_allowed=True,
        validated_pair_manifest_id=f"validated-pair-{index:02d}",
        validated_pair_manifest_path=f"validated-pair-{index:02d}.json",
        validated_pair_manifest_sha256=f"{index + 1:064x}"[-64:],
        source_session_manifest_hashes={
            f"coinbase-{index:02d}": f"{index + 2:064x}"[-64:],
            f"kraken-{index:02d}": f"{index + 3:064x}"[-64:],
        },
        source_raw_shard_checksums={
            f"coinbase-{index:02d}": {"raw/part-00000.jsonl": f"{index + 4:064x}"[-64:]},
            f"kraken-{index:02d}": {"raw/part-00000.jsonl": f"{index + 5:064x}"[-64:]},
        },
        session_quality_report_hashes={
            f"coinbase-{index:02d}": f"{index + 6:064x}"[-64:],
            f"kraken-{index:02d}": f"{index + 7:064x}"[-64:],
        },
        paired_quality_report_hash=f"{index + 8:064x}"[-64:],
        attempt_status=AttemptStatus.ACCEPTED,
        inclusion_status=InclusionStatus.INCLUDED,
    )


def _started_from_accepted(attempt: AttemptSummary) -> AttemptSummary:
    return attempt.model_copy(
        update={
            "actual_completed_at": None,
            "actual_collection_duration_seconds": None,
            "paired_overlap_seconds": 0.0,
            "paired_collection_id": None,
            "coinbase_session_id": None,
            "kraken_session_id": None,
            "coinbase_frame_count": 0,
            "kraken_frame_count": 0,
            "validated_pair_manifest_id": None,
            "validated_pair_manifest_path": None,
            "validated_pair_manifest_sha256": None,
            "source_session_manifest_hashes": {},
            "source_raw_shard_checksums": {},
            "session_quality_report_hashes": {},
            "paired_quality_report_hash": None,
            "attempt_status": AttemptStatus.STARTED,
            "inclusion_status": InclusionStatus.EXCLUDED,
            "exclusion_reason": "attempt not complete",
        }
    )


def _zero_data_failed_attempt(config: CampaignConfig) -> AttemptSummary:
    started = _started_attempt(config)
    return started.model_copy(
        update={
            "actual_completed_at": started.actual_started_at,
            "attempt_status": AttemptStatus.FAILED,
            "failure_classification": FailureClassification.UNKNOWN_FAILURE,
            "failure_message": "duration exceeds Phase 2D maximum",
            "exclusion_reason": "attempt failed",
        }
    )


def _excluded_rejected_attempt(config: CampaignConfig) -> AttemptSummary:
    started = _started_attempt(config)
    return started.model_copy(
        update={
            "actual_completed_at": started.actual_started_at + timedelta(seconds=373),
            "actual_collection_duration_seconds": 373.199853,
            "paired_overlap_seconds": 289.97174,
            "paired_collection_id": "paired-test",
            "coinbase_session_id": "coinbase-test",
            "kraken_session_id": "kraken-test",
            "coinbase_frame_count": 5001,
            "kraken_frame_count": 4879,
            "coinbase_archive_valid": True,
            "kraken_archive_valid": True,
            "coinbase_disposition": "ACCEPTED",
            "kraken_disposition": "ACCEPTED",
            "paired_disposition": "ACCEPTED",
            "promotion_dry_run_allowed": True,
            "source_session_manifest_hashes": {
                "coinbase-test": "b" * 64,
                "kraken-test": "c" * 64,
            },
            "source_raw_shard_checksums": {
                "coinbase-test": {"raw/part-00000.jsonl": "d" * 64},
                "kraken-test": {"raw/part-00000.jsonl": "e" * 64},
            },
            "session_quality_report_hashes": {
                "coinbase-test": "f" * 64,
                "kraken-test": "1" * 64,
            },
            "paired_quality_report_hash": "2" * 64,
            "attempt_status": AttemptStatus.REJECTED,
            "inclusion_status": InclusionStatus.EXCLUDED,
            "exclusion_reason": "quality disposition was not accepted",
        }
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
