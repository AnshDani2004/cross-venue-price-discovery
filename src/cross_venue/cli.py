"""Command-line interface for project inspection and phase-safe utilities."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cross_venue import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser."""

    parser = argparse.ArgumentParser(
        prog="python -m cross_venue",
        description=(
            "Cross-venue price-discovery research utilities. "
            "No live-trading or live collection commands are available in Phase 2A."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cross-venue-price-discovery {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    parser.parse_args(argv)
    return 0
