import subprocess
import sys

from cross_venue import __version__


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
    assert "unrecognized arguments: collect" in result.stderr


def test_cli_has_no_live_trading_command_surface() -> None:
    result = run_cli("--help")

    forbidden_terms = ["order", "cancel", "withdraw", "deposit", "position", "trade-live"]
    help_text = result.stdout.lower()
    assert all(term not in help_text for term in forbidden_terms)
