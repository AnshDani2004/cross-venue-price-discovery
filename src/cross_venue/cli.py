"""Command-line interface for project inspection and phase-safe utilities."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cross_venue import __version__
from cross_venue.collectors.coinbase.collector import load_coinbase_live_collector
from cross_venue.collectors.kraken.collector import load_kraken_live_collector
from cross_venue.collectors.runtime import CollectorRunSummary, RunLimits
from cross_venue.config import StorageConfig, load_storage_config
from cross_venue.storage.archive_writer import RotatingRawArchiveWriter
from cross_venue.storage.exceptions import StorageError
from cross_venue.storage.manifest_store import persist_manifest
from cross_venue.storage.paths import resolve_under_root
from cross_venue.storage.quality_store import persist_quality_summary
from cross_venue.storage.recovery import RecoveryResult, recover_session
from cross_venue.storage.session import build_manifest, build_quality_summary
from cross_venue.storage.validation import ArchiveValidationResult, validate_archive


class SmokeRunner(Protocol):
    """Injectable smoke runner for CLI tests."""

    async def __call__(self, venue: str, limits: RunLimits) -> CollectorRunSummary:
        """Run a bounded smoke collection."""


@dataclass(frozen=True, slots=True)
class ArchivePersistenceResult:
    """Result for an opt-in archival smoke run."""

    summary: CollectorRunSummary
    validation: ArchiveValidationResult

    @property
    def successful(self) -> bool:
        return self.summary.completed_successfully and self.validation.valid

    def to_text(self) -> str:
        archive = self.summary.archive_summary
        session_path = archive.session_paths.session_root if archive is not None else "unavailable"
        lines = [
            self.summary.to_text(),
            f"Archive session path: {session_path}",
            f"Archive validation: {'valid' if self.validation.valid else 'invalid'}",
        ]
        if archive is not None:
            lines.extend(
                [
                    f"Manifest path: {archive.session_paths.manifest_path}",
                    f"Quality summary path: {archive.session_paths.quality_path}",
                    f"Checksum status: {archive.checksum_status}",
                    f"Partial files remaining: {archive.partial_files_remaining}",
                ]
            )
        if self.validation.errors:
            lines.extend(f"Validation error: {error}" for error in self.validation.errors)
        return "\n".join(lines)


class ArchiveRunner(Protocol):
    """Injectable archive runner for CLI tests."""

    async def __call__(
        self,
        venue: str,
        limits: RunLimits,
        storage_config: StorageConfig,
    ) -> ArchivePersistenceResult:
        """Run a bounded archival collection."""


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
    archive = subparsers.add_parser(
        "smoke-archive",
        help="run a bounded public WebSocket collection with raw archival",
        description=(
            "Run a bounded public-only WebSocket collection and persist exact raw frames "
            "to ignored local data directories."
        ),
    )
    archive.add_argument("--venue", choices=("coinbase", "kraken"), required=True)
    archive.add_argument("--duration-seconds", type=float, default=20.0)
    archive.add_argument("--max-messages", type=int, default=2000)
    archive.add_argument(
        "--storage-config",
        type=Path,
        default=Path("configs/storage.toml"),
        help="path to Phase 2C storage configuration",
    )
    validate = subparsers.add_parser(
        "validate-archive",
        help="validate a finalized raw archive session",
    )
    validate.add_argument("--session-path", type=Path, required=True)
    validate.add_argument(
        "--storage-config",
        type=Path,
        default=Path("configs/storage.toml"),
        help="path to Phase 2C storage configuration",
    )
    recover = subparsers.add_parser(
        "recover-session",
        help="inspect or recover interrupted raw archive partial shards",
    )
    recover.add_argument("--session-path", type=Path, required=True)
    recover.add_argument(
        "--apply",
        action="store_true",
        help="apply recovery; without this flag the command is a dry run",
    )
    recover.add_argument(
        "--storage-config",
        type=Path,
        default=Path("configs/storage.toml"),
        help="path to Phase 2C storage configuration",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    smoke_runner: SmokeRunner | None = None,
    archive_runner: ArchiveRunner | None = None,
) -> int:
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
    if args.command == "smoke-archive":
        try:
            limits = RunLimits(
                duration_seconds=args.duration_seconds,
                max_messages=args.max_messages,
                max_phase_duration_seconds=30.0,
            )
            storage_config = load_storage_config(args.storage_config)
        except ValueError as exc:
            parser.error(str(exc))
        archive_command_runner = archive_runner or _run_smoke_archive
        try:
            archive_result = asyncio.run(archive_command_runner(args.venue, limits, storage_config))
        except StorageError as exc:
            print(f"Archive error: {exc}")
            return 1
        print(archive_result.to_text())
        return 0 if archive_result.successful else 1
    if args.command == "validate-archive":
        storage_config = load_storage_config(args.storage_config)
        session_path = _resolve_session_arg(storage_config, args.session_path)
        validation_result = validate_archive(session_path)
        print(validation_result.to_text())
        return 0 if validation_result.valid else 1
    if args.command == "recover-session":
        storage_config = load_storage_config(args.storage_config)
        session_path = _resolve_session_arg(storage_config, args.session_path)
        recovery_result: RecoveryResult = recover_session(session_path, apply=args.apply)
        print(recovery_result.to_text())
        return 0 if recovery_result.successful else 1
    return 0


async def _run_smoke_collect(venue: str, limits: RunLimits) -> CollectorRunSummary:
    if venue == "coinbase":
        return await load_coinbase_live_collector().collect(limits=limits)
    if venue == "kraken":
        return await load_kraken_live_collector().collect(limits=limits)
    raise ValueError(f"unsupported venue: {venue}")


async def _run_smoke_archive(
    venue: str,
    limits: RunLimits,
    storage_config: StorageConfig,
) -> ArchivePersistenceResult:
    writer = RotatingRawArchiveWriter(storage_config=storage_config)
    if venue == "coinbase":
        summary = await load_coinbase_live_collector().collect(limits=limits, archive_writer=writer)
    elif venue == "kraken":
        summary = await load_kraken_live_collector().collect(limits=limits, archive_writer=writer)
    else:
        raise ValueError(f"unsupported venue: {venue}")
    if summary.archive_summary is None:
        raise StorageError("archive summary missing after archival run")
    manifest = build_manifest(summary, git_commit=_current_git_commit())
    quality = build_quality_summary(summary)
    persist_manifest(summary.archive_summary.session_paths.manifest_path, manifest)
    persist_quality_summary(summary.archive_summary.session_paths.quality_path, quality)
    validation = validate_archive(summary.archive_summary.session_paths.session_root)
    return ArchivePersistenceResult(summary=summary, validation=validation)


def _resolve_session_arg(storage_config: StorageConfig, session_path: Path) -> Path:
    return resolve_under_root(storage_config.archive_root, session_path)


def _current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
