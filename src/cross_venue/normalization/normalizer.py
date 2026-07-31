"""Deterministic replay from validated manifests into normalized Parquet tables."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

from cross_venue.campaigns.models import ValidatedCampaignManifest
from cross_venue.collectors.base import ParseResult
from cross_venue.collectors.coinbase.parser import parse_coinbase_message
from cross_venue.collectors.kraken.parser import parse_kraken_message
from cross_venue.config import DataQualityConfig, NormalizationConfig, StorageConfig
from cross_venue.normalization.decimal_utils import validate_decimal
from cross_venue.normalization.exceptions import NormalizationError, ValidatedManifestError
from cross_venue.normalization.identifiers import (
    combine_hashes,
    semantic_table_hash,
    stable_event_id,
    stable_source_event_id,
)
from cross_venue.normalization.parquet_writer import write_parquet
from cross_venue.normalization.schemas import (
    OUTCOME_COLUMNS,
    TOP_OF_BOOK_COLUMNS,
    TRADE_COLUMNS,
    outcome_schema,
    top_of_book_schema,
    trade_schema,
)
from cross_venue.quality.io import current_git_commit, model_sha256, sha256_text, utc_now
from cross_venue.quality.models import (
    PairedQualityReport,
    QualityDisposition,
    SessionQualityReport,
    ValidatedDatasetManifest,
)
from cross_venue.schemas import Exchange, MarketEventType, NormalizedTopOfBook, NormalizedTrade
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json, load_manifest
from cross_venue.storage.paths import resolve_under_root, safe_path_component


@dataclass(frozen=True, slots=True)
class NormalizeDatasetResult:
    """Result paths and manifest from a deterministic normalization run."""

    dataset_root: Path
    normalization_manifest_path: Path
    manifest: dict[str, Any]

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Normalized dataset: {self.dataset_root}",
                f"Normalization manifest: {self.normalization_manifest_path}",
                f"Trade rows: {self.manifest['trade_row_count']}",
                f"Top-of-book rows: {self.manifest['top_of_book_row_count']}",
                f"Raw outcome rows: {self.manifest['raw_record_outcome_row_count']}",
                f"Semantic dataset hash: {self.manifest['semantic_dataset_hash']}",
                f"Reconciliation: {self.manifest['reconciliation_status']}",
                f"Validation: {self.manifest['validation_status']}",
            ]
        )


@dataclass(frozen=True, slots=True)
class _InputContext:
    manifest_path: Path
    manifest_sha256: str
    validated_manifest: ValidatedDatasetManifest
    paired_report: PairedQualityReport
    paired_report_path: Path
    session_roots: dict[str, Path]
    session_manifests: dict[str, Any]
    session_quality_paths: dict[str, Path]
    source_snapshot: dict[str, Any]
    campaign_lineage_by_session: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _NormalizationInputBundle:
    contexts: tuple[_InputContext, ...]
    dataset_identity: str
    campaign_manifest: ValidatedCampaignManifest | None
    campaign_manifest_path: Path | None
    campaign_manifest_sha256: str | None

    @property
    def primary_context(self) -> _InputContext:
        return self.contexts[0]


def normalize_dataset(
    validated_manifest_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    normalization_config: NormalizationConfig,
    dry_run: bool = False,
    output_root: Path | None = None,
    expected_commit: str | None = None,
    require_clean: bool | None = None,
) -> NormalizeDatasetResult | dict[str, Any]:
    """Normalize an accepted validated dataset manifest into deterministic Parquet outputs."""

    if not normalization_config.require_validated_manifest:
        raise ValidatedManifestError("Phase 3A requires a validated manifest")
    clean_required = (
        normalization_config.require_clean_working_tree_for_final_run
        if require_clean is None
        else require_clean
    )
    if clean_required and not dry_run and not _working_tree_clean():
        raise NormalizationError("final normalization requires a clean working tree")
    commit = current_git_commit()
    if expected_commit is not None and expected_commit != commit:
        raise NormalizationError(f"expected commit {expected_commit}, found {commit}")
    bundle = load_normalization_inputs(
        validated_manifest_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
    )
    config_sha = sha256_file(Path("configs/normalization.toml"))
    dataset_id = normalized_dataset_id(
        bundle,
        normalization_schema_version=normalization_config.normalization_schema_version,
        normalization_config_sha256=config_sha,
        normalizer_git_commit=commit,
    )
    root = (output_root or normalization_config.output_root) / f"dataset={dataset_id}"
    if dry_run:
        return _dry_run_plan(bundle, root, dataset_id)
    if root.exists():
        raise NormalizationError(f"normalized output already exists: {root}")
    partial_root = root.with_name(f"{root.name}.partial")
    if partial_root.exists():
        raise NormalizationError(f"partial normalized output already exists: {partial_root}")
    trade_rows: list[dict[str, Any]] = []
    bbo_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    try:
        partial_root.mkdir(parents=True)
        for context in bundle.contexts:
            duplicate_index = _raw_duplicate_index(context)
            for session_id, session_manifest in context.session_manifests.items():
                _replay_session(
                    context,
                    session_id=session_id,
                    session_manifest=session_manifest,
                    duplicate_index=duplicate_index[session_id],
                    normalization_config=normalization_config,
                    trade_rows=trade_rows,
                    bbo_rows=bbo_rows,
                    outcome_rows=outcome_rows,
                )
        files = _write_outputs(
            partial_root,
            trade_rows=trade_rows,
            bbo_rows=bbo_rows,
            outcome_rows=outcome_rows,
            normalization_config=normalization_config,
        )
        semantic_trade_hash = semantic_table_hash(trade_rows, TRADE_COLUMNS)
        semantic_bbo_hash = semantic_table_hash(bbo_rows, TOP_OF_BOOK_COLUMNS)
        semantic_outcome_hash = semantic_table_hash(outcome_rows, OUTCOME_COLUMNS)
        semantic_dataset_hash = combine_hashes(
            [semantic_trade_hash, semantic_bbo_hash, semantic_outcome_hash]
        )
        reconciliation = _reconcile(trade_rows, bbo_rows, outcome_rows)
        for context in bundle.contexts:
            _verify_source_snapshot(context)
        manifest = _normalization_manifest(
            bundle,
            dataset_id=dataset_id,
            dataset_root=partial_root,
            normalizer_git_commit=commit,
            normalization_config_sha256=config_sha,
            files=files,
            trade_rows=trade_rows,
            bbo_rows=bbo_rows,
            outcome_rows=outcome_rows,
            semantic_trade_hash=semantic_trade_hash,
            semantic_bbo_hash=semantic_bbo_hash,
            semantic_outcome_hash=semantic_outcome_hash,
            semantic_dataset_hash=semantic_dataset_hash,
            reconciliation_status=reconciliation,
        )
        manifest_path = partial_root / "manifest" / "normalization_manifest.json"
        atomic_write_json(manifest_path, manifest)
        partial_root.replace(root)
    except Exception:
        if partial_root.exists():
            shutil.rmtree(partial_root)
        raise
    final_manifest_path = root / "manifest" / "normalization_manifest.json"
    final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
    return NormalizeDatasetResult(
        dataset_root=root,
        normalization_manifest_path=final_manifest_path,
        manifest=final_manifest,
    )


def load_normalization_inputs(
    validated_manifest_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    normalization_config: NormalizationConfig,
) -> _NormalizationInputBundle:
    """Load a single-pair or campaign validated manifest bundle."""

    manifest_path = resolve_under_root(
        quality_config.validated_manifest_root, validated_manifest_path
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "validated_campaign_manifest_version" not in payload:
        context = load_normalization_input(
            validated_manifest_path,
            storage_config=storage_config,
            quality_config=quality_config,
            normalization_config=normalization_config,
        )
        return _NormalizationInputBundle(
            contexts=(context,),
            dataset_identity=context.validated_manifest.dataset_manifest_id,
            campaign_manifest=None,
            campaign_manifest_path=None,
            campaign_manifest_sha256=None,
        )
    campaign = ValidatedCampaignManifest.model_validate(payload)
    campaign_sha = sha256_file(manifest_path)
    expected_content = model_sha256(campaign.model_copy(update={"content_hash": None}))
    if campaign.content_hash != expected_content:
        raise ValidatedManifestError("validated campaign manifest content hash mismatch")
    if campaign.quality_policy_version != normalization_config.require_quality_policy_version:
        raise ValidatedManifestError("campaign manifest policy version does not match config")
    if campaign.instrument != "BTC-USD":
        raise ValidatedManifestError("campaign manifest must contain BTC-USD only")
    if set(campaign.venues) != {Exchange.COINBASE, Exchange.KRAKEN}:
        raise ValidatedManifestError("campaign manifest must contain Coinbase and Kraken")
    contexts: list[_InputContext] = []
    seen_sessions: set[str] = set()
    seen_pairs: set[str] = set()
    for entry in sorted(
        campaign.accepted_pair_manifests,
        key=lambda item: (item.planned_start_utc, item.slot_id),
    ):
        if entry.paired_collection_id in seen_pairs:
            raise ValidatedManifestError("campaign manifest contains duplicate paired collection")
        seen_pairs.add(entry.paired_collection_id)
        pair_path = (
            quality_config.validated_manifest_root / entry.validated_pair_manifest_relative_path
        )
        if sha256_file(pair_path) != entry.validated_pair_manifest_sha256:
            raise ValidatedManifestError("accepted pair manifest hash mismatch")
        context = load_normalization_input(
            pair_path,
            storage_config=storage_config,
            quality_config=quality_config,
            normalization_config=normalization_config,
            campaign_lineage={
                "campaign_id": campaign.campaign_id,
                "slot_id": entry.slot_id,
                "campaign_attempt_id": entry.campaign_attempt_id,
                "time_bucket": entry.time_bucket.value,
                "validated_campaign_manifest_id": campaign.validated_campaign_manifest_id,
                "validated_campaign_manifest_sha256": campaign_sha,
            },
        )
        overlap = seen_sessions.intersection(context.validated_manifest.session_ids)
        if overlap:
            raise ValidatedManifestError("campaign manifest contains duplicate session inclusion")
        seen_sessions.update(context.validated_manifest.session_ids)
        contexts.append(context)
    return _NormalizationInputBundle(
        contexts=tuple(contexts),
        dataset_identity=campaign.validated_campaign_manifest_id,
        campaign_manifest=campaign,
        campaign_manifest_path=manifest_path,
        campaign_manifest_sha256=campaign_sha,
    )


def load_normalization_input(
    validated_manifest_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    normalization_config: NormalizationConfig,
    campaign_lineage: dict[str, Any] | None = None,
) -> _InputContext:
    """Load and verify the strict validated-manifest input contract."""

    manifest_path = resolve_under_root(
        quality_config.validated_manifest_root, validated_manifest_path
    )
    manifest_sha = sha256_file(manifest_path)
    validated = ValidatedDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if validated.quality_policy_version != normalization_config.require_quality_policy_version:
        raise ValidatedManifestError("validated manifest policy version does not match config")
    if len(set(validated.session_ids)) != len(validated.session_ids):
        raise ValidatedManifestError("validated manifest contains duplicate sessions")
    if set(validated.venues) != {Exchange.COINBASE, Exchange.KRAKEN}:
        raise ValidatedManifestError("validated manifest must contain Coinbase and Kraken")
    if validated.canonical_instrument != "BTC-USD":
        raise ValidatedManifestError("validated manifest must contain BTC-USD only")
    paired_path = resolve_under_root(
        quality_config.report_root,
        quality_config.report_root / validated.cross_venue_overlap_report_path,
    )
    paired = PairedQualityReport.model_validate_json(paired_path.read_text(encoding="utf-8"))
    if paired.disposition != QualityDisposition.ACCEPTED:
        raise ValidatedManifestError("paired report is not accepted")
    if paired.paired_collection_id != validated.paired_collection_ids[0]:
        raise ValidatedManifestError("paired report ID does not match validated manifest")
    for report in (paired.coinbase_report, paired.kraken_report):
        if report.disposition != QualityDisposition.ACCEPTED:
            raise ValidatedManifestError(f"session {report.session_id} is not accepted")
        if report.session_id not in validated.session_ids:
            raise ValidatedManifestError("paired report references an unexpected session")
    session_roots: dict[str, Path] = {}
    session_manifests: dict[str, Any] = {}
    for relative_path in validated.raw_session_relative_paths:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ValidatedManifestError("raw session paths must be relative")
        root = resolve_under_root(
            storage_config.archive_root, storage_config.archive_root / relative_path
        )
        source_manifest = load_manifest(root / "manifest" / "session_manifest.json")
        expected_hash = validated.raw_manifest_hashes.get(source_manifest.session_id)
        actual_hash = sha256_file(root / "manifest" / "session_manifest.json")
        if expected_hash != actual_hash:
            raise ValidatedManifestError(
                f"source manifest hash mismatch: {source_manifest.session_id}"
            )
        for shard in source_manifest.shards:
            shard_path = root / shard.relative_path
            if not shard_path.exists():
                raise ValidatedManifestError(f"missing raw shard: {shard.relative_path}")
            expected = _expected_shard_checksum(
                paired, source_manifest.session_id, shard.relative_path
            )
            if expected != sha256_file(shard_path):
                raise ValidatedManifestError(f"raw shard checksum mismatch: {shard.relative_path}")
        session_roots[source_manifest.session_id] = root
        session_manifests[source_manifest.session_id] = source_manifest
    quality_paths: dict[str, Path] = {}
    for relative_path in validated.session_quality_report_paths:
        if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
            raise ValidatedManifestError("quality report paths must be relative")
        path = resolve_under_root(
            quality_config.report_root, quality_config.report_root / relative_path
        )
        if not path.exists():
            raise ValidatedManifestError(f"missing session quality report: {relative_path}")
        report = SessionQualityReport.model_validate_json(path.read_text(encoding="utf-8"))
        expected_hash = validated.session_quality_report_hashes.get(report.session_id)
        if expected_hash != model_sha256(report):
            raise ValidatedManifestError(f"quality report hash mismatch: {report.session_id}")
        if report.disposition != QualityDisposition.ACCEPTED:
            raise ValidatedManifestError(f"quality report is not accepted: {report.session_id}")
        if report.session_id not in session_manifests:
            raise ValidatedManifestError("quality report references an unexpected session")
        quality_paths[report.session_id] = path
    if set(quality_paths) != set(session_manifests):
        raise ValidatedManifestError("quality reports do not cover every source session")
    snapshot = {
        "validated_manifest_sha256": manifest_sha,
        "validated_manifest_id": validated.dataset_manifest_id,
        "paired_collection_id": validated.paired_collection_ids[0],
        "policy_version": validated.quality_policy_version,
        "source_session_ids": list(validated.session_ids),
        "source_manifest_hashes": dict(validated.raw_manifest_hashes),
        "raw_shard_checksums_by_session": _session_shard_checksums(paired),
        "quality_report_hashes": dict(validated.session_quality_report_hashes),
        "overlap_start": validated.overlap_start.isoformat(),
        "overlap_end": validated.overlap_end.isoformat(),
    }
    return _InputContext(
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha,
        validated_manifest=validated,
        paired_report=paired,
        paired_report_path=paired_path,
        session_roots=session_roots,
        session_manifests=session_manifests,
        session_quality_paths=quality_paths,
        source_snapshot=snapshot,
        campaign_lineage_by_session={
            session_id: dict(campaign_lineage or {}) for session_id in session_manifests
        },
    )


def normalized_dataset_id(
    bundle: _NormalizationInputBundle,
    *,
    normalization_schema_version: str,
    normalization_config_sha256: str,
    normalizer_git_commit: str,
) -> str:
    identity = bundle.dataset_identity
    if bundle.campaign_manifest is None:
        identity = bundle.primary_context.validated_manifest.paired_collection_ids[0]
    full_hash = stable_event_id(
        [
            bundle.dataset_identity,
            bundle.campaign_manifest_sha256 or bundle.primary_context.manifest_sha256,
            normalization_schema_version,
            normalization_config_sha256,
            normalizer_git_commit,
        ]
    )
    return f"normalized-{safe_path_component(identity)}-{full_hash[:12]}"


def _raw_duplicate_index(context: _InputContext) -> dict[str, dict[int, tuple[str, int, int]]]:
    result: dict[str, dict[int, tuple[str, int, int]]] = {}
    for session_id, source_manifest in context.session_manifests.items():
        counts: Counter[str] = Counter()
        ordered: list[tuple[int, str]] = []
        root = context.session_roots[session_id]
        for shard in source_manifest.shards:
            for record in _iter_raw_records(root / shard.relative_path):
                raw_hash = _raw_frame_hash(record)
                counts[raw_hash] += 1
                ordered.append((record.record_index, raw_hash))
        occurrences: Counter[str] = Counter()
        session_map: dict[int, tuple[str, int, int]] = {}
        for record_index, raw_hash in ordered:
            occurrence = occurrences[raw_hash]
            occurrences[raw_hash] += 1
            session_map[record_index] = (raw_hash, counts[raw_hash], occurrence)
        result[session_id] = session_map
    return result


def _replay_session(
    context: _InputContext,
    *,
    session_id: str,
    session_manifest: Any,
    duplicate_index: dict[int, tuple[str, int, int]],
    normalization_config: NormalizationConfig,
    trade_rows: list[dict[str, Any]],
    bbo_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
) -> None:
    root = context.session_roots[session_id]
    for shard in session_manifest.shards:
        shard_path = root / shard.relative_path
        shard_sha = sha256_file(shard_path)
        for record in _iter_raw_records(shard_path):
            raw_hash, duplicate_count, occurrence_index = duplicate_index[record.record_index]
            lineage = _lineage(
                context,
                session_manifest=session_manifest,
                shard_relative_path=shard.relative_path,
                shard_sha=shard_sha,
                record=record,
                raw_hash=raw_hash,
                duplicate_count=duplicate_count,
                occurrence_index=occurrence_index,
            )
            rows_before = (len(trade_rows), len(bbo_rows))
            outcome, parse_status, error_type, error_message, unsupported_reason = _parse_record(
                record,
                lineage,
                normalization_config,
                trade_rows,
                bbo_rows,
            )
            trade_count = len(trade_rows) - rows_before[0]
            bbo_count = len(bbo_rows) - rows_before[1]
            outcome_rows.append(
                _outcome_row(
                    lineage,
                    record=record,
                    outcome=outcome,
                    parse_status=parse_status,
                    trade_count=trade_count,
                    bbo_count=bbo_count,
                    error_type=error_type,
                    error_message=error_message,
                    unsupported_reason=unsupported_reason,
                )
            )


def _parse_record(
    record: RawArchiveRecord,
    lineage: dict[str, Any],
    normalization_config: NormalizationConfig,
    trade_rows: list[dict[str, Any]],
    bbo_rows: list[dict[str, Any]],
) -> tuple[str, str, str | None, str | None, str | None]:
    try:
        payload = json.loads(record.frame_bytes().decode("utf-8"))
    except UnicodeDecodeError as exc:
        return "JSON_DECODE_ERROR", "ERROR", type(exc).__name__, _bounded(str(exc)), None
    except json.JSONDecodeError as exc:
        return "JSON_DECODE_ERROR", "ERROR", type(exc).__name__, _bounded(str(exc)), None
    if not isinstance(payload, dict):
        return "PARSE_ERROR", "ERROR", "TypeError", "payload is not a JSON object", None
    try:
        result = _parse_payload(record, payload)
    except Exception as exc:
        return "PARSE_ERROR", "ERROR", type(exc).__name__, _bounded(str(exc)), None
    if result.events:
        trade_count = 0
        bbo_count = 0
        for child_index, event in enumerate(result.events):
            if event.event_type == MarketEventType.TRADE and isinstance(event, NormalizedTrade):
                trade_rows.append(_trade_row(lineage, event, child_index, normalization_config))
                trade_count += 1
            elif event.event_type == MarketEventType.TOP_OF_BOOK and isinstance(
                event, NormalizedTopOfBook
            ):
                bbo_rows.append(_bbo_row(lineage, event, child_index, normalization_config))
                bbo_count += 1
            else:
                return (
                    "PARSE_ERROR",
                    "ERROR",
                    "UnexpectedParserOutput",
                    "unsupported event type",
                    None,
                )
        if trade_count > 1:
            return "NORMALIZED_MULTIPLE_TRADES", "OK", None, None, None
        if trade_count == 1:
            return "NORMALIZED_TRADE", "OK", None, None, None
        if bbo_count == 1:
            return "NORMALIZED_TOP_OF_BOOK", "OK", None, None, None
    if result.control is not None:
        summary = result.control.payload_summary.lower()
        if "heartbeat" in summary:
            return "HEARTBEAT", "OK", None, None, None
        if "subscription" in summary:
            return "SUBSCRIPTION_ACKNOWLEDGEMENT", "OK", None, None, None
        if "status" in summary:
            return "STATUS_MESSAGE", "OK", None, None, None
        return "CONTROL_MESSAGE", "OK", None, None, None
    if result.unsupported is not None:
        return "UNSUPPORTED_MESSAGE", "OK", None, None, result.unsupported.reason
    if result.exchange_error is not None:
        return "EXCHANGE_ERROR", "OK", None, None, result.exchange_error.error_message[:200]
    return "NO_NORMALIZED_EVENT", "OK", None, None, None


def _parse_payload(record: RawArchiveRecord, payload: dict[str, Any]) -> ParseResult:
    if record.venue == Exchange.COINBASE:
        return parse_coinbase_message(
            payload,
            local_receipt_ts=record.local_receipt_ts,
            collector_session_id=record.collector_session_id,
        )
    return parse_kraken_message(
        payload,
        local_receipt_ts=record.local_receipt_ts,
        collector_session_id=record.collector_session_id,
    )


def _lineage(
    context: _InputContext,
    *,
    session_manifest: Any,
    shard_relative_path: str,
    shard_sha: str,
    record: RawArchiveRecord,
    raw_hash: str,
    duplicate_count: int,
    occurrence_index: int,
) -> dict[str, Any]:
    return {
        "normalized_schema_version": "3a.1",
        **context.campaign_lineage_by_session.get(session_manifest.session_id, {}),
        "validated_dataset_manifest_id": context.validated_manifest.dataset_manifest_id,
        "validated_dataset_manifest_sha256": context.manifest_sha256,
        "paired_collection_id": context.validated_manifest.paired_collection_ids[0],
        "venue": record.venue.value,
        "canonical_instrument": record.canonical_instrument,
        "venue_symbol": record.venue_symbol,
        "session_id": session_manifest.session_id,
        "connection_epoch": 0,
        "source_shard_relative_path": shard_relative_path,
        "source_shard_sha256": shard_sha,
        "source_raw_record_index": record.record_index,
        "source_raw_frame_sha256": raw_hash,
        "local_receipt_ts": record.local_receipt_ts.astimezone(UTC),
        "is_raw_frame_duplicate": duplicate_count > 1,
        "raw_frame_duplicate_count": duplicate_count,
        "raw_frame_duplicate_occurrence_index": occurrence_index,
    }


def _trade_row(
    lineage: dict[str, Any],
    event: NormalizedTrade,
    child_index: int,
    normalization_config: NormalizationConfig,
) -> dict[str, Any]:
    source_sequence = (
        str(event.raw_sequence_value) if event.raw_sequence_value is not None else None
    )
    event_id = stable_event_id(
        [
            lineage["normalized_schema_version"],
            lineage.get("validated_campaign_manifest_id")
            or lineage["validated_dataset_manifest_id"],
            lineage["venue"],
            lineage["session_id"],
            lineage["source_shard_relative_path"],
            lineage["source_raw_record_index"],
            "trade",
            child_index,
        ]
    )
    source_event_id = stable_source_event_id(
        venue=lineage["venue"],
        session_id=lineage["session_id"],
        source_shard_relative_path=lineage["source_shard_relative_path"],
        source_raw_record_index=lineage["source_raw_record_index"],
        normalized_event_type="trade",
        normalized_child_index=child_index,
    )
    row = {
        **lineage,
        "normalized_event_id": event_id,
        "source_event_id": source_event_id,
        "source_channel": event.source_channel,
        "source_message_type": event.raw_message_type,
        "normalized_child_index": child_index,
        "exchange_ts": event.exchange_ts.astimezone(UTC),
        "trade_id": event.trade_id,
        "price": validate_decimal(
            event.price,
            field_name="price",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "quantity": validate_decimal(
            event.quantity,
            field_name="quantity",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "side": event.aggressor_side.value,
        "side_semantics": "normalized_aggressor_side_from_existing_parser",
        "source_trade_id": event.trade_id,
        "source_sequence": source_sequence,
        "source_checksum": event.raw_checksum_value,
    }
    return {column: row.get(column) for column in TRADE_COLUMNS}


def _bbo_row(
    lineage: dict[str, Any],
    event: NormalizedTopOfBook,
    child_index: int,
    normalization_config: NormalizationConfig,
) -> dict[str, Any]:
    source_sequence = (
        str(event.raw_sequence_value) if event.raw_sequence_value is not None else None
    )
    event_id = stable_event_id(
        [
            lineage["normalized_schema_version"],
            lineage.get("validated_campaign_manifest_id")
            or lineage["validated_dataset_manifest_id"],
            lineage["venue"],
            lineage["session_id"],
            lineage["source_shard_relative_path"],
            lineage["source_raw_record_index"],
            "top_of_book",
            child_index,
        ]
    )
    source_event_id = stable_source_event_id(
        venue=lineage["venue"],
        session_id=lineage["session_id"],
        source_shard_relative_path=lineage["source_shard_relative_path"],
        source_raw_record_index=lineage["source_raw_record_index"],
        normalized_event_type="top_of_book",
        normalized_child_index=child_index,
    )
    row = {
        **lineage,
        "normalized_event_id": event_id,
        "source_event_id": source_event_id,
        "source_channel": event.source_channel,
        "source_message_type": event.raw_message_type,
        "normalized_child_index": child_index,
        "exchange_ts": event.exchange_ts.astimezone(UTC),
        "bid_price": validate_decimal(
            event.best_bid_price,
            field_name="bid_price",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "bid_size": validate_decimal(
            event.best_bid_size,
            field_name="bid_size",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "ask_price": validate_decimal(
            event.best_ask_price,
            field_name="ask_price",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "ask_size": validate_decimal(
            event.best_ask_size,
            field_name="ask_size",
            precision=normalization_config.decimal_precision,
            scale=normalization_config.decimal_scale,
            lineage=event_id,
        ),
        "source_sequence": source_sequence,
        "source_checksum": event.raw_checksum_value,
    }
    return {column: row.get(column) for column in TOP_OF_BOOK_COLUMNS}


def _outcome_row(
    lineage: dict[str, Any],
    *,
    record: RawArchiveRecord,
    outcome: str,
    parse_status: str,
    trade_count: int,
    bbo_count: int,
    error_type: str | None,
    error_message: str | None,
    unsupported_reason: str | None,
) -> dict[str, Any]:
    row = {
        **lineage,
        "frame_type": record.frame_type,
        "source_message_type": record.message_type,
        "source_channel": record.source_channel,
        "normalization_outcome": outcome,
        "normalized_trade_row_count": trade_count,
        "normalized_bbo_row_count": bbo_count,
        "normalized_total_row_count": trade_count + bbo_count,
        "parse_status": parse_status,
        "parse_error_type": error_type,
        "parse_error_message": _bounded(error_message),
        "unsupported_reason": _bounded(unsupported_reason),
    }
    return {column: row.get(column) for column in OUTCOME_COLUMNS}


def _write_outputs(
    root: Path,
    *,
    trade_rows: list[dict[str, Any]],
    bbo_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
    normalization_config: NormalizationConfig,
) -> dict[str, list[dict[str, Any]]]:
    files: dict[str, list[dict[str, Any]]] = {
        "trade_files": [],
        "top_of_book_files": [],
        "raw_record_outcome_files": [],
    }
    files["trade_files"].extend(
        _write_partitioned(root, "trades", trade_rows, TRADE_COLUMNS, normalization_config)
    )
    files["top_of_book_files"].extend(
        _write_partitioned(root, "top_of_book", bbo_rows, TOP_OF_BOOK_COLUMNS, normalization_config)
    )
    files["raw_record_outcome_files"].extend(
        _write_partitioned(
            root,
            "raw_record_outcomes",
            outcome_rows,
            OUTCOME_COLUMNS,
            normalization_config,
        )
    )
    return files


def _write_partitioned(
    root: Path,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    config: NormalizationConfig,
) -> list[dict[str, Any]]:
    schema = {
        "trades": trade_schema(precision=config.decimal_precision, scale=config.decimal_scale),
        "top_of_book": top_of_book_schema(
            precision=config.decimal_precision,
            scale=config.decimal_scale,
        ),
        "raw_record_outcomes": outcome_schema(),
    }[table_name]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["venue"]), str(row["session_id"]))].append(row)
    output_files = []
    for (venue, session_id), group in sorted(grouped.items()):
        ordered = sorted(
            group,
            key=lambda row: (
                int(row["source_raw_record_index"]),
                int(row.get("normalized_child_index") or 0),
            ),
        )
        date = ordered[0]["local_receipt_ts"].date().isoformat()
        path = (
            root
            / table_name
            / f"venue={safe_path_component(venue)}"
            / f"date={date}"
            / f"session={safe_path_component(session_id)}"
            / "part-00000.parquet"
        )
        metadata = write_parquet(path, ordered, schema=schema, config=config)
        output_files.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "table": table_name,
                "venue": venue,
                "session_id": session_id,
                **metadata,
                "minimum_raw_record_index": ordered[0]["source_raw_record_index"],
                "maximum_raw_record_index": ordered[-1]["source_raw_record_index"],
                "minimum_local_receipt_timestamp": ordered[0]["local_receipt_ts"].isoformat(),
                "maximum_local_receipt_timestamp": ordered[-1]["local_receipt_ts"].isoformat(),
            }
        )
    return output_files


def _normalization_manifest(
    bundle: _NormalizationInputBundle,
    *,
    dataset_id: str,
    dataset_root: Path,
    normalizer_git_commit: str,
    normalization_config_sha256: str,
    files: dict[str, list[dict[str, Any]]],
    trade_rows: list[dict[str, Any]],
    bbo_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
    semantic_trade_hash: str,
    semantic_bbo_hash: str,
    semantic_outcome_hash: str,
    semantic_dataset_hash: str,
    reconciliation_status: str,
) -> dict[str, Any]:
    output_file_checksums = {
        entry["relative_path"]: entry["sha256"] for items in files.values() for entry in items
    }
    primary = bundle.primary_context
    contexts = bundle.contexts
    return {
        "normalization_manifest_version": "3a.1",
        "normalized_dataset_id": dataset_id,
        "normalized_schema_version": "3a.1",
        "created_at": utc_now().isoformat(),
        "normalizer_git_commit": normalizer_git_commit,
        "normalizer_working_tree_clean": _working_tree_clean(),
        "normalization_config_sha256": normalization_config_sha256,
        "validated_dataset_manifest_id": primary.validated_manifest.dataset_manifest_id,
        "validated_dataset_manifest_sha256": primary.manifest_sha256,
        "validated_campaign_manifest_id": (
            bundle.campaign_manifest.validated_campaign_manifest_id
            if bundle.campaign_manifest is not None
            else None
        ),
        "validated_campaign_manifest_sha256": bundle.campaign_manifest_sha256,
        "quality_policy_version": primary.validated_manifest.quality_policy_version,
        "quality_policy_sha256": sha256_file(Path("configs/data_quality.toml")),
        "paired_collection_id": primary.validated_manifest.paired_collection_ids[0],
        "paired_collection_ids": [
            pair_id
            for context in contexts
            for pair_id in context.validated_manifest.paired_collection_ids
        ],
        "canonical_instrument": primary.validated_manifest.canonical_instrument,
        "venues": [venue.value for venue in primary.validated_manifest.venues],
        "source_session_ids": [
            session_id
            for context in contexts
            for session_id in context.validated_manifest.session_ids
        ],
        "source_session_manifest_hashes": {
            session_id: manifest_hash
            for context in contexts
            for session_id, manifest_hash in context.validated_manifest.raw_manifest_hashes.items()
        },
        "source_raw_shard_checksums_by_session": {
            session_id: checksums
            for context in contexts
            for session_id, checksums in _session_shard_checksums(context.paired_report).items()
        },
        "source_quality_report_hashes": {
            session_id: report_hash
            for context in contexts
            for session_id, report_hash in (
                context.validated_manifest.session_quality_report_hashes.items()
            )
        },
        "overlap_start": min(
            context.validated_manifest.overlap_start for context in contexts
        ).isoformat(),
        "overlap_end": max(
            context.validated_manifest.overlap_end for context in contexts
        ).isoformat(),
        **files,
        "trade_row_count": len(trade_rows),
        "top_of_book_row_count": len(bbo_rows),
        "raw_record_outcome_row_count": len(outcome_rows),
        "source_raw_record_count": sum(
            manifest.records_written
            for context in contexts
            for manifest in context.session_manifests.values()
        ),
        "source_supported_trade_event_count": len(trade_rows),
        "source_supported_bbo_event_count": len(bbo_rows),
        "source_control_record_count": sum(
            row["normalization_outcome"]
            in {"CONTROL_MESSAGE", "HEARTBEAT", "STATUS_MESSAGE", "SUBSCRIPTION_ACKNOWLEDGEMENT"}
            for row in outcome_rows
        ),
        "source_unsupported_record_count": sum(
            row["normalization_outcome"] == "UNSUPPORTED_MESSAGE" for row in outcome_rows
        ),
        "source_parse_error_count": sum(row["parse_status"] == "ERROR" for row in outcome_rows),
        "semantic_trade_hash": semantic_trade_hash,
        "semantic_top_of_book_hash": semantic_bbo_hash,
        "semantic_outcome_hash": semantic_outcome_hash,
        "semantic_dataset_hash": semantic_dataset_hash,
        "output_file_checksums": output_file_checksums,
        "reconciliation_status": reconciliation_status,
        "validation_status": "VALID",
        "known_limitations": [
            "No deduplication, clock correction, feature engineering, or lead-lag analysis.",
            "Physical Parquet byte equality is supported within the validated local environment.",
        ],
    }


def _dry_run_plan(
    bundle: _NormalizationInputBundle,
    root: Path,
    dataset_id: str,
) -> dict[str, Any]:
    source_records = sum(
        manifest.records_written
        for context in bundle.contexts
        for manifest in context.session_manifests.values()
    )
    return {
        "dry_run": True,
        "normalized_dataset_id": dataset_id,
        "planned_output_root": str(root),
        "validated_dataset_manifest_id": (
            bundle.primary_context.validated_manifest.dataset_manifest_id
        ),
        "validated_campaign_manifest_id": (
            bundle.campaign_manifest.validated_campaign_manifest_id
            if bundle.campaign_manifest is not None
            else None
        ),
        "source_raw_record_count": source_records,
        "source_session_ids": [
            session_id
            for context in bundle.contexts
            for session_id in context.validated_manifest.session_ids
        ],
    }


def _reconcile(
    trade_rows: list[dict[str, Any]],
    bbo_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
) -> str:
    if sum(int(row["normalized_trade_row_count"]) for row in outcome_rows) != len(trade_rows):
        raise NormalizationError("trade row reconciliation failed")
    if sum(int(row["normalized_bbo_row_count"]) for row in outcome_rows) != len(bbo_rows):
        raise NormalizationError("top-of-book row reconciliation failed")
    event_ids = [row["normalized_event_id"] for row in trade_rows + bbo_rows]
    if len(event_ids) != len(set(event_ids)):
        raise NormalizationError("normalized event IDs are not unique")
    return "PASSED"


def _verify_source_snapshot(context: _InputContext) -> None:
    if sha256_file(context.manifest_path) != context.manifest_sha256:
        raise NormalizationError("validated manifest changed during replay")
    for session_id, session_manifest in context.session_manifests.items():
        root = context.session_roots[session_id]
        manifest_hash = sha256_file(root / "manifest" / "session_manifest.json")
        if manifest_hash != context.validated_manifest.raw_manifest_hashes[session_id]:
            raise NormalizationError(f"source manifest changed during replay: {session_id}")
        for shard in session_manifest.shards:
            shard_path = root / shard.relative_path
            expected = _expected_shard_checksum(
                context.paired_report,
                session_id,
                shard.relative_path,
            )
            if sha256_file(shard_path) != expected:
                raise NormalizationError(f"raw shard changed during replay: {shard.relative_path}")


def _iter_raw_records(shard_path: Path) -> Iterator[RawArchiveRecord]:
    with shard_path.open("r", encoding="utf-8") as file_handle:
        for line in file_handle:
            if line.strip():
                yield RawArchiveRecord.from_json_line(line)


def _raw_frame_hash(record: RawArchiveRecord) -> str:
    return sha256_text(f"{record.venue.value}|{record.frame_type}|{record.frame_bytes().hex()}")


def _expected_shard_checksum(
    paired_report: PairedQualityReport,
    session_id: str,
    shard_relative_path: str,
) -> str:
    for report in (paired_report.coinbase_report, paired_report.kraken_report):
        if report.session_id == session_id:
            return report.input_shard_checksums[shard_relative_path]
    raise ValidatedManifestError(f"session report missing for {session_id}")


def _session_shard_checksums(paired_report: PairedQualityReport) -> dict[str, dict[str, str]]:
    return {
        report.session_id: dict(report.input_shard_checksums)
        for report in (paired_report.coinbase_report, paired_report.kraken_report)
    }


def _bounded(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:500]


def _working_tree_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == ""
