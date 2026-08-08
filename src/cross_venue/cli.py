"""Command-line interface for project inspection and phase-safe utilities."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
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
    load_normalization_config,
    load_storage_config,
)
from cross_venue.normalization.catalog import build_normalized_catalog
from cross_venue.normalization.determinism import verify_normalization_determinism
from cross_venue.normalization.exceptions import NormalizationError
from cross_venue.normalization.normalizer import normalize_dataset
from cross_venue.normalization.validation import validate_normalized_dataset
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

DEFAULT_PHASE_3B_CAMPAIGN_ID = "btc-usd-coinbase-kraken-2026-07-31-v1"
DEFAULT_CAMPAIGN_CONFIG_PATH = Path("configs/campaigns/phase_3b_btc_usd.toml")


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
    normalize = subparsers.add_parser(
        "normalize-dataset",
        help="replay an accepted validated manifest into deterministic normalized Parquet",
    )
    normalize.add_argument("--validated-manifest", type=Path, required=True)
    normalize.add_argument(
        "--normalization-config",
        type=Path,
        default=Path("configs/normalization.toml"),
    )
    normalize.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    normalize.add_argument("--quality-policy", type=Path, default=Path("configs/data_quality.toml"))
    normalize.add_argument("--output-root", type=Path)
    normalize.add_argument("--expected-commit")
    normalize.add_argument("--dry-run", action="store_true")
    validate_normalized = subparsers.add_parser(
        "validate-normalized-dataset",
        help="validate a Phase 3 normalized dataset",
    )
    validate_normalized.add_argument("--normalization-manifest", type=Path, required=True)
    validate_normalized.add_argument("--snapshot-root", type=Path, required=True)

    dataset_validation_status = subparsers.add_parser(
        "normalized-dataset-validation-status",
        help="print normalized dataset validation status",
    )
    dataset_validation_status.add_argument("--normalization-manifest", type=Path, required=True)

    preliminary_readiness = subparsers.add_parser(
        "analyze-preliminary-readiness",
        help="analyze preliminary research readiness",
    )
    preliminary_readiness.add_argument("--dataset-root", type=Path, required=True)
    preliminary_readiness.add_argument("--validation-report", type=Path, required=True)
    preliminary_price_discovery = subparsers.add_parser(
        "analyze-preliminary-price-discovery",
        help="run Phase 4B preliminary price discovery analysis",
    )
    preliminary_price_discovery.add_argument("--dataset-root", type=Path, required=True)
    preliminary_price_discovery.add_argument("--validation-report", type=Path, required=True)
    preliminary_price_discovery.add_argument("--derived-root", type=Path, required=True)
    catalog = subparsers.add_parser(
        "build-normalized-catalog",
        help="build DuckDB views over a normalized dataset",
    )
    catalog.add_argument("--normalization-manifest", type=Path, required=True)
    deterministic = subparsers.add_parser(
        "verify-normalization-determinism",
        help="normalize twice into temporary roots and compare deterministic outputs",
    )
    deterministic.add_argument("--validated-manifest", type=Path, required=True)
    deterministic.add_argument(
        "--normalization-config",
        type=Path,
        default=Path("configs/normalization.toml"),
    )
    deterministic.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    deterministic.add_argument(
        "--quality-policy",
        type=Path,
        default=Path("configs/data_quality.toml"),
    )
    init_campaign = subparsers.add_parser(
        "init-collection-campaign",
        help="initialize a collection campaign from a validated TOML configuration",
    )
    init_campaign.add_argument(
        "--campaign-config",
        type=Path,
        default=DEFAULT_CAMPAIGN_CONFIG_PATH,
    )
    campaign_status = subparsers.add_parser(
        "campaign-status",
        help="print and persist current campaign status",
    )
    campaign_status.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    campaign_status.add_argument(
        "--campaign-config",
        type=Path,
        default=None,
    )
    run_slot = subparsers.add_parser(
        "run-campaign-slot",
        help="run one scheduled slot for the selected campaign",
    )
    run_slot.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    run_slot.add_argument("--slot-id", required=True)
    run_slot.add_argument(
        "--campaign-config",
        type=Path,
        default=None,
    )
    run_slot.add_argument("--storage-config", type=Path, default=Path("configs/storage.toml"))
    run_slot.add_argument("--quality-policy", type=Path, default=Path("configs/data_quality.toml"))
    missed = subparsers.add_parser(
        "mark-campaign-slot-missed",
        help="mark a campaign slot missed with an enumerated reason",
    )
    missed.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    missed.add_argument("--slot-id", required=True)
    missed.add_argument(
        "--reason",
        choices=(
            "IMPLEMENTATION_NOT_READY",
            "USER_UNAVAILABLE",
            "SYSTEM_UNAVAILABLE",
            "NETWORK_UNAVAILABLE",
            "SLOT_WINDOW_EXPIRED",
            "CAMPAIGN_ALREADY_COMPLETE",
            "CAMPAIGN_INITIALIZED_AFTER_SLOT_WINDOW",
        ),
    )
    missed.add_argument(
        "--campaign-config",
        type=Path,
        default=None,
    )
    validate_campaign_parser = subparsers.add_parser(
        "validate-collection-campaign",
        help="validate campaign registry, ledger, and accepted-attempt rules",
    )
    validate_campaign_parser.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    validate_campaign_parser.add_argument(
        "--campaign-config",
        type=Path,
        default=None,
    )
    finalize = subparsers.add_parser(
        "finalize-campaign-manifest",
        help="create the validated campaign manifest after completion",
    )
    finalize.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    finalize.add_argument(
        "--campaign-config",
        type=Path,
        default=None,
    )
    composite = subparsers.add_parser(
        "build-composite-exploratory-dataset",
        help="build a lineage-only exploratory manifest from separate campaigns",
    )
    composite.add_argument(
        "--campaign-id",
        action="append",
        required=True,
        help="source campaign ID; repeat once per source campaign",
    )
    composite.add_argument("--output-path", type=Path, required=True)
    composite.add_argument("--minimum-accepted-sessions", type=int, default=10)
    composite.add_argument("--minimum-overlap-seconds", type=float, default=18_000)
    migrate = subparsers.add_parser(
        "migrate-campaign-runtime",
        help="append a controlled pre-collection campaign runtime migration",
    )
    migrate.add_argument("--campaign-id", default=DEFAULT_PHASE_3B_CAMPAIGN_ID)
    migrate.add_argument("--campaign-config", type=Path, default=None)
    migrate.add_argument("--to-current-commit", action="store_true")
    migrate.add_argument(
        "--reason",
        choices=(
            "GENERIC_ENGINE_BEFORE_FIRST_COLLECTION",
            "LONG_DURATION_PREFLIGHT_FIX",
            "CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX",
            "COLLECTOR_INTERNAL_MESSAGE_LIMIT_FIX",
        ),
        required=True,
    )
    build_snapshot = subparsers.add_parser(
        "build-analysis-source-snapshot",
        help="build an immutable source catalog and analysis snapshot from read-only campaign data",
    )
    build_snapshot.add_argument("--source-collection-root", type=Path, required=True)
    build_snapshot.add_argument(
        "--analysis-output-root",
        type=Path,
        default=Path("data/analysis"),
    )
    build_snapshot.add_argument(
        "--campaign-id",
        action="append",
        dest="campaign_ids",
        required=True,
        help="source campaign ID; repeat to include multiple campaigns",
    )
    build_snapshot.add_argument("--snapshot-label")
    validate_snapshot = subparsers.add_parser(
        "validate-analysis-source-snapshot",
        help="validate an existing immutable analysis source snapshot",
    )
    validate_snapshot.add_argument("--snapshot-root", type=Path, required=True)
    validate_snapshot.add_argument(
        "--source-collection-root",
        type=Path,
        help="verify the reconstructed catalog against the local source tree",
    )

    snapshot_status = subparsers.add_parser(
        "analysis-snapshot-status",
        help="print a compact analysis source snapshot status",
    )
    snapshot_status.add_argument("--snapshot-root", type=Path, required=True)
    normalize_snapshot = subparsers.add_parser(
        "normalize-analysis-snapshot",
        help="normalize an immutable analysis source snapshot into research Parquet outputs",
    )
    normalize_snapshot.add_argument("--source-collection-root", type=Path, required=True)
    normalize_snapshot.add_argument("--snapshot-root", type=Path, required=True)
    normalize_snapshot.add_argument(
        "--analysis-output-root",
        type=Path,
        default=Path("data/analysis"),
    )
    normalize_snapshot.add_argument(
        "--normalization-config",
        type=Path,
        default=Path("configs/normalization.toml"),
    )
    normalize_snapshot.add_argument("--expected-commit")
    normalize_snapshot.add_argument("--dry-run", action="store_true")
    normalize_snapshot.add_argument(
        "--attempt-id",
        help="debug a single accepted attempt; rejected if outside snapshot membership",
    )
    normalized_status = subparsers.add_parser(
        "analysis-normalization-status",
        help="print a compact normalized analysis-snapshot status",
    )
    normalized_status.add_argument("--normalization-manifest", type=Path, required=True)

    p = subparsers.add_parser(
        "analyze-econometric-price-discovery", help="Run Phase 4C econometric price discovery"
    )
    p.add_argument("--dataset-root", type=Path, required=True)
    p.add_argument("--validation-report", type=Path, required=True)
    p.add_argument("--preliminary-result-root", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--derived-root", type=Path, required=True)
    p.add_argument(
        "--analysis-mode",
        type=str,
        required=True,
        choices=["development", "final", "DEVELOPMENT", "FINAL"],
    )

    p.set_defaults(func=analyze_econometric_price_discovery_cmd)

    render_parser = subparsers.add_parser(
        "render-econometric-results", help="Render Phase 4D econometric results report"
    )
    render_parser.add_argument("--econometric-output-root", type=Path, required=True)
    render_parser.add_argument("--output-root", type=Path, required=True)
    render_parser.set_defaults(func=render_econometric_results_cmd)

    return parser


def render_econometric_results_cmd(args: argparse.Namespace) -> int:
    from cross_venue.research.econometric_reporting import render_econometric_results
    from cross_venue.research.exceptions import ResearchError

    try:
        render_econometric_results(args.econometric_output_root, args.output_root)
        manifest = json.loads((args.output_root / "reporting_manifest.json").read_text())
        print(
            json_dumps(
                {
                    "reporting_id": manifest["reporting_id"],
                    "analysis_mode": manifest["analysis_mode"],
                    "tables": len(manifest["generated_tables"]),
                    "figures": len(manifest["generated_figures"]),
                }
            )
        )
        return 0
    except (ResearchError, OSError, ValueError) as exc:
        print(f"Phase 4D reporting failed: {exc}")
        return 1


def analyze_econometric_price_discovery_cmd(args: argparse.Namespace) -> int:

    from cross_venue.research.econometric_analysis import (
        AnalysisMode,
        analyze_econometric_price_discovery,
    )

    try:
        mode = AnalysisMode(args.analysis_mode.upper())
    except ValueError:
        print(f"Invalid analysis mode: {args.analysis_mode}", file=sys.stderr)
        return 1

    try:
        res = analyze_econometric_price_discovery(
            dataset_root=args.dataset_root,
            validation_report_path=args.validation_report,
            preliminary_result_root=args.preliminary_result_root,
            config_path=args.config,
            derived_root=args.derived_root,
            analysis_mode=mode,
        )
        print(res.model_dump_json(indent=2))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


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
            if args.duration_seconds > 120.0:
                raise ValueError("duration exceeds Phase 2B maximum")
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
            if args.duration_seconds > 30.0:
                raise ValueError("duration exceeds Phase 2B maximum")
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
    if args.command == "normalize-dataset":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        normalization_config = load_normalization_config(args.normalization_config)
        try:
            result = normalize_dataset(
                args.validated_manifest,
                storage_config=storage_config,
                quality_config=quality_config,
                normalization_config=normalization_config,
                dry_run=args.dry_run,
                output_root=args.output_root,
                expected_commit=args.expected_commit,
            )
        except NormalizationError as exc:
            print(f"Normalization failed: {exc}")
            return 1
        if isinstance(result, dict):
            print(json_dumps(result))
        else:
            print(result.to_text())
        return 0
    if args.command == "validate-normalized-dataset":
        try:
            normalized_validation_report = validate_normalized_dataset(
                args.normalization_manifest,
                snapshot_root=args.snapshot_root,
            )
        except NormalizationError as exc:
            print(f"Normalized dataset invalid: {exc}")
            return 1
        print(normalized_validation_report.model_dump_json(indent=2))
        return 0
    if args.command == "normalized-dataset-validation-status":
        import sys

        dataset_root = args.normalization_manifest.parent.parent
        report_path = dataset_root / "validation" / "normalized_dataset_validation.json"
        if not report_path.exists():
            print("Validation report not found.", file=sys.stderr)
            return 1
        print(report_path.read_text(encoding="utf-8"))
        return 0
    if args.command == "analyze-preliminary-readiness":
        from cross_venue.research.exceptions import ResearchError
        from cross_venue.research.preliminary_diagnostics import analyze_preliminary_readiness

        try:
            readiness_report = analyze_preliminary_readiness(
                dataset_root=args.dataset_root,
                validation_report_path=args.validation_report,
            )
        except ResearchError as exc:
            print(f"Preliminary readiness failed: {exc}")
            return 1
        print(readiness_report.model_dump_json(indent=2))
        return 0
    if args.command == "analyze-preliminary-price-discovery":
        from cross_venue.research.exceptions import ResearchError
        from cross_venue.research.preliminary_analysis import analyze_preliminary_price_discovery

        try:
            analysis_report = analyze_preliminary_price_discovery(
                dataset_root=args.dataset_root,
                validation_report_path=args.validation_report,
                derived_root=args.derived_root,
            )
        except ResearchError as exc:
            print(f"Preliminary analysis failed: {exc}")
            return 1
        print(analysis_report.model_dump_json(indent=2))
        return 0
    if args.command == "build-normalized-catalog":
        try:
            catalog_report = build_normalized_catalog(args.normalization_manifest)
        except NormalizationError as exc:
            print(f"Catalog build failed: {exc}")
            return 1
        print(json_dumps(catalog_report))
        return 0
    if args.command == "verify-normalization-determinism":
        storage_config = load_storage_config(args.storage_config)
        quality_config = load_data_quality_config(args.quality_policy)
        normalization_config = load_normalization_config(args.normalization_config)
        try:
            determinism_report = verify_normalization_determinism(
                args.validated_manifest,
                storage_config=storage_config,
                quality_config=quality_config,
                normalization_config=normalization_config,
            )
        except NormalizationError as exc:
            print(f"Determinism verification failed: {exc}")
            return 1
        print(json_dumps(determinism_report))
        return 0
    if args.command == "init-collection-campaign":
        from cross_venue.campaigns.config import load_campaign_config
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.registry import initialize_campaign
        from cross_venue.campaigns.reporting import registry_summary_text

        try:
            campaign_config = load_campaign_config(args.campaign_config)
            registry = initialize_campaign(campaign_config, config_path=args.campaign_config)
        except CampaignError as exc:
            print(f"Campaign initialization failed: {exc}")
            return 1
        print(registry_summary_text(registry))
        return 0
    if args.command == "campaign-status":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.registry import (
            campaign_status_payload,
            validate_registry_and_ledger,
            write_status_reports,
        )

        try:
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            registry = validate_registry_and_ledger(campaign_config)
            write_status_reports(campaign_config, registry)
            print(json_dumps(campaign_status_payload(campaign_config, registry)))
        except CampaignError as exc:
            print(f"Campaign status failed: {exc}")
            return 1
        return 0
    if args.command == "run-campaign-slot":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.runner import run_campaign_slot

        try:
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            attempt = asyncio.run(
                run_campaign_slot(
                    campaign_config,
                    slot_id=args.slot_id,
                    storage_config=load_storage_config(args.storage_config),
                    quality_config=load_data_quality_config(args.quality_policy),
                )
            )
        except CampaignError as exc:
            print(f"Campaign slot failed: {exc}")
            return 1
        print(json_dumps(attempt.model_dump(mode="json")))
        return 0
    if args.command == "mark-campaign-slot-missed":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.models import MissedReason
        from cross_venue.campaigns.registry import mark_slot_missed
        from cross_venue.campaigns.reporting import registry_summary_text

        try:
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            registry = mark_slot_missed(
                campaign_config,
                slot_id=args.slot_id,
                reason=MissedReason(args.reason),
            )
        except CampaignError as exc:
            print(f"Mark missed failed: {exc}")
            return 1
        print(registry_summary_text(registry))
        return 0
    if args.command == "validate-collection-campaign":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.validation import validate_campaign

        try:
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            campaign_validation_report = validate_campaign(campaign_config)
        except CampaignError as exc:
            print(f"Campaign validation failed: {exc}")
            return 1
        print(json_dumps(campaign_validation_report))
        return 0
    if args.command == "finalize-campaign-manifest":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.manifest import finalize_campaign_manifest

        try:
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            manifest, path = finalize_campaign_manifest(campaign_config)
        except CampaignError as exc:
            print(f"Campaign finalization failed: {exc}")
            return 1
        print(json_dumps({"manifest": manifest.model_dump(mode="json"), "path": str(path)}))
        return 0
    if args.command == "build-composite-exploratory-dataset":
        from cross_venue.campaigns.composite import build_composite_exploratory_dataset
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError

        try:
            campaign_configs = tuple(
                load_campaign_config_for_id(campaign_id) for campaign_id in args.campaign_id
            )
            composite_manifest, path = build_composite_exploratory_dataset(
                campaign_configs,
                output_path=args.output_path,
                accepted_session_count_requirement=args.minimum_accepted_sessions,
                accepted_overlap_seconds_requirement=args.minimum_overlap_seconds,
            )
        except CampaignError as exc:
            print(f"Composite exploratory dataset failed: {exc}")
            return 1
        print(
            json_dumps({"manifest": composite_manifest.model_dump(mode="json"), "path": str(path)})
        )
        return 0
    if args.command == "migrate-campaign-runtime":
        from cross_venue.campaigns.config import load_campaign_config_for_id
        from cross_venue.campaigns.exceptions import CampaignError
        from cross_venue.campaigns.migration import migrate_campaign_runtime
        from cross_venue.campaigns.models import RuntimeMigrationReason

        try:
            if not args.to_current_commit:
                raise CampaignError("--to-current-commit is required for runtime migration")
            campaign_config = load_campaign_config_for_id(
                args.campaign_id,
                config_path=args.campaign_config,
            )
            migration_report = migrate_campaign_runtime(
                campaign_config,
                reason=RuntimeMigrationReason(args.reason),
            )
        except CampaignError as exc:
            print(f"Campaign runtime migration failed: {exc}")
            return 1
        print(json_dumps(migration_report))
        return 0
    if args.command == "build-analysis-source-snapshot":
        from cross_venue.research.exceptions import ResearchSnapshotError
        from cross_venue.research.source_snapshot import build_analysis_source_snapshot

        try:
            snapshot_build_result = build_analysis_source_snapshot(
                source_collection_root=args.source_collection_root,
                analysis_output_root=args.analysis_output_root,
                campaign_ids=tuple(args.campaign_ids),
                snapshot_label=args.snapshot_label,
            )
        except ResearchSnapshotError as exc:
            print(f"Analysis source snapshot failed: {exc}")
            return 1
        print(snapshot_build_result.to_text())
        return 0
    if args.command == "validate-analysis-source-snapshot":
        from cross_venue.research.exceptions import ResearchSnapshotError
        from cross_venue.research.source_snapshot import validate_analysis_source_snapshot

        try:
            validation = validate_analysis_source_snapshot(
                snapshot_root=args.snapshot_root,
                source_collection_root=args.source_collection_root,
            )
        except ResearchSnapshotError as exc:
            print(f"Analysis source snapshot validation failed: {exc}")
            return 1
        print(json_dumps(validation.model_dump(mode="json")))
        return 0 if validation.validation_status == "VALID" else 1
    if args.command == "analysis-snapshot-status":
        from cross_venue.research.exceptions import ResearchSnapshotError
        from cross_venue.research.source_snapshot import snapshot_status

        try:
            status = snapshot_status(args.snapshot_root)
        except ResearchSnapshotError as exc:
            print(f"Analysis snapshot status failed: {exc}")
            return 1
        print(json_dumps(status))
        return 0
    if args.command == "normalize-analysis-snapshot":
        from cross_venue.research.exceptions import ResearchSnapshotError
        from cross_venue.research.source_snapshot import (
            AnalysisSourceCatalog,
            validate_analysis_source_snapshot,
        )

        try:
            source_root = args.source_collection_root.expanduser().resolve()
            validation = validate_analysis_source_snapshot(
                snapshot_root=args.snapshot_root,
            )
            if validation.validation_status != "VALID":
                print(json_dumps(validation.model_dump(mode="json")))
                return 1
            snapshot_manifest = args.snapshot_root / "snapshot_manifest.json"
            if args.attempt_id:
                catalog = AnalysisSourceCatalog.model_validate_json(
                    (args.snapshot_root / "source_catalog.json").read_text(encoding="utf-8")
                )
                if args.attempt_id not in {
                    attempt.campaign_attempt_id for attempt in catalog.accepted_attempts
                }:
                    print("Normalization failed: attempt is outside analysis snapshot membership")
                    return 1
            storage_config = _source_storage_config(source_root)
            quality_config = _source_quality_config(source_root)
            normalization_config = load_normalization_config(args.normalization_config).model_copy(
                update={"output_root": args.analysis_output_root / "normalized"}
            )
            result = normalize_dataset(
                snapshot_manifest,
                storage_config=storage_config,
                quality_config=quality_config,
                normalization_config=normalization_config,
                dry_run=args.dry_run,
                expected_commit=args.expected_commit,
            )
        except (ResearchSnapshotError, NormalizationError, OSError) as exc:
            print(f"Analysis snapshot normalization failed: {exc}")
            return 1
        if isinstance(result, dict):
            print(json_dumps(result))
        else:
            print(result.to_text())
        return 0
    if args.command == "analysis-normalization-status":
        try:
            manifest = json.loads(args.normalization_manifest.read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"Analysis normalization status failed: {exc}")
            return 1

        status = {
            "normalized_dataset_id": manifest.get("normalized_dataset_id"),
            "normalization_manifest_id": manifest.get("normalization_manifest_id"),
            "source_analysis_snapshot_id": manifest.get("source_analysis_snapshot_id"),
            "source_catalog_id": manifest.get("source_catalog_id"),
            "accepted_attempt_count": manifest.get("accepted_attempt_count"),
            "venue_session_count": manifest.get("venue_session_count"),
            "trade_row_count": manifest.get("trade_row_count"),
            "top_of_book_row_count": manifest.get("top_of_book_row_count"),
            "raw_record_outcome_row_count": manifest.get("raw_record_outcome_row_count"),
            "validation_status": manifest.get("validation_status"),
            "final_composite_status": manifest.get("final_composite_status"),
        }
        print(json_dumps(status))
        return 0

    if args.command == "render-econometric-results":
        ret = args.func(args)
        return int(ret) if ret is not None else 0

    if args.command == "analyze-econometric-price-discovery":
        ret = args.func(args)
        return int(ret) if ret is not None else 0

    return 1


def _source_storage_config(source_root: Path) -> StorageConfig:
    storage_config = load_storage_config(source_root / "configs" / "storage.toml")
    return storage_config.model_copy(update={"archive_root": source_root / "data" / "raw"})


def _source_quality_config(source_root: Path) -> DataQualityConfig:
    quality_config = load_data_quality_config(source_root / "configs" / "data_quality.toml")
    return quality_config.model_copy(
        update={
            "report_root": source_root / "data" / "quality",
            "validated_manifest_root": source_root / "data" / "validated" / "manifests",
        }
    )


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


def json_dumps(payload: object) -> str:
    """Return deterministic pretty JSON for CLI diagnostics."""

    return json.dumps(payload, indent=2, sort_keys=True, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
