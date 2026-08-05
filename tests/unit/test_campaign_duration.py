from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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
from cross_venue.collectors.coinbase.collector import build_coinbase_runtime_spec
from cross_venue.collectors.kraken.collector import build_kraken_runtime_spec
from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.collectors.runtime import (
    CollectorRunSummary,
    CollectorStopReason,
    RunLimits,
    SessionStatistics,
    run_collector,
)
from cross_venue.collectors.sink import DiscardingEventSink
from cross_venue.config import DataQualityConfig, StorageConfig, load_venue_catalog_config
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.collection import PairedCollectionResult, collect_paired_quality
from cross_venue.quality.exceptions import CollectionPreflightError
from cross_venue.quality.models import QualityDisposition, SessionQualityReport
from cross_venue.quality.overlap import build_paired_quality_report
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


def test_campaign_100000_message_limit_reaches_live_collector_stop_predicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = storage_config(tmp_path)
    policy = _long_duration_quality_config(tmp_path)
    reports = _reports_with_frame_counts(
        asyncio.run(_quality_reports(tmp_path, storage, policy)),
        coinbase_frames=5001,
        kraken_frames=5001,
    )
    calls: list[tuple[Exchange, RunLimits]] = []
    catalog = load_venue_catalog_config(Path("configs/venues.toml"))
    coinbase_config = next(venue for venue in catalog.venues if venue.venue_id == Exchange.COINBASE)
    kraken_config = next(venue for venue in catalog.venues if venue.venue_id == Exchange.KRAKEN)
    monkeypatch.setattr(
        "cross_venue.quality.collection.load_coinbase_live_collector",
        lambda: _ScriptedRuntimeCollector(
            Exchange.COINBASE,
            build_coinbase_runtime_spec(coinbase_config),
            _coinbase_runtime_frames(5010),
            calls,
        ),
    )
    monkeypatch.setattr(
        "cross_venue.quality.collection.load_kraken_live_collector",
        lambda: _ScriptedRuntimeCollector(
            Exchange.KRAKEN,
            build_kraken_runtime_spec(kraken_config),
            _kraken_runtime_frames(5010),
            calls,
        ),
    )
    _patch_quality_analysis(monkeypatch, reports)
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "e" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "e" * 40)
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

    assert [call[1].duration_seconds for call in calls] == [1860, 1860]
    assert [call[1].max_messages for call in calls] == [100_000, 100_000]
    assert [call[1].max_phase_duration_seconds for call in calls] == [3600, 3600]
    assert attempt.coinbase_frame_count > 5000
    assert attempt.kraken_frame_count > 5000
    assert attempt.coinbase_effective_message_limit == 100_000
    assert attempt.kraken_effective_message_limit == 100_000
    assert attempt.coinbase_stop_reason == CollectorStopReason.REQUESTED_DURATION_REACHED.value
    assert attempt.kraken_stop_reason == CollectorStopReason.REQUESTED_DURATION_REACHED.value


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


def test_campaign_full_duration_accepted_pair_creates_validated_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = storage_config(tmp_path)
    policy = quality_config(tmp_path).model_copy(update={"policy_version": "2d.2"})
    result = asyncio.run(_accepted_full_duration_result(tmp_path, storage, policy))
    monkeypatch.setattr("cross_venue.campaigns.registry.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.runner.working_tree_clean", lambda: True)
    monkeypatch.setattr("cross_venue.campaigns.registry.current_git_commit", lambda: "d" * 40)
    monkeypatch.setattr("cross_venue.campaigns.runner.current_git_commit", lambda: "d" * 40)
    config = _temp_campaign_config(tmp_path, requested_duration_seconds=1860)
    initialize_campaign(config, config_path=Path("configs/campaigns/phase_3b_btc_usd.toml"))

    async def accepted_runner(
        duration_seconds: float, max_messages_per_venue: int
    ) -> PairedCollectionResult:
        assert duration_seconds == 1860
        assert max_messages_per_venue == 100_000
        return result

    attempt = asyncio.run(
        run_campaign_slot(
            config,
            slot_id="P01",
            storage_config=storage,
            quality_config=policy,
            runner=accepted_runner,
            now=config.slot_by_id("P01").planned_start_utc,
        )
    )

    assert attempt.attempt_status == AttemptStatus.ACCEPTED
    assert attempt.inclusion_status.value == "INCLUDED"
    assert attempt.validated_pair_manifest_id is not None
    assert attempt.validated_pair_manifest_sha256 is not None
    assert attempt.paired_overlap_seconds >= 1800
    assert attempt.coinbase_effective_message_limit == 100_000
    assert attempt.kraken_effective_message_limit == 100_000
    assert attempt.coinbase_stop_reason == CollectorStopReason.REQUESTED_DURATION_REACHED.value
    assert attempt.kraken_stop_reason == CollectorStopReason.REQUESTED_DURATION_REACHED.value


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


def _long_duration_quality_config(tmp_path: Path) -> DataQualityConfig:
    policy = quality_config(tmp_path)
    coverage = policy.quality.coverage.model_copy(
        update={
            "minimum_session_duration_seconds": 1860,
            "minimum_cross_venue_overlap_seconds": 900,
        }
    )
    sections = policy.quality.model_copy(update={"coverage": coverage})
    return policy.model_copy(
        update={
            "default_controlled_duration_seconds": 1860,
            "max_controlled_duration_seconds": 3600,
            "quality": sections,
        }
    )


def _reports_with_frame_counts(
    reports: tuple[SessionQualityReport, SessionQualityReport],
    *,
    coinbase_frames: int,
    kraken_frames: int,
) -> tuple[SessionQualityReport, SessionQualityReport]:
    updated = []
    for report, frames in zip(reports, (coinbase_frames, kraken_frames), strict=True):
        coverage = report.metrics.coverage.model_copy(update={"frames_received": frames})
        metrics = report.metrics.model_copy(update={"coverage": coverage})
        updated.append(report.model_copy(update={"metrics": metrics}))
    return (updated[0], updated[1])


async def _accepted_full_duration_result(
    tmp_path: Path,
    storage: StorageConfig,
    policy: DataQualityConfig,
) -> PairedCollectionResult:
    coinbase_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-full-duration-test",
        duration_seconds=2,
        frames=(
            (
                '{"type":"match","trade_id":1,"sequence":1,"product_id":"BTC-USD",'
                '"side":"buy","price":"100.00","size":"0.10",'
                '"time":"2026-07-30T21:00:00Z"}'
            ),
            (
                '{"type":"ticker","sequence":2,"product_id":"BTC-USD",'
                '"best_bid":"100.00","best_bid_size":"1.0",'
                '"best_ask":"100.10","best_ask_size":"2.0",'
                '"time":"2026-07-30T21:30:00Z","trade_id":2}'
            ),
        ),
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-full-duration-test",
        duration_seconds=2,
        frames=(
            (
                '{"channel":"trade","type":"update","data":[{"symbol":"BTC/USD",'
                '"side":"buy","price":"100.00","qty":"0.10","trade_id":1,'
                '"timestamp":"2026-07-30T21:00:00Z"}]}'
            ),
            (
                '{"channel":"ticker","type":"update","data":[{"symbol":"BTC/USD",'
                '"bid":"100.00","bid_qty":"1.0","ask":"100.10","ask_qty":"2.0",'
                '"timestamp":"2026-07-30T21:30:00Z"}]}'
            ),
        ),
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage,
        quality_config=policy,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage,
        quality_config=policy,
    )
    overlap_start = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    overlap_end = overlap_start + timedelta(seconds=1800)
    coinbase_report = _with_coverage_span(coinbase_report, overlap_start, overlap_end)
    kraken_report = _with_coverage_span(kraken_report, overlap_start, overlap_end)
    paired = build_paired_quality_report(
        paired_collection_id="paired-full-duration-test",
        requested_duration_seconds=1860,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=policy,
    )
    started = datetime(2026, 7, 31, 17, 5, tzinfo=UTC)
    limits = {
        "effective_duration_limit_seconds": 1860,
        "effective_message_limit": 100_000,
        "effective_phase_duration_limit_seconds": MAX_PAIRED_COLLECTION_DURATION_SECONDS,
    }
    coinbase_summary = CollectorRunSummary(
        stats=SessionStatistics(
            venue=Exchange.COINBASE,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC-USD",
            configured_channels=("matches", "ticker", "heartbeat"),
            session_id=coinbase_report.session_id,
            started_at=started,
            ended_at=started,
            frames_received=2,
            trade_events=1,
            top_of_book_events=1,
            final_state=CollectorState.STOPPED,
        ),
        subscription_acknowledged=True,
        stop_reason=CollectorStopReason.REQUESTED_DURATION_REACHED,
        **limits,
    )
    kraken_summary = CollectorRunSummary(
        stats=SessionStatistics(
            venue=Exchange.KRAKEN,
            canonical_instrument="BTC-USD",
            venue_symbol="BTC/USD",
            configured_channels=("trade", "ticker"),
            session_id=kraken_report.session_id,
            started_at=started,
            ended_at=started,
            frames_received=2,
            trade_events=1,
            top_of_book_events=1,
            final_state=CollectorState.STOPPED,
        ),
        subscription_acknowledged=True,
        stop_reason=CollectorStopReason.REQUESTED_DURATION_REACHED,
        **limits,
    )
    return PairedCollectionResult(
        paired_report=paired,
        coinbase_summary=coinbase_summary,
        kraken_summary=kraken_summary,
        coinbase_report_path=policy.report_root / "coinbase-full-duration-test.json",
        kraken_report_path=policy.report_root / "kraken-full-duration-test.json",
        paired_report_path=policy.report_root / "paired-full-duration-test.json",
    )


def _with_coverage_span(
    report: SessionQualityReport,
    start: datetime,
    end: datetime,
) -> SessionQualityReport:
    coverage = report.metrics.coverage.model_copy(
        update={
            "session_duration_seconds": 1860,
            "first_market_event_ts": start,
            "last_market_event_ts": end,
            "first_top_of_book_ts": start,
            "last_top_of_book_ts": end,
        }
    )
    metrics = report.metrics.model_copy(update={"coverage": coverage})
    return report.model_copy(update={"metrics": metrics})


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


class _ScriptedRuntimeCollector:
    def __init__(
        self,
        venue: Exchange,
        spec: Any,
        frames: list[str],
        calls: list[tuple[Exchange, RunLimits]],
    ) -> None:
        self.venue = venue
        self.spec = spec
        self.frames = frames
        self.calls = calls
        self.clock = _ScriptedClock()

    async def collect(self, *, limits: RunLimits, archive_writer: Any) -> CollectorRunSummary:
        self.calls.append((self.venue, limits))
        return await run_collector(
            self.spec,
            connector=_ScriptedConnector(
                [_ScriptedConnection(self.frames, self.clock, seconds_per_recv=0.372)]
            ),
            sink=DiscardingEventSink(),
            limits=limits,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleeper=self.clock.sleep,
            archive_writer=archive_writer,
        )


class _ScriptedConnection:
    def __init__(
        self,
        frames: list[str],
        clock: _ScriptedClock,
        *,
        seconds_per_recv: float,
    ) -> None:
        self.frames = frames
        self.clock = clock
        self.seconds_per_recv = seconds_per_recv
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        self.clock.monotonic_time += self.seconds_per_recv
        if not self.frames:
            raise TimeoutError("script exhausted")
        return self.frames.pop(0)

    async def close(self) -> None:
        return None


class _ScriptedConnector:
    def __init__(self, connections: list[_ScriptedConnection]) -> None:
        self.connections = connections

    async def connect(
        self,
        url: str,
        *,
        open_timeout_seconds: float,
        max_message_bytes: int,
    ) -> _ScriptedConnection:
        _ = (url, open_timeout_seconds, max_message_bytes)
        return self.connections.pop(0)


class _ScriptedClock:
    def __init__(self) -> None:
        self.now_calls = 0
        self.monotonic_time = 0.0

    def now(self) -> datetime:
        self.now_calls += 1
        return datetime(2026, 7, 31, 17, tzinfo=UTC) + timedelta(seconds=self.now_calls)

    def monotonic(self) -> float:
        return self.monotonic_time

    async def sleep(self, delay_seconds: float) -> None:
        self.monotonic_time += delay_seconds


def _coinbase_runtime_frames(count: int) -> list[str]:
    frames = [
        (
            '{"type":"subscriptions","channels":['
            '{"name":"matches","product_ids":["BTC-USD"]},'
            '{"name":"ticker","product_ids":["BTC-USD"]},'
            '{"name":"heartbeat","product_ids":["BTC-USD"]}]}'
        )
    ]
    for index in range(1, count):
        ts = (datetime(2026, 7, 31, 17, tzinfo=UTC) + timedelta(seconds=index)).isoformat()
        if index == 1:
            frames.append(
                '{"type":"match","trade_id":1,"sequence":1,"product_id":"BTC-USD",'
                '"side":"buy","price":"100.00","size":"0.10",'
                f'"time":"{ts.replace("+00:00", "Z")}"'
                "}"
            )
        else:
            frames.append(
                '{"type":"ticker","sequence":'
                f'{index},"product_id":"BTC-USD","best_bid":"100.00",'
                '"best_bid_size":"1.0","best_ask":"100.10","best_ask_size":"2.0",'
                f'"time":"{ts.replace("+00:00", "Z")}","trade_id":{index}'
                "}"
            )
    return frames


def _kraken_runtime_frames(count: int) -> list[str]:
    frames = [
        (
            '{"method":"subscribe","result":{"channel":"trade","symbol":"BTC/USD",'
            '"snapshot":true},"success":true,'
            '"time_in":"2026-07-31T17:00:00.000000Z",'
            '"time_out":"2026-07-31T17:00:00.001000Z"}'
        ),
        (
            '{"method":"subscribe","result":{"channel":"ticker","symbol":"BTC/USD",'
            '"snapshot":true},"success":true,'
            '"time_in":"2026-07-31T17:00:00.000000Z",'
            '"time_out":"2026-07-31T17:00:00.001000Z"}'
        ),
    ]
    for index in range(2, count):
        ts = (datetime(2026, 7, 31, 17, tzinfo=UTC) + timedelta(seconds=index)).isoformat()
        if index == 2:
            frames.append(
                '{"channel":"trade","type":"update","data":[{"symbol":"BTC/USD",'
                '"side":"buy","price":"100.00","qty":"0.10","trade_id":1,'
                f'"timestamp":"{ts.replace("+00:00", "Z")}"'
                "}]} "
            )
        else:
            frames.append(
                '{"channel":"ticker","type":"update","data":[{"symbol":"BTC/USD",'
                '"bid":"100.00","bid_qty":"1.0","ask":"100.10","ask_qty":"2.0",'
                f'"timestamp":"{ts.replace("+00:00", "Z")}"'
                "}]}"
            )
    return frames


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
