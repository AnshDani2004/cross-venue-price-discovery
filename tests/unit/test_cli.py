import subprocess
import sys
from datetime import UTC, datetime

from cross_venue import __version__
from cross_venue.cli import ArchivePersistenceResult, main
from cross_venue.collectors.lifecycle import CollectorState
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits, SessionStatistics
from cross_venue.config import StorageConfig
from cross_venue.schemas import Exchange
from cross_venue.storage.validation import ArchiveValidationResult


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "cross_venue", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_package_import_and_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_exits_successfully() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "Cross-venue price-discovery research utilities" in result.stdout
    assert "No live-trading" in result.stdout
    assert "available" in result.stdout


def test_cli_version_exits_successfully() -> None:
    result = run_cli("--version")

    assert result.returncode == 0
    assert f"cross-venue-price-discovery {__version__}" in result.stdout


def test_cli_invalid_command_exits_nonzero_with_clear_message() -> None:
    result = run_cli("collect")

    assert result.returncode != 0
    assert "invalid choice: 'collect'" in result.stderr


def test_cli_has_no_live_trading_command_surface() -> None:
    result = run_cli("--help")

    forbidden_terms = ["order", "cancel", "withdraw", "deposit", "trade-live"]
    help_text = result.stdout.lower()
    assert all(term not in help_text for term in forbidden_terms)


async def _successful_smoke_runner(_venue: str, _limits: RunLimits) -> CollectorRunSummary:
    stats = SessionStatistics(
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        configured_channels=("matches", "ticker", "heartbeat"),
        session_id="coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001",
        started_at=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        final_state=CollectorState.STOPPED,
        connections_opened=1,
        frames_received=1,
    )
    return CollectorRunSummary(
        stats=stats,
        subscription_acknowledged=True,
        stop_reason="message limit reached",
    )


async def _failed_smoke_runner(_venue: str, _limits: RunLimits) -> CollectorRunSummary:
    stats = SessionStatistics(
        venue=Exchange.KRAKEN,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC/USD",
        configured_channels=("trade", "ticker"),
        session_id="kraken_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001",
        started_at=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        final_state=CollectorState.FAILED,
        failure_reason="terminal failure",
    )
    return CollectorRunSummary(
        stats=stats,
        subscription_acknowledged=False,
        stop_reason="terminal failure",
    )


async def _successful_archive_runner(
    _venue: str,
    _limits: RunLimits,
    _storage_config: StorageConfig,
) -> ArchivePersistenceResult:
    stats = SessionStatistics(
        venue=Exchange.COINBASE,
        canonical_instrument="BTC-USD",
        venue_symbol="BTC-USD",
        configured_channels=("matches", "ticker", "heartbeat"),
        session_id="coinbase_BTC-USD_20260730T210000Z_00000000-0000-0000-0000-000000000001",
        started_at=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        final_state=CollectorState.STOPPED,
        connections_opened=1,
        frames_received=1,
    )
    return ArchivePersistenceResult(
        summary=CollectorRunSummary(
            stats=stats,
            subscription_acknowledged=True,
            stop_reason="message limit reached",
            data_persisted=True,
        ),
        validation=ArchiveValidationResult(
            valid=True,
            session_path=_storage_config.archive_root / "session=fake",
            shards_checked=1,
            records_checked=1,
        ),
    )


def test_smoke_collect_command_uses_fake_runner_and_prints_summary(capsys) -> None:
    exit_code = main(
        [
            "smoke-collect",
            "--venue",
            "coinbase",
            "--duration-seconds",
            "1",
            "--max-messages",
            "1",
            "--public-only",
            "--no-write",
        ],
        smoke_runner=_successful_smoke_runner,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Venue: coinbase" in output
    assert "Data persisted: no" in output


def test_smoke_collect_terminal_failure_exits_nonzero(capsys) -> None:
    exit_code = main(
        ["smoke-collect", "--venue", "kraken", "--duration-seconds", "1", "--max-messages", "1"],
        smoke_runner=_failed_smoke_runner,
    )

    assert exit_code == 1
    assert "Final state: failed" in capsys.readouterr().out


def test_smoke_collect_rejects_invalid_limits() -> None:
    result = run_cli("smoke-collect", "--venue", "coinbase", "--duration-seconds", "-1")

    assert result.returncode != 0
    assert "duration must be positive" in result.stderr


def test_smoke_collect_rejects_excessive_duration() -> None:
    result = run_cli("smoke-collect", "--venue", "kraken", "--duration-seconds", "121")

    assert result.returncode != 0
    assert "duration exceeds Phase 2B maximum" in result.stderr


def test_smoke_archive_command_uses_fake_runner_and_prints_validation(capsys) -> None:
    exit_code = main(
        [
            "smoke-archive",
            "--venue",
            "coinbase",
            "--duration-seconds",
            "1",
            "--max-messages",
            "1",
        ],
        archive_runner=_successful_archive_runner,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Data persisted: yes" in output
    assert "Archive validation: valid" in output


def test_smoke_archive_rejects_excessive_duration() -> None:
    result = run_cli("smoke-archive", "--venue", "kraken", "--duration-seconds", "31")

    assert result.returncode != 0
    assert "duration exceeds Phase 2B maximum" in result.stderr
