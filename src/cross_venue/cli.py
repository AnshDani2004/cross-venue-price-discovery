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
from cross_venue.config import (
    DataQualityConfig,
    StorageConfig,
    load_data_quality_config,
    load_storage_config,
)
from cross_venue.quality.aggregation import aggregate_quality_reports
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.calibration import reanalyze_calibrated_pair
from cross_venue.quality.collection import PairedCollectionResult, collect_paired_quality
from cross_venue.quality.exceptions import PromotionError, QualityError
from cross_venue.quality.investigation import investigate_quality_findings
from cross_venue.quality.io import persist_model_json, portable_relative_path
from cross_venue.quality.models import PairedQualityReport, SessionQualityReport
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import promote_dataset
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


class PairedQualityRunner(Protocol):
    """Injectable paired quality runner for CLI tests."""

    async def __call__(
        self,
        storage_config: StorageConfig,
        quality_config: DataQualityConfig,
        duration_seconds: float,
        max_messages_per_venue: int,
    ) -> PairedCollectionResult:
        """Run a bounded paired quality collection."""


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
    analyze_session = subparsers.add_parser(
        "analyze-session-quality",
        help="analyze a finalized raw archive session",
    )
    analyze_session.add_argument("--session-path", type=Path, required=True)
    analyze_session.add_argument("--output-path", type=Path)
    analyze_session.add_argument(
        "--storage-config", type=Path, default=Path("configs/storage.toml")
    )
    analyze_session.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    analyze_pair = subparsers.add_parser(
        "analyze-paired-quality",
        help="analyze two finalized venue sessions as a pair",
    )
    analyze_pair.add_argument("--coinbase-session", type=Path, required=True)
    analyze_pair.add_argument("--kraken-session", type=Path, required=True)
    analyze_pair.add_argument("--paired-collection-id", default="manual-pair")
    analyze_pair.add_argument("--requested-duration-seconds", type=float, default=120.0)
    analyze_pair.add_argument("--output-path", type=Path)
    analyze_pair.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    analyze_pair.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    aggregate = subparsers.add_parser(
        "aggregate-quality",
        help="aggregate session quality reports under an input root",
    )
    aggregate.add_argument("--input-root", type=Path, required=True)
    aggregate.add_argument("--output-path", type=Path)
    aggregate.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    promote = subparsers.add_parser(
        "promote-dataset",
        help="dry-run or apply validated dataset manifest promotion",
    )
    promote.add_argument("--paired-report", type=Path, required=True)
    promote.add_argument("--apply", action="store_true")
    promote.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    investigate = subparsers.add_parser(
        "investigate-quality-findings",
        help="investigate quarantined paired quality findings without mutating source reports",
    )
    investigate.add_argument("--paired-report", type=Path, required=True)
    investigate.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    investigate.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    calibrated = subparsers.add_parser(
        "reanalyze-calibrated-pair",
        help="reanalyze an existing paired report under the active calibrated quality policy",
    )
    calibrated.add_argument("--paired-report", type=Path, required=True)
    calibrated.add_argument(
        "--storage-config",
        type=Path,
        default=Path("configs/storage.toml"),
    )
    calibrated.add_argument(
        "--quality-policy", type=Path, default=Path("configs/data_quality.toml")
    )
    calibrated.add_argument("--expected-commit")
    paired = subparsers.add_parser(
        "collect-paired-quality",
        help="run bounded paired Coinbase/Kraken archival collection and quality analysis",
    )
    paired.add_argument("--duration-seconds", type=float, default=120.0)
    paired.add_argument("--max-messages-per-venue", type=int, default=20_000)
    paired.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    paired.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    smoke_runner: SmokeRunner | None = None,
    archive_runner: ArchiveRunner | None = None,
    paired_quality_runner: PairedQualityRunner | None = None,
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
    if args.command == "analyze-session-quality":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        session_path = _resolve_session_arg(storage_config, args.session_path)
        output_path = args.output_path or _default_session_quality_path(
            quality_config,
            session_path,
        )
        output_path = resolve_under_root(quality_config.report_root, output_path)
        report = analyze_session_quality(
            session_path,
            storage_config=storage_config,
            quality_config=quality_config,
            report_path=output_path,
        )
        report = report.model_copy(
            update={
                "report_relative_path": portable_relative_path(
                    quality_config.report_root,
                    output_path,
                )
            }
        )
        persist_model_json(output_path, report)
        print(_session_report_text(report, output_path))
        return 0 if report.disposition.value != "REJECTED" else 1
    if args.command == "analyze-paired-quality":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        coinbase_report = analyze_session_quality(
            _resolve_session_arg(storage_config, args.coinbase_session),
            storage_config=storage_config,
            quality_config=quality_config,
        )
        kraken_report = analyze_session_quality(
            _resolve_session_arg(storage_config, args.kraken_session),
            storage_config=storage_config,
            quality_config=quality_config,
        )
        start_skew = abs(
            (coinbase_report.analysis_timestamp - kraken_report.analysis_timestamp).total_seconds()
        )
        paired_report = build_paired_quality_report(
            paired_collection_id=args.paired_collection_id,
            requested_duration_seconds=args.requested_duration_seconds,
            start_skew_seconds=start_skew,
            coinbase_report=coinbase_report,
            kraken_report=kraken_report,
            quality_config=quality_config,
        )
        output_path = args.output_path or (
            quality_config.report_root
            / "paired"
            / args.paired_collection_id
            / "paired_quality_report.json"
        )
        output_path = resolve_under_root(quality_config.report_root, output_path)
        paired_report = paired_report.model_copy(
            update={
                "paired_report_relative_path": portable_relative_path(
                    quality_config.report_root,
                    output_path,
                )
            }
        )
        persist_model_json(output_path, paired_report)
        print(_paired_report_text(paired_report, output_path))
        return 0 if paired_report.disposition.value != "REJECTED" else 1
    if args.command == "aggregate-quality":
        quality_config = load_data_quality_config(args.quality_policy)
        input_root = resolve_under_root(quality_config.report_root, args.input_root)
        reports = [
            SessionQualityReport.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(input_root.rglob("*session_quality_report.json"))
        ]
        aggregate_report = aggregate_quality_reports(reports, quality_config=quality_config)
        output_path = args.output_path or (quality_config.report_root / "aggregate_quality.json")
        output_path = resolve_under_root(quality_config.report_root, output_path)
        persist_model_json(output_path, aggregate_report)
        print(
            f"Aggregate sessions: {aggregate_report.session_count}\n"
            f"Accepted: {aggregate_report.accepted_count}\n"
            f"Quarantined: {aggregate_report.quarantined_count}\n"
            f"Rejected: {aggregate_report.rejected_count}\n"
            f"Report: {output_path}"
        )
        return 0
    if args.command == "promote-dataset":
        quality_config = load_data_quality_config(args.quality_policy)
        paired_path = resolve_under_root(quality_config.report_root, args.paired_report)
        paired_report = PairedQualityReport.model_validate_json(
            paired_path.read_text(encoding="utf-8")
        )
        try:
            _manifest, message = promote_dataset(
                paired_report,
                quality_config=quality_config,
                apply=args.apply,
            )
        except (PromotionError, QualityError) as exc:
            print(f"Promotion blocked: {exc}")
            return 1
        print(message)
        return 0
    if args.command == "investigate-quality-findings":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        try:
            investigation_result = investigate_quality_findings(
                args.paired_report,
                storage_config=storage_config,
                quality_config=quality_config,
            )
        except (QualityError, StorageError) as exc:
            print(f"Investigation blocked: {exc}")
            return 1
        print(investigation_result.to_text())
        return 0
    if args.command == "reanalyze-calibrated-pair":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        try:
            calibrated_result = reanalyze_calibrated_pair(
                args.paired_report,
                storage_config=storage_config,
                quality_config=quality_config,
                expected_commit=args.expected_commit,
            )
        except (QualityError, StorageError) as exc:
            print(f"Calibrated reanalysis blocked: {exc}")
            return 1
        print(calibrated_result.to_text())
        return 0
    if args.command == "collect-paired-quality":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        paired_command_runner = paired_quality_runner or _run_collect_paired_quality
        try:
            paired_collection_result = asyncio.run(
                paired_command_runner(
                    storage_config,
                    quality_config,
                    args.duration_seconds,
                    args.max_messages_per_venue,
                )
            )
        except (ValueError, QualityError, StorageError) as exc:
            print(f"Paired quality collection failed: {exc}")
            return 1
        print(paired_collection_result.to_text())
        return 0 if paired_collection_result.paired_report.disposition.value != "REJECTED" else 1
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


async def _run_collect_paired_quality(
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    duration_seconds: float,
    max_messages_per_venue: int,
) -> PairedCollectionResult:
    return await collect_paired_quality(
        storage_config=storage_config,
        quality_config=quality_config,
        duration_seconds=duration_seconds,
        max_messages_per_venue=max_messages_per_venue,
    )


def _default_session_quality_path(quality_config: DataQualityConfig, session_path: Path) -> Path:
    return (
        quality_config.report_root / "sessions" / session_path.name / "session_quality_report.json"
    )


def _session_report_text(report: SessionQualityReport, path: Path) -> str:
    return "\n".join(
        [
            f"Session ID: {report.session_id}",
            f"Venue: {report.venue.value}",
            f"Disposition: {report.disposition.value}",
            f"Findings: {len(report.findings)}",
            f"Policy: {report.quality_policy_version}",
            f"Report: {path}",
        ]
    )


def _paired_report_text(report: PairedQualityReport, path: Path) -> str:
    return "\n".join(
        [
            f"Paired collection ID: {report.paired_collection_id}",
            f"Coinbase disposition: {report.coinbase_report.disposition.value}",
            f"Kraken disposition: {report.kraken_report.disposition.value}",
            f"Paired disposition: {report.disposition.value}",
            (f"Overlap duration seconds: {report.overlap.market_event_overlap_duration_seconds}"),
            f"Policy: {report.quality_policy_version}",
            f"Report: {path}",
        ]
    )
