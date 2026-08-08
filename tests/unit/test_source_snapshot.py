from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from quality_helpers import make_session

from cross_venue.campaigns.models import (
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    CampaignRegistry,
    CompletionRequirements,
    CompletionState,
    InclusionStatus,
    LedgerEvent,
    LedgerEventType,
    MissedReason,
    PlannedSlotState,
    SlotStatus,
)
from cross_venue.cli import main
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.io import persist_model_json, portable_relative_path
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import build_validated_dataset_manifest
from cross_venue.research.exceptions import SnapshotPersistenceError, SourceCatalogError
from cross_venue.research.source_snapshot import (
    SourceSelectionConfig,
    atomic_write_json,
    build_analysis_source_snapshot,
    build_source_catalog,
    canonical_decimal,
    compute_event_hash,
    read_source_ledger,
    sha256_file,
    validate_analysis_source_snapshot,
    validate_attempt_membership,
)
from cross_venue.schemas import Exchange

FIXTURE_RUNTIME_COMMIT = "98e28b2e026124434fc1bec1d442d7b9bcbc8530"  # pragma: allowlist secret
CAMPAIGN_ID = "btc-usd-coinbase-kraken-2026-07-31-v1"
INTRADAY_ID = "btc-usd-coinbase-kraken-2026-07-31-intraday-v1"
ACCEPTED_ATTEMPT_IDS = (
    f"{CAMPAIGN_ID}-P02-001",
    f"{CAMPAIGN_ID}-P03-001",
    f"{CAMPAIGN_ID}-P09-001",
    f"{CAMPAIGN_ID}-P10-001",
    f"{CAMPAIGN_ID}-R01-001",
    f"{CAMPAIGN_ID}-R02-001",
    f"{CAMPAIGN_ID}-R05-001",
)
MISSED_SLOT_IDS = ("P01", "P04", "P05", "P06", "P07", "R03", "R04")
PAIR_IDS = {
    "P02": "paired-0bef4dc2-7b60-4c7c-aa07-a9dc90b3e8bc",
    "P03": "paired-1b78cbcf-62c5-4d5c-9829-bfa6d2999fe2",
    "P09": "paired-a18713dc-b448-4c67-8cd6-917d6410a119",
    "P10": "paired-d943dca9-f0d7-47f9-84d3-f3aa5b83f86c",
    "R01": "paired-bbc595c7-7082-4c07-a603-fdf41d5ad4fb",
    "R02": "paired-a539656a-e7cf-4f32-903c-062f34f41f66",
    "R05": "paired-55c8e33b-4f21-4f8d-b96f-05493254d6c0",
    "P08": "paired-36289696-9fde-4b08-9a07-694b1328ecc5",
    "R03": "paired-future-r03",
}


def test_source_catalog_includes_seven_and_excludes_quarantined_missed_intraday(
    tmp_path: Path,
) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))

    catalog = build_source_catalog(
        source_collection_root=fixture.source_root,
        selection=SourceSelectionConfig(campaign_ids=(CAMPAIGN_ID,)),
    )

    assert catalog.accepted_attempt_count == 7
    assert tuple(attempt.campaign_attempt_id for attempt in catalog.accepted_attempts) == (
        ACCEPTED_ATTEMPT_IDS
    )
    assert {item["campaign_attempt_id"] for item in catalog.excluded_attempt_summary} == {
        f"{CAMPAIGN_ID}-P08-001"
    }
    assert {item["slot_id"] for item in catalog.missed_slot_summary} == set(MISSED_SLOT_IDS)
    assert INTRADAY_ID not in catalog.source_campaign_ids
    assert catalog.accepted_calendar_dates == (
        "2026-07-31",
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
    )
    assert catalog.accepted_time_buckets == ("AFTERNOON", "EVENING", "MORNING")


def test_snapshot_identity_is_stable_across_time_and_absolute_source_root(
    tmp_path: Path,
) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path / "one"))
    cloned_source = tmp_path / "two" / "source"
    shutil.copytree(fixture.source_root, cloned_source)

    first = build_source_catalog(
        source_collection_root=fixture.source_root,
        selection=SourceSelectionConfig(campaign_ids=(CAMPAIGN_ID,)),
    )
    second = build_source_catalog(
        source_collection_root=cloned_source,
        selection=SourceSelectionConfig(campaign_ids=(CAMPAIGN_ID,)),
    )
    first_result = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis-one",
        campaign_ids=(CAMPAIGN_ID,),
    )
    second_result = build_analysis_source_snapshot(
        source_collection_root=cloned_source,
        analysis_output_root=tmp_path / "analysis-two",
        campaign_ids=(CAMPAIGN_ID,),
    )

    assert first.source_catalog_id == second.source_catalog_id
    assert first.content_hash == second.content_hash
    assert first_result.snapshot.snapshot_id == second_result.snapshot.snapshot_id
    assert first_result.snapshot.created_at != second_result.snapshot.created_at
    assert canonical_decimal(first.aggregate_paired_overlap_seconds) == "13005.314148"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda fixture: validated_manifest_path(
                fixture, "validated-paired-0bef4dc2-7b60-4c7c-aa07-a9dc90b3e8bc"
            ).unlink(),
            "missing validated-pair manifest",
        ),
        (
            lambda fixture: validated_manifest_path(
                fixture, "validated-paired-0bef4dc2-7b60-4c7c-aa07-a9dc90b3e8bc"
            ).write_text('{"broken": true}\n', encoding="utf-8"),
            "validated-pair manifest hash mismatch",
        ),
        (
            lambda fixture: _mutate_json(
                fixture.registry_path,
                lambda payload: payload.update({"accepted_attempt_count": 99}),
            ),
            "registry does not match ledger reconstruction",
        ),
        (
            lambda fixture: _mutate_ledger_line(fixture.ledger_path, 1, "bad hash"),
            "ledger event hash mismatch",
        ),
        (
            lambda fixture: _mutate_attempt_event(
                fixture,
                ACCEPTED_ATTEMPT_IDS[0],
                lambda attempt: attempt.update({"inclusion_status": "EXCLUDED"}),
            ),
            "accepted attempt is excluded",
        ),
        (
            lambda fixture: _mutate_attempt_event(
                fixture,
                ACCEPTED_ATTEMPT_IDS[0],
                lambda attempt: attempt.update({"paired_quality_report_hash": None}),
            ),
            "missing required lineage",
        ),
    ],
)
def test_source_catalog_failure_modes(
    tmp_path: Path,
    mutation: Any,
    match: str,
) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))
    mutation(fixture)

    with pytest.raises(SourceCatalogError, match=match):
        build_source_catalog(
            source_collection_root=fixture.source_root,
            selection=SourceSelectionConfig(campaign_ids=(CAMPAIGN_ID,)),
        )


def test_duplicate_attempt_and_manifest_identity_failures(tmp_path: Path) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))
    catalog = build_source_catalog(
        source_collection_root=fixture.source_root,
        selection=SourceSelectionConfig(campaign_ids=(CAMPAIGN_ID,)),
    )
    duplicate_attempt = list(catalog.accepted_attempts)
    duplicate_attempt.append(catalog.accepted_attempts[0])
    with pytest.raises(SourceCatalogError, match="duplicate campaign attempt identity"):
        validate_attempt_membership(duplicate_attempt)

    duplicate_manifest = list(catalog.accepted_attempts)
    duplicate_manifest[1] = duplicate_manifest[1].model_copy(
        update={
            "validated_pair_manifest_id": duplicate_manifest[0].validated_pair_manifest_id,
        }
    )
    with pytest.raises(SourceCatalogError, match="duplicate validated-pair manifest identity"):
        validate_attempt_membership(duplicate_manifest)


def test_snapshot_atomic_noop_conflict_and_source_immutability(tmp_path: Path) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))
    before = file_hashes(fixture.source_root)

    result = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis",
        campaign_ids=(CAMPAIGN_ID,),
    )
    repeated = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis",
        campaign_ids=(CAMPAIGN_ID,),
    )

    assert result.created is True
    assert repeated.created is False
    assert file_hashes(fixture.source_root) == before
    manifest = json.loads(result.snapshot_manifest_path.read_text(encoding="utf-8"))
    manifest["content_hash"] = "0" * 64
    atomic_write_json(result.snapshot_manifest_path, manifest)
    with pytest.raises(SnapshotPersistenceError, match="different content"):
        build_analysis_source_snapshot(
            source_collection_root=fixture.source_root,
            analysis_output_root=tmp_path / "analysis",
            campaign_ids=(CAMPAIGN_ID,),
        )


def test_validate_and_status_cli_success_and_failure(tmp_path: Path, capsys: Any) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))
    output_root = tmp_path / "analysis"

    exit_code = main(
        [
            "build-analysis-source-snapshot",
            "--source-collection-root",
            str(fixture.source_root),
            "--analysis-output-root",
            str(output_root),
            "--campaign-id",
            CAMPAIGN_ID,
        ]
    )
    assert exit_code == 0
    assert "Analysis snapshot created" in capsys.readouterr().out

    snapshot_root = next((output_root / "snapshots").iterdir())
    assert (
        main(
            [
                "validate-analysis-source-snapshot",
                "--snapshot-root",
                str(snapshot_root),
                "--source-collection-root",
                str(fixture.source_root),
            ]
        )
        == 0
    )
    assert '"validation_status": "VALID"' in capsys.readouterr().out
    assert main(["analysis-snapshot-status", "--snapshot-root", str(snapshot_root)]) == 0
    assert "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED" in capsys.readouterr().out
    assert (
        main(
            [
                "build-analysis-source-snapshot",
                "--source-collection-root",
                str(fixture.source_root),
                "--analysis-output-root",
                str(output_root),
                "--campaign-id",
                INTRADAY_ID,
            ]
        )
        == 1
    )
    assert "Analysis source snapshot failed" in capsys.readouterr().out


def test_future_accepted_session_creates_new_snapshot_without_mutating_original(
    tmp_path: Path,
) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))
    first = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis",
        campaign_ids=(CAMPAIGN_ID,),
    )
    original_manifest = first.snapshot_manifest_path.read_text(encoding="utf-8")

    asyncio.run(add_future_accepted_attempt(fixture))
    second = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis",
        campaign_ids=(CAMPAIGN_ID,),
    )

    assert second.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert second.snapshot.accepted_attempt_count == 8
    assert first.snapshot_manifest_path.read_text(encoding="utf-8") == original_manifest
    assert (
        validate_analysis_source_snapshot(
            snapshot_root=first.snapshot_root,
            source_collection_root=None,
        ).validation_status
        == "VALID"
    )


def test_seven_sessions_are_preliminary_valid_but_final_requirements_unsatisfied(
    tmp_path: Path,
) -> None:
    fixture = asyncio.run(make_source_fixture(tmp_path))

    result = build_analysis_source_snapshot(
        source_collection_root=fixture.source_root,
        analysis_output_root=tmp_path / "analysis",
        campaign_ids=(CAMPAIGN_ID,),
    )

    assert result.validation.validation_status == "VALID"
    assert result.snapshot.status == "SOURCE_SNAPSHOT_VALID"
    assert result.snapshot.final_composite_status == "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
    assert result.snapshot.accepted_attempt_count == 7


class SourceFixture:
    def __init__(self, source_root: Path, registry_path: Path, ledger_path: Path) -> None:
        self.source_root = source_root
        self.registry_path = registry_path
        self.ledger_path = ledger_path


async def make_source_fixture(tmp_path: Path) -> SourceFixture:
    source_root = tmp_path / "source"
    (source_root / "configs/campaigns").mkdir(parents=True)
    shutil.copyfile(
        Path("configs/campaigns/phase_3b_btc_usd.toml"),
        source_root / "configs/campaigns/phase_3b_btc_usd.toml",
    )
    shutil.copyfile(Path("configs/data_quality.toml"), source_root / "configs/data_quality.toml")
    config = load_fixture_config(source_root)
    pair_entries = []
    for attempt_id in ACCEPTED_ATTEMPT_IDS:
        slot_id = attempt_id.removeprefix(f"{CAMPAIGN_ID}-").removesuffix("-001")
        pair_entries.append(await make_pair_entry(source_root, config, slot_id, attempt_id))
    quarantined = await make_pair_entry(
        source_root,
        config,
        "P08",
        f"{CAMPAIGN_ID}-P08-001",
        status=AttemptStatus.QUARANTINED,
        inclusion=InclusionStatus.EXCLUDED,
    )
    write_campaign_state(
        config,
        [*pair_entries, quarantined],
        source_root=source_root,
        config_path=source_root / "configs/campaigns/phase_3b_btc_usd.toml",
    )
    write_intraday_campaign(source_root)
    return SourceFixture(
        source_root=source_root,
        registry_path=campaign_registry_path(config),
        ledger_path=campaign_ledger_path(config),
    )


async def add_future_accepted_attempt(fixture: SourceFixture) -> None:
    config = load_fixture_config(fixture.source_root)
    existing = CampaignRegistry.model_validate_json(fixture.registry_path.read_text())
    attempts = list(existing.attempts.values())
    attempts.append(
        await make_pair_entry(
            fixture.source_root,
            config,
            "R03",
            f"{CAMPAIGN_ID}-R03-001",
            overlap=1858.123456,
        )
    )
    write_campaign_state(
        config,
        attempts,
        source_root=fixture.source_root,
        config_path=fixture.source_root / "configs/campaigns/phase_3b_btc_usd.toml",
        missed_slots=("P01", "P04", "P05", "P06", "P07", "R04"),
    )


async def make_pair_entry(
    source_root: Path,
    config: CampaignConfig,
    slot_id: str,
    attempt_id: str,
    *,
    status: AttemptStatus = AttemptStatus.ACCEPTED,
    inclusion: InclusionStatus = InclusionStatus.INCLUDED,
    overlap: float | None = None,
) -> AttemptSummary:
    pair_id = PAIR_IDS[slot_id]
    coinbase_session, storage_config, quality_config = await make_session(
        source_root / "data",
        venue=Exchange.COINBASE,
        session_id=f"coinbase-{slot_id.lower()}",
    )
    kraken_session, _, _ = await make_session(
        source_root / "data",
        venue=Exchange.KRAKEN,
        session_id=f"kraken-{slot_id.lower()}",
    )
    quality_config = quality_config.model_copy(
        update={
            "policy_version": "2d.2",
            "validated_manifest_root": source_root / "data/validated/manifests",
        }
    )
    pair_root = quality_config.report_root / "paired" / pair_id
    coinbase_path = pair_root / "coinbase_session_quality_report.json"
    kraken_path = pair_root / "kraken_session_quality_report.json"
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
            "report_relative_path": portable_relative_path(quality_config.report_root, kraken_path)
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
    slot = config.slot_by_id(slot_id)
    accepted_overlap = overlap if overlap is not None else SYNTHETIC_OVERLAPS[slot_id]
    return AttemptSummary(
        campaign_id=CAMPAIGN_ID,
        slot_id=slot_id,
        attempt_number=1,
        campaign_attempt_id=attempt_id,
        slot_type=slot.slot_type,
        planned_start_utc=slot.planned_start_utc,
        planned_start_local=slot.planned_start_local,
        time_bucket=slot.time_bucket,
        actual_started_at=slot.planned_start_utc,
        actual_completed_at=slot.planned_start_utc,
        requested_duration_seconds=1860,
        maximum_messages_per_venue=100000,
        actual_collection_duration_seconds=1860,
        paired_overlap_seconds=accepted_overlap,
        paired_collection_id=paired_report.paired_collection_id,
        coinbase_session_id=coinbase_report.session_id,
        kraken_session_id=kraken_report.session_id,
        coinbase_archive_valid=True,
        kraken_archive_valid=True,
        coinbase_disposition="ACCEPTED",
        kraken_disposition="ACCEPTED",
        paired_disposition="ACCEPTED",
        promotion_dry_run_allowed=True,
        validated_pair_manifest_id=validated.dataset_manifest_id,
        validated_pair_manifest_path=portable_relative_path(
            quality_config.validated_manifest_root, validated_path
        ),
        validated_pair_manifest_sha256=sha256_file(validated_path),
        source_session_manifest_hashes=validated.raw_manifest_hashes,
        source_raw_shard_checksums={
            coinbase_report.session_id: dict(coinbase_report.input_shard_checksums),
            kraken_report.session_id: dict(kraken_report.input_shard_checksums),
        },
        session_quality_report_hashes=validated.session_quality_report_hashes,
        paired_quality_report_hash=_model_hash(paired_report),
        attempt_runtime_git_commit=FIXTURE_RUNTIME_COMMIT,
        attempt_status=status,
        inclusion_status=inclusion,
        exclusion_reason="PAIRED_QUALITY_QUARANTINED"
        if inclusion == InclusionStatus.EXCLUDED
        else None,
    )


SYNTHETIC_OVERLAPS = {
    "P02": 1856.790902,
    "P03": 1855.849980,
    "P09": 1858.689021,
    "P10": 1858.812558,
    "R01": 1858.356535,
    "R02": 1858.276005,
    "R05": 1858.539147,
    "P08": 1850.669218,
}


def write_campaign_state(
    config: CampaignConfig,
    attempts: list[AttemptSummary],
    *,
    source_root: Path,
    config_path: Path,
    missed_slots: tuple[str, ...] = MISSED_SLOT_IDS,
) -> None:
    created = datetime(2026, 8, 5, tzinfo=UTC)
    planned_slots = {
        slot.slot_id: PlannedSlotState(slot=slot, status=SlotStatus.PLANNED)
        for slot in config.slots
    }
    registry = CampaignRegistry(
        campaign_schema_version=config.campaign_schema_version,
        campaign_id=config.campaign_id,
        campaign_role=config.campaign_role,
        campaign_status="IN_PROGRESS",
        campaign_config_path="configs/campaigns/phase_3b_btc_usd.toml",
        campaign_config_sha256=sha256_file(config_path),
        quality_policy_version="2d.2",
        quality_policy_sha256=sha256_file(source_root / "configs/data_quality.toml"),
        runtime_git_commit=FIXTURE_RUNTIME_COMMIT,
        runtime_working_tree_clean=True,
        created_at=created,
        updated_at=created,
        instrument="BTC-USD",
        venues=(Exchange.COINBASE, Exchange.KRAKEN),
        timezone="America/New_York",
        requested_duration_seconds=1860,
        minimum_overlap_seconds_per_accepted_session=1800,
        minimum_accepted_sessions=10,
        minimum_total_accepted_overlap_seconds=18000,
        minimum_calendar_dates=3,
        minimum_time_buckets=3,
        maximum_attempts=15,
        planned_slots=planned_slots,
        attempts={},
        completion_requirements=CompletionRequirements(
            accepted_sessions=False,
            accepted_overlap_seconds=False,
            calendar_dates=False,
            time_buckets=False,
            policy_consistency=True,
            runtime_consistency=True,
            attempts_registered=False,
            registry_and_ledger_valid=True,
        ),
        completion_status=CompletionState.UNSATISFIED,
        ledger_sha256="",
    )
    events = [make_event(0, LedgerEventType.CAMPAIGN_INITIALIZED, {"registry": registry})]
    for slot_id in missed_slots:
        events.append(
            make_event(
                len(events),
                LedgerEventType.SLOT_MARKED_MISSED,
                {"reason": MissedReason.USER_UNAVAILABLE.value},
                slot_id=slot_id,
                previous=events[-1].event_hash,
            )
        )
    for attempt in sorted(attempts, key=lambda item: item.planned_start_utc):
        started = attempt.model_copy(update={"attempt_status": AttemptStatus.STARTED})
        events.append(
            make_event(
                len(events),
                LedgerEventType.ATTEMPT_STARTED,
                {"attempt": started},
                slot_id=attempt.slot_id,
                campaign_attempt_id=attempt.campaign_attempt_id,
                previous=events[-1].event_hash,
            )
        )
        event_type = {
            AttemptStatus.ACCEPTED: LedgerEventType.ATTEMPT_ACCEPTED,
            AttemptStatus.QUARANTINED: LedgerEventType.ATTEMPT_QUARANTINED,
            AttemptStatus.REJECTED: LedgerEventType.ATTEMPT_REJECTED,
            AttemptStatus.FAILED: LedgerEventType.ATTEMPT_FAILED,
        }[attempt.attempt_status]
        events.append(
            make_event(
                len(events),
                event_type,
                {"attempt": attempt},
                slot_id=attempt.slot_id,
                campaign_attempt_id=attempt.campaign_attempt_id,
                previous=events[-1].event_hash,
            )
        )
    ledger_path = campaign_ledger_path(config)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        "".join(
            json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    rebuilt = read_source_ledger(ledger_path)
    assert len(rebuilt) == len(events)
    from cross_venue.research.source_snapshot import rebuild_registry_from_events

    final_registry = rebuild_registry_from_events(events).model_copy(
        update={"updated_at": created, "ledger_sha256": sha256_file(ledger_path)}
    )
    registry_path = campaign_registry_path(config)
    atomic_write_json(registry_path, final_registry.model_dump(mode="json"))


def make_event(
    index: int,
    event_type: LedgerEventType,
    payload: dict[str, Any],
    *,
    slot_id: str | None = None,
    campaign_attempt_id: str | None = None,
    previous: str = "0" * 64,
) -> LedgerEvent:
    event = LedgerEvent(
        event_index=index,
        campaign_id=CAMPAIGN_ID,
        event_type=event_type,
        occurred_at=datetime(2026, 8, 5, tzinfo=UTC),
        slot_id=slot_id,
        campaign_attempt_id=campaign_attempt_id,
        payload={
            key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            for key, value in payload.items()
        },
        previous_event_hash=previous,
        event_hash="",
    )
    return event.model_copy(update={"event_hash": compute_event_hash(event)})


def write_intraday_campaign(source_root: Path) -> None:
    path = (
        source_root
        / "data/campaigns"
        / f"campaign={INTRADAY_ID}"
        / "registry/campaign_registry.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "campaign_id": INTRADAY_ID,
        "campaign_config_path": "configs/campaigns/phase_3b_btc_usd.toml",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_fixture_config(source_root: Path) -> CampaignConfig:
    with (source_root / "configs/campaigns/phase_3b_btc_usd.toml").open("rb") as handle:
        payload = __import__("tomllib").load(handle)
    payload.update(
        {
            "registry_root": source_root / "data/campaigns",
            "validated_manifest_root": source_root / "data/validated/manifests",
            "normalized_output_root": source_root / "data/normalized",
        }
    )
    return CampaignConfig.model_validate(payload)


def campaign_registry_path(config: CampaignConfig) -> Path:
    return (
        config.registry_root / f"campaign={config.campaign_id}" / "registry/campaign_registry.json"
    )


def campaign_ledger_path(config: CampaignConfig) -> Path:
    return config.registry_root / f"campaign={config.campaign_id}" / "ledger/campaign_events.jsonl"


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def validated_manifest_path(fixture: SourceFixture, manifest_id: str) -> Path:
    return fixture.source_root / "data/validated/manifests" / f"{manifest_id}.json"


def _mutate_json(path: Path, mutator: Any) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    atomic_write_json(path, payload)


def _mutate_ledger_line(path: Path, index: int, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[index])
    payload["event_hash"] = value
    lines[index] = json.dumps(payload)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mutate_attempt_event(fixture: SourceFixture, attempt_id: str, mutator: Any) -> None:
    payloads = [
        json.loads(line)
        for line in fixture.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for payload in payloads:
        if (
            payload.get("campaign_attempt_id") == attempt_id
            and payload["event_type"] == "ATTEMPT_ACCEPTED"
        ):
            mutator(payload["payload"]["attempt"])
            break
    rehashed = rehash_ledger_payloads(payloads)
    fixture.ledger_path.write_text(
        "".join(
            json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n" for event in rehashed
        ),
        encoding="utf-8",
    )
    events = read_source_ledger(fixture.ledger_path)
    from cross_venue.research.source_snapshot import rebuild_registry_from_events

    registry = rebuild_registry_from_events(events).model_copy(
        update={"ledger_sha256": sha256_file(fixture.ledger_path)}
    )
    atomic_write_json(fixture.registry_path, registry.model_dump(mode="json"))


def rehash_ledger_payloads(payloads: list[dict[str, Any]]) -> list[LedgerEvent]:
    previous = "0" * 64
    events: list[LedgerEvent] = []
    for index, payload in enumerate(payloads):
        payload["event_index"] = index
        payload["previous_event_hash"] = previous
        payload["event_hash"] = ""
        event = LedgerEvent.model_validate(payload)
        event = event.model_copy(update={"event_hash": compute_event_hash(event)})
        previous = event.event_hash
        events.append(event)
    return events


def _model_hash(model: Any) -> str:
    encoded = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_rebuild_registry_from_events_status() -> None:
    from datetime import UTC, datetime

    from cross_venue.campaigns.models import (
        AttemptStatus,
        CampaignRegistry,
        CampaignRole,
        CampaignSlot,
        CampaignStatus,
        CompletionRequirements,
        CompletionState,
        InclusionStatus,
        LedgerEvent,
        LedgerEventType,
        PlannedSlotState,
        SlotStatus,
        SlotType,
        TimeBucket,
    )
    from cross_venue.research.source_snapshot import rebuild_registry_from_events

    now = datetime.now(UTC)
    slot = CampaignSlot(
        slot_id="P01",
        slot_type=SlotType.PRIMARY,
        time_bucket=TimeBucket.MORNING,
        planned_start_utc=now,
        planned_start_local="2026-08-01 09:30:00",
    )
    registry = CampaignRegistry(
        campaign_schema_version="3b-campaign-registry.1",
        campaign_id="test-camp",
        campaign_role=CampaignRole.MULTI_DAY_VALIDATION,
        campaign_status=CampaignStatus.IN_PROGRESS,
        campaign_config_path="configs/c.toml",
        campaign_config_sha256="aaa",
        quality_policy_version="1",
        quality_policy_sha256="bbb",
        runtime_git_commit="ccc",
        runtime_working_tree_clean=True,
        created_at=now,
        updated_at=now,
        instrument="BTC-USD",
        venues=(Exchange.COINBASE, Exchange.KRAKEN),
        timezone="America/New_York",
        requested_duration_seconds=1800,
        minimum_overlap_seconds_per_accepted_session=1800,
        minimum_accepted_sessions=1,
        minimum_total_accepted_overlap_seconds=1800,
        minimum_calendar_dates=1,
        minimum_time_buckets=1,
        maximum_attempts=1,
        planned_slots={"P01": PlannedSlotState(slot=slot, status=SlotStatus.PLANNED)},
        attempts={},
        completion_requirements=CompletionRequirements(
            accepted_sessions=False,
            accepted_overlap_seconds=False,
            calendar_dates=False,
            time_buckets=False,
            policy_consistency=True,
            runtime_consistency=True,
            attempts_registered=False,
            registry_and_ledger_valid=True,
        ),
        completion_status=CompletionState.UNSATISFIED,
        ledger_sha256="ddd",
    )
    events = [
        LedgerEvent(
            event_index=0,
            event_hash="hash0",
            previous_event_hash="0000000000000000000000000000000000000000000000000000000000000000",
            occurred_at=now,
            event_type=LedgerEventType.CAMPAIGN_INITIALIZED,
            campaign_id="test-camp",
            payload={"registry": registry.model_dump(mode="json")},
        ),
        LedgerEvent(
            event_index=1,
            event_hash="hash1",
            previous_event_hash="hash0",
            occurred_at=now,
            event_type=LedgerEventType.ATTEMPT_ACCEPTED,
            campaign_id="test-camp",
            slot_id="P01",
            campaign_attempt_id="test-camp-P01-001",
            payload={
                "attempt": {
                    "campaign_id": "test-camp",
                    "slot_id": "P01",
                    "campaign_attempt_id": "test-camp-P01-001",
                    "attempt_number": 1,
                    "slot_type": "PRIMARY",
                    "requested_duration_seconds": 1800,
                    "attempt_status": AttemptStatus.ACCEPTED.value,
                    "inclusion_status": InclusionStatus.INCLUDED.value,
                    "attempt_runtime_git_commit": "abcdef1",
                    "planned_start_utc": now.isoformat(),
                    "planned_start_local": "2026-08-01 09:30:00",
                    "time_bucket": TimeBucket.MORNING.value,
                    "paired_overlap_seconds": "1800.0",
                    "validated_pair_manifest_id": "pair",
                    "validated_pair_manifest_sha256": "sha",
                    "coinbase_disposition": "ACCEPTED",
                    "kraken_disposition": "ACCEPTED",
                    "paired_disposition": "ACCEPTED",
                    "coinbase_archive_valid": True,
                    "kraken_archive_valid": True,
                    "coinbase_stop_reason": "REQUESTED_DURATION_REACHED",
                    "kraken_stop_reason": "REQUESTED_DURATION_REACHED",
                    "promotion_dry_run_allowed": True,
                }
            },
        ),
    ]
    rebuilt = rebuild_registry_from_events(events)
    assert rebuilt.completion_status == CompletionState.SATISFIED
    assert rebuilt.campaign_status == CampaignStatus.COMPLETE

    # Test unsatisfied behavior
    events_unsat = [
        LedgerEvent(
            event_index=0,
            event_hash="hash0",
            previous_event_hash="0000000000000000000000000000000000000000000000000000000000000000",
            occurred_at=now,
            event_type=LedgerEventType.CAMPAIGN_INITIALIZED,
            campaign_id="test-camp",
            payload={"registry": registry.model_dump(mode="json")},
        ),
        LedgerEvent(
            event_index=1,
            event_hash="hash1",
            previous_event_hash="hash0",
            occurred_at=now,
            event_type=LedgerEventType.ATTEMPT_REJECTED,
            campaign_id="test-camp",
            slot_id="P01",
            campaign_attempt_id="test-camp-P01-001",
            payload={
                "attempt": {
                    "campaign_id": "test-camp",
                    "slot_id": "P01",
                    "campaign_attempt_id": "test-camp-P01-001",
                    "attempt_number": 1,
                    "slot_type": "PRIMARY",
                    "requested_duration_seconds": 1800,
                    "attempt_status": AttemptStatus.REJECTED.value,
                    "inclusion_status": InclusionStatus.EXCLUDED.value,
                    "exclusion_reason": "fail",
                    "attempt_runtime_git_commit": "abcdef1",
                    "planned_start_utc": now.isoformat(),
                    "planned_start_local": "2026-08-01 09:30:00",
                    "time_bucket": TimeBucket.MORNING.value,
                    "paired_overlap_seconds": "0.0",
                    "validated_pair_manifest_id": "pair",
                    "validated_pair_manifest_sha256": "sha",
                    "coinbase_disposition": "ACCEPTED",
                    "kraken_disposition": "ACCEPTED",
                    "paired_disposition": "ACCEPTED",
                    "coinbase_archive_valid": True,
                    "kraken_archive_valid": True,
                    "coinbase_stop_reason": "REQUESTED_DURATION_REACHED",
                    "kraken_stop_reason": "REQUESTED_DURATION_REACHED",
                    "promotion_dry_run_allowed": True,
                }
            },
        ),
    ]
    rebuilt_unsat = rebuild_registry_from_events(events_unsat)
    assert rebuilt_unsat.completion_status == CompletionState.UNSATISFIED
    assert rebuilt_unsat.campaign_status == CampaignStatus.IN_PROGRESS

    # Test identical _registry_comparable behavior
    from cross_venue.campaigns.registry import _registry_comparable

    assert _registry_comparable(rebuilt) == _registry_comparable(rebuilt.model_copy())
