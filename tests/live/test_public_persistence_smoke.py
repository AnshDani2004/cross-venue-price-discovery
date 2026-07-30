import os
import subprocess
from pathlib import Path

import pytest

from cross_venue.collectors.coinbase.collector import load_coinbase_live_collector
from cross_venue.collectors.kraken.collector import load_kraken_live_collector
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits
from cross_venue.config import load_storage_config
from cross_venue.storage.archive_writer import RotatingRawArchiveWriter
from cross_venue.storage.manifest_store import persist_manifest
from cross_venue.storage.quality_store import persist_quality_summary
from cross_venue.storage.session import build_manifest, build_quality_summary
from cross_venue.storage.validation import validate_archive

pytestmark = pytest.mark.live_persistence


def _live_persistence_enabled() -> bool:
    return os.environ.get("CROSS_VENUE_ENABLE_LIVE_PERSISTENCE") == "1"


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip() or "unknown"


async def _collect_with_archive(venue: str) -> CollectorRunSummary:
    storage_config = load_storage_config(Path("configs/storage.toml"))
    writer = RotatingRawArchiveWriter(storage_config=storage_config)
    limits = RunLimits(
        duration_seconds=20,
        max_messages=2000,
        max_phase_duration_seconds=30,
    )
    if venue == "coinbase":
        summary = await load_coinbase_live_collector().collect(
            limits=limits,
            archive_writer=writer,
        )
    else:
        summary = await load_kraken_live_collector().collect(
            limits=limits,
            archive_writer=writer,
        )
    assert summary.archive_summary is not None
    persist_manifest(
        summary.archive_summary.session_paths.manifest_path,
        build_manifest(summary, git_commit=_git_commit()),
    )
    persist_quality_summary(
        summary.archive_summary.session_paths.quality_path,
        build_quality_summary(summary),
    )
    return summary


@pytest.mark.asyncio
async def test_coinbase_public_persistence_smoke() -> None:
    if not _live_persistence_enabled():
        pytest.skip(
            "set CROSS_VENUE_ENABLE_LIVE_PERSISTENCE=1 to run public Coinbase archival smoke test"
        )

    summary = await _collect_with_archive("coinbase")
    assert summary.archive_summary is not None
    validation = validate_archive(summary.archive_summary.session_paths.session_root)
    print(summary.to_text())
    print(validation.to_text())

    assert summary.stats.connections_opened >= 1
    assert summary.subscription_acknowledged
    assert summary.stats.frames_received >= 1
    assert summary.stats.archive_records_written == summary.stats.frames_received
    assert validation.valid


@pytest.mark.asyncio
async def test_kraken_public_persistence_smoke() -> None:
    if not _live_persistence_enabled():
        pytest.skip(
            "set CROSS_VENUE_ENABLE_LIVE_PERSISTENCE=1 to run public Kraken archival smoke test"
        )

    summary = await _collect_with_archive("kraken")
    assert summary.archive_summary is not None
    validation = validate_archive(summary.archive_summary.session_paths.session_root)
    print(summary.to_text())
    print(validation.to_text())

    assert summary.stats.connections_opened >= 1
    assert summary.subscription_acknowledged
    assert summary.stats.frames_received >= 1
    assert summary.stats.archive_records_written == summary.stats.frames_received
    assert validation.valid
