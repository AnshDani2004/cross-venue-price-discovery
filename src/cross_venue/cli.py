"""Command-line interface for project inspection and phase-safe utilities."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from typing import Protocol

from cross_venue import __version__
from cross_venue.collectors.coinbase.collector import load_coinbase_live_collector
from cross_venue.collectors.kraken.collector import load_kraken_live_collector
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits


class SmokeRunner(Protocol):
    """Injectable smoke runner for CLI tests."""

    async def __call__(self, venue: str, limits: RunLimits) -> CollectorRunSummary:
        """Run a bounded smoke collection."""


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser."""

    parser = argparse.ArgumentParser(
        prog="python -m cross_venue",
        description=(
            "Cross-venue price-discovery research utilities. "
            "No live-trading commands are available."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cross-venue-price-discovery {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    smoke = subparsers.add_parser(
        "smoke-collect",
        help="run a bounded public no-write WebSocket smoke collection",
        description=(
            "Run a bounded public-only, no-write WebSocket smoke collection. "
            "No market data is persisted."
        ),
    )
    smoke.add_argument("--venue", choices=("coinbase", "kraken"), required=True)
    smoke.add_argument("--duration-seconds", type=float, default=30.0)
    smoke.add_argument("--max-messages", type=int, default=500)
    smoke.add_argument(
        "--public-only",
        action="store_true",
        help="affirm that this command uses public unauthenticated feeds only",
    )
    smoke.add_argument(
        "--no-write",
        action="store_true",
        help="affirm that this command performs no persistence",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, smoke_runner: SmokeRunner | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "smoke-collect":
        try:
            limits = RunLimits(
                duration_seconds=args.duration_seconds,
                max_messages=args.max_messages,
            )
        except ValueError as exc:
            parser.error(str(exc))
        runner = smoke_runner or _run_smoke_collect
        summary = asyncio.run(runner(args.venue, limits))
        print(summary.to_text())
        return 0 if summary.completed_successfully else 1
    return 0


async def _run_smoke_collect(venue: str, limits: RunLimits) -> CollectorRunSummary:
    if venue == "coinbase":
        return await load_coinbase_live_collector().collect(limits=limits)
    if venue == "kraken":
        return await load_kraken_live_collector().collect(limits=limits)
    raise ValueError(f"unsupported venue: {venue}")
