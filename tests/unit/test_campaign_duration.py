from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from quality_helpers import make_session, quality_config, storage_config

from cross_venue.campaigns.config import load_campaign_config
from cross_venue.campaigns.models import (
    AttemptExclusionReason,
    AttemptStatus,
    CampaignConfig,
    FailureClassification,
)
from cross_venue.campaigns.registry import initialize_campaign
from cross_venue.campaigns.runner import run_campaign_slot
from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits, SessionStatistics
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.collection import collect_paired_quality
from cross_venue.quality.exceptions import CollectionPreflightError
from cross_venue.quality.models import QualityDisposition, SessionQualityReport
from cross_venue.runtime_limits import (
    MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE,
)
from cross_venue.schemas import Exchange


@pytest.mark.parametrize("duration", [180, 1860, 3600])
def test_paired_collection_duration_accepts_bounded_campaign_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path)
    reports = asyncio.run(_quality_reports(tmp_path, storage, policy))
    _patch_collectors(monkeypatch, calls)
    _patch_quality_analysis(monkeypatch, reports)

    result = asyncio.run(
        collect_paired_quality(
            storage_config=storage,
            quality_config=policy,
            duration_seconds=duration,
            max_messages_per_venue=5,
            paired_collection_id=f"duration-{duration:g}",
        )
    )

    assert result.paired_report.overlap.requested_duration_seconds == duration
    assert [call[1].duration_seconds for call in calls] == [duration, duration]
    assert [call[1].max_messages for call in calls] == [5, 5]
    assert all(
        call[1].max_phase_duration_seconds == MAX_PAIRED_COLLECTION_DURATION_SECONDS
        for call in calls
    )


@pytest.mark.parametrize("duration", [0, -1, 3601])
def test_paired_collection_duration_rejects_invalid_values_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    _patch_collectors(monkeypatch, calls)

    with pytest.raises(CollectionPreflightError):
        asyncio.run(
            collect_paired_quality(
                storage_config=storage_config(tmp_path),
                quality_config=quality_config(tmp_path),
                duration_seconds=duration,
            )
        )

    assert calls == []


@pytest.mark.parametrize("message_limit", [100_000, 50_000, 5_000])
def test_paired_collection_message_limit_passes_explicit_value_to_collectors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message_limit: int,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path)
    reports = asyncio.run(_quality_reports(tmp_path, storage, policy))
    _patch_collectors(monkeypatch, calls)
    _patch_quality_analysis(monkeypatch, reports)

    asyncio.run(
        collect_paired_quality(
            storage_config=storage,
            quality_config=policy,
            duration_seconds=180,
            max_messages_per_venue=message_limit,
            paired_collection_id=f"messages-{message_limit}",
        )
    )

    assert [call[1].max_messages for call in calls] == [message_limit, message_limit]


def test_paired_collection_message_limit_none_uses_quality_policy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path)
    reports = asyncio.run(_quality_reports(tmp_path, storage, policy))
    _patch_collectors(monkeypatch, calls)
    _patch_quality_analysis(monkeypatch, reports)

    asyncio.run(
        collect_paired_quality(
            storage_config=storage,
            quality_config=policy,
            duration_seconds=180,
            max_messages_per_venue=None,
            paired_collection_id="messages-policy-fallback",
        )
    )

    assert [call[1].max_messages for call in calls] == [
        policy.max_messages_per_venue,
        policy.max_messages_per_venue,
    ]


@pytest.mark.parametrize("message_limit", [0, 100_001])
def test_paired_collection_message_limit_rejects_invalid_values_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message_limit: int,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    _patch_collectors(monkeypatch, calls)

    with pytest.raises(CollectionPreflightError):
        asyncio.run(
            collect_paired_quality(
                storage_config=storage_config(tmp_path),
                quality_config=quality_config(tmp_path),
                duration_seconds=180,
                max_messages_per_venue=message_limit,
            )
        )

    assert calls == []


def test_campaign_1860_second_duration_reaches_paired_collector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path)
    reports = asyncio.run(_quality_reports(tmp_path, storage, policy))
    _patch_collectors(monkeypatch, calls)
    _patch_quality_analysis(monkeypatch, reports)
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "a" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "a" * 40)
    config = _temp_campaign_config(tmp_path, requested_duration_seconds=1860)
    registry = initialize_campaign(
        config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml")
    )

    attempt = asyncio.run(
        run_campaign_slot(
            config,
            slot_id="P01",
            storage_config=storage,
            quality_config=policy,
            now=config.slot_by_id("P01").planned_start_utc,
        )
    )

    assert registry.runtime_git_commit == "a" * 40
    assert attempt.requested_duration_seconds == 1860
    assert attempt.maximum_messages_per_venue == 100_000
    assert attempt.attempt_runtime_git_commit == "a" * 40
    assert [call[1].duration_seconds for call in calls] == [1860, 1860]
    assert [call[1].max_messages for call in calls] == [100_000, 100_000]
    assert all(
        call[1].max_phase_duration_seconds == MAX_PAIRED_COLLECTION_DURATION_SECONDS
        for call in calls
    )
    assert attempt.attempt_status == AttemptStatus.REJECTED
    assert (attempt.exclusion_reason or "").startswith(
        AttemptExclusionReason.INSUFFICIENT_PAIRED_OVERLAP.value
    )


def test_campaign_excessive_duration_records_preflight_failure_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    _patch_collectors(monkeypatch, calls)
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "b" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "b" * 40)
    config = _temp_campaign_config(tmp_path, requested_duration_seconds=3600)
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    bad_config = config.model_copy(update={"requested_duration_seconds": 3601})

    attempt = asyncio.run(
        run_campaign_slot(
            bad_config,
            slot_id="P01",
            storage_config=storage_config(tmp_path),
            quality_config=quality_config(tmp_path),
            now=bad_config.slot_by_id("P01").planned_start_utc,
        )
    )

    assert calls == []
    assert attempt.attempt_status == AttemptStatus.FAILED
    assert attempt.failure_classification == FailureClassification.COLLECTION_PREFLIGHT_FAILURE
    assert "configured maximum of 3600 seconds" in (attempt.failure_message or "")


def test_campaign_excessive_message_limit_records_preflight_failure_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    _patch_collectors(monkeypatch, calls)
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "b" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "b" * 40)
    config = _temp_campaign_config(tmp_path, requested_duration_seconds=1860)
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))
    bad_config = config.model_copy(update={"maximum_messages_per_venue": 100_001})

    attempt = asyncio.run(
        run_campaign_slot(
            bad_config,
            slot_id="P01",
            storage_config=storage_config(tmp_path),
            quality_config=quality_config(tmp_path),
            now=bad_config.slot_by_id("P01").planned_start_utc,
        )
    )

    assert calls == []
    assert attempt.attempt_status == AttemptStatus.FAILED
    assert attempt.failure_classification == FailureClassification.COLLECTION_PREFLIGHT_FAILURE
    assert "configured maximum of 100000" in (attempt.failure_message or "")


def test_campaign_quality_rejection_reason_stays_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Exchange, RunLimits]] = []
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path)
    reports = asyncio.run(_quality_reports(tmp_path, storage, policy))
    rejected_coinbase = reports[0].model_copy(
        update={
            "disposition": QualityDisposition.REJECTED,
            "disposition_reasons": ("synthetic quality rejection",),
        }
    )
    _patch_collectors(monkeypatch, calls)
    _patch_quality_analysis(monkeypatch, (rejected_coinbase, reports[1]))
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "c" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "c" * 40)
    config = _temp_campaign_config(tmp_path, requested_duration_seconds=1860)
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))

    attempt = asyncio.run(
        run_campaign_slot(
            config,
            slot_id="P01",
            storage_config=storage,
            quality_config=policy,
            now=config.slot_by_id("P01").planned_start_utc,
        )
    )

    assert attempt.attempt_status == AttemptStatus.REJECTED
    assert attempt.exclusion_reason == AttemptExclusionReason.COINBASE_QUALITY_NOT_ACCEPTED.value


def test_campaign_config_and_runtime_share_duration_maximum(tmp_path: Path) -> None:
    CampaignConfig.model_validate(
        _campaign_payload(
            tmp_path, requested_duration_seconds=int(MAX_PAIRED_COLLECTION_DURATION_SECONDS)
        )
    )
    payload = _campaign_payload(tmp_path, requested_duration_seconds=3601)
    with pytest.raises(Exception, match="less than or equal"):
        CampaignConfig.model_validate(payload)


def test_campaign_config_and_runtime_share_message_limit_maximum(tmp_path: Path) -> None:
    CampaignConfig.model_validate(
        _campaign_payload(
            tmp_path,
            requested_duration_seconds=1860,
            maximum_messages_per_venue=MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE,
        )
    )
    payload = _campaign_payload(
        tmp_path,
        requested_duration_seconds=1860,
        maximum_messages_per_venue=MAX_PAIRED_COLLECTION_MESSAGES_PER_VENUE + 1,
    )
    with pytest.raises(Exception, match="less than or equal"):
        CampaignConfig.model_validate(payload)


async def _quality_reports(
    tmp_path: Path,
    storage: StorageConfig,
    policy: DataQualityConfig,
) -> tuple[SessionQualityReport, SessionQualityReport]:
    coinbase_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-duration-test",
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-duration-test",
    )
    return (
        analyze_session_quality(coinbase_session, storage_config=storage, quality_config=policy),
        analyze_session_quality(kraken_session, storage_config=storage, quality_config=policy),
    )


def _patch_collectors(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[Exchange, RunLimits]],
) -> None:
    class FakeCollector:
        def __init__(self, venue: Exchange) -> None:
            self.venue = venue

        async def collect(self, *, limits: RunLimits, archive_writer: Any) -> CollectorRunSummary:
            calls.append((self.venue, limits))
            started = datetime(2026, 7, 31, 17, 5, tzinfo=UTC)
            stats = SessionStatistics(
                venue=self.venue,
                canonical_instrument="BTC-USD",
                venue_symbol="BTC-USD" if self.venue == Exchange.COINBASE else "BTC/USD",
                configured_channels=("trades", "ticker"),
                session_id=f"{self.venue.value}-duration-test",
                started_at=started,
                frames_received=2,
                trade_events=1,
                top_of_book_events=1,
                final_state=CollectorState.STOPPED,
                ended_at=started,
            )
            return CollectorRunSummary(
                stats=stats,
                subscription_acknowledged=True,
                stop_reason="duration reached",
                archive_summary=None,
                data_persisted=True,
            )

    monkeypatch.setattr(
        "cross_venue.quality.collection.load_coinbase_live_collector",
        lambda: FakeCollector(Exchange.COINBASE),
    )
    monkeypatch.setattr(
        "cross_venue.quality.collection.load_kraken_live_collector",
        lambda: FakeCollector(Exchange.KRAKEN),
    )


def _patch_quality_analysis(
    monkeypatch: pytest.MonkeyPatch,
    reports: tuple[SessionQualityReport, SessionQualityReport],
) -> None:
    def fake_persist_summary_and_analyze(
        summary: CollectorRunSummary,
        *,
        storage_config: StorageConfig,
        quality_config: DataQualityConfig,
        pair_id: str,
        venue_name: str,
    ) -> SessionQualityReport:
        return reports[0] if venue_name == "coinbase" else reports[1]

    monkeypatch.setattr(
        "cross_venue.quality.collection._persist_summary_and_analyze",
        fake_persist_summary_and_analyze,
    )


def _temp_campaign_config(tmp_path: Path, *, requested_duration_seconds: int) -> CampaignConfig:
    return CampaignConfig.model_validate(
        _campaign_payload(tmp_path, requested_duration_seconds=requested_duration_seconds)
    )


def _campaign_payload(
    tmp_path: Path,
    *,
    requested_duration_seconds: int,
    maximum_messages_per_venue: int = 100_000,
) -> dict[str, Any]:
    config = load_campaign_config(Path("configs/campaigns/phase_3b_btc_usd.toml"))
    payload = config.model_dump(mode="python")
    payload.update(
        {
            "campaign_schema_version": "3b.2",
            "requested_duration_seconds": requested_duration_seconds,
            "maximum_messages_per_venue": maximum_messages_per_venue,
            "registry_root": tmp_path / "campaigns",
            "validated_manifest_root": tmp_path / "validated",
            "normalized_output_root": tmp_path / "normalized",
        }
    )
    return payload
