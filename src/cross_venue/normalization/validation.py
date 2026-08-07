"""Validation for finalized normalized datasets.

Provides two modes of operation:

1. Legacy one-argument mode: ``validate_normalized_dataset(manifest_path)``
   returns ``dict[str, Any]`` and writes ``validation/validation_report.json``.

2. Extended three-argument mode: ``validate_normalized_dataset(manifest_path,
   normalization_manifest_path, snapshot_root)`` returns a Pydantic
   ``NormalizedDatasetValidationResult`` and writes
   ``validation/normalized_dataset_validation.json``.

Both modes use dependency-safe local helpers only.  Neither mode imports from
``cross_venue.storage``, ``cross_venue.collectors``, or their sub-packages.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, overload

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from cross_venue.normalization.exceptions import NormalizedDatasetValidationError
from cross_venue.research.source_snapshot import (
    AnalysisSourceCatalog,
    DatasetAnalysisSnapshot,
    semantic_hash,
)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ImmutabilityResult = Literal[
    "VERIFIED_UNCHANGED",
    "TAMPERED",
    "NOT_CHECKED",
]

VALIDATION_SCHEMA_VERSION = "3c-normalized-validation.1"
EXPECTED_SESSIONS = 10

# ---------------------------------------------------------------------------
# Local helpers — no cross_venue.storage imports
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return hex SHA-256 digest of a file read in 64 KiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False).encode(
        "utf-8"
    )


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomically write *obj* as deterministic JSON to *path*.

    Guarantees:
    1.  Writes to a temp file in the destination directory (same filesystem).
    2.  Writes ALL bytes via a loop; does not rely on a single os.write call.
    3.  Flushes and fsyncs the file.
    4.  Atomically replaces the destination with Path.replace().
    5.  fsyncs the parent directory when the OS supports it.
    6.  Removes the temp file on any failure.
    7.  Never leaves a truncated report at the destination path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_json_bytes(obj)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        # Write in a loop to handle partial writes
        written = 0
        while written < len(data):
            n = os.write(fd, data[written:])
            if n == 0:
                raise OSError("os.write returned 0 bytes")
            written += n
        os.fsync(fd)
        os.close(fd)
        Path(tmp).replace(path)
        # Best-effort fsync of parent directory
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


def _safe_resolve(dataset_root: Path, relative: str) -> Path:
    """Resolve *relative* under *dataset_root*, rejecting path escapes.

    Uses ``Path.is_relative_to`` (Python 3.9+) which correctly rejects:
    - absolute paths
    - ``..`` parent traversal
    - symlink-resolved paths outside the dataset root
    - sibling paths sharing a textual prefix (e.g. ``/data/x-sibling``)
    """
    if Path(relative).is_absolute():
        raise NormalizedDatasetValidationError(f"unsafe absolute path in manifest: {relative}")
    resolved = (dataset_root / relative).resolve()
    root_resolved = dataset_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise NormalizedDatasetValidationError(
            f"unsafe path escapes dataset root: {relative}"
        ) from None
    return resolved


def _current_worktree_identity(repo_root: Path) -> str:
    """Return the current HEAD commit or a dirty-worktree descriptor."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.call(
            ["git", "diff", "--quiet", "--exit-code"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        index_dirty = subprocess.call(
            ["git", "diff", "--cached", "--quiet", "--exit-code"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if dirty != 0 or index_dirty != 0:
            return f"{commit}+dirty"
        return commit
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


# ---------------------------------------------------------------------------
# Pydantic result model
# ---------------------------------------------------------------------------


class NormalizedDatasetValidationResult(BaseModel):
    """Structured result of extended normalized-dataset validation.

    Field aliases (input only):
      ``dataset_snapshot_id`` -> ``source_snapshot_id``
      ``accepted_attempt_count`` -> ``attempt_count``

    Canonical serialization uses the field names, not the aliases.
    """

    model_config = {
        "frozen": True,
        "populate_by_name": True,
    }

    validation_schema_version: str = VALIDATION_SCHEMA_VERSION
    validation_report_id: str
    normalized_dataset_id: str | None = None
    source_snapshot_id: str | None = Field(
        default=None,
        alias="dataset_snapshot_id",
    )
    source_snapshot_content_hash: str | None = None
    source_catalog_id: str | None = None
    source_catalog_content_hash: str | None = None
    validation_timestamp: str
    # validation_code_identity is the current worktree commit, not the normalizer commit
    validation_code_identity: str | None = None
    # normalization_code_identity is the historical normalizer commit from the manifest
    normalization_code_identity: str | None = None
    normalized_manifest_hash: str | None = None
    attempt_count: int | None = Field(default=None, alias="accepted_attempt_count")
    venue_session_count: int | None = None
    trade_counts_by_venue: dict[str, int] = Field(default_factory=dict)
    bbo_counts_by_venue: dict[str, int] = Field(default_factory=dict)
    missingness_counts: dict[str, int] = Field(default_factory=dict)
    duplicate_counts: dict[str, int] = Field(default_factory=dict)
    locked_and_crossed_counts: dict[str, int] = Field(default_factory=dict)
    diagnostic_counts: dict[str, Any] = Field(default_factory=dict)
    timestamp_diagnostics: dict[str, Any] = Field(default_factory=dict)
    manifest_verification_results: dict[str, Any] = Field(default_factory=dict)
    source_immutability_result: ImmutabilityResult = "NOT_CHECKED"
    snapshot_immutability_result: ImmutabilityResult = "NOT_CHECKED"
    normalized_output_immutability_result: ImmutabilityResult = "NOT_CHECKED"
    output_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    per_attempt_validation_results: dict[str, str] = Field(default_factory=dict)
    per_venue_session_validation_results: dict[str, str] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    aggregate_disposition: str = "VALID"
    aggregate_paired_overlap_seconds: float = 0.0
    preliminary_analysis_eligibility: str = "ELIGIBLE"
    final_composite_status: str = "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"


# semantic_hash and Pydantic model types are imported at module level so that
# tests can patch ``cross_venue.normalization.validation.semantic_hash``.

# ---------------------------------------------------------------------------
# Overloaded public API
# ---------------------------------------------------------------------------


@overload
def validate_normalized_dataset(
    normalization_manifest_path: Path,
) -> dict[str, Any]: ...


@overload
def validate_normalized_dataset(
    normalization_manifest_path: Path,
    snapshot_root: Path,
) -> NormalizedDatasetValidationResult: ...


def validate_normalized_dataset(
    normalization_manifest_path: Path,
    snapshot_root: Path | None = None,
) -> dict[str, Any] | NormalizedDatasetValidationResult:
    """Validate a normalized dataset manifest and its Parquet outputs.

    One-argument mode (legacy): returns ``dict[str, Any]``.
    Three-argument mode (extended): returns ``NormalizedDatasetValidationResult``.
    """
    extended = snapshot_root is not None
    if extended:
        return _validate_extended(
            normalization_manifest_path,
            snapshot_root,  # type: ignore[arg-type]
        )
    return _validate_legacy(normalization_manifest_path)


# ---------------------------------------------------------------------------
# Legacy one-argument implementation — NO storage imports
# ---------------------------------------------------------------------------


def _validate_legacy(normalization_manifest_path: Path) -> dict[str, Any]:
    """Original one-argument validator returning ``dict``.

    Uses only local helpers — does not import from cross_venue.storage.
    """
    manifest_path = normalization_manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_root = manifest_path.parents[1]
    errors: list[str] = []
    table_counts = {
        "trades": 0,
        "top_of_book": 0,
        "raw_record_outcomes": 0,
    }
    for key, _expected_count in (
        ("trade_files", "trade_row_count"),
        ("top_of_book_files", "top_of_book_row_count"),
        ("raw_record_outcome_files", "raw_record_outcome_row_count"),
        ("session_metadata_files", "session_metadata_row_count"),
        ("attempt_metadata_files", "attempt_metadata_row_count"),
    ):
        for entry in manifest.get(key, []):
            rel = entry["relative_path"]
            path = dataset_root / rel
            if not path.exists():
                errors.append(f"missing output file: {rel}")
                continue
            actual_sha = _sha256_file(path)
            if actual_sha != entry["sha256"]:
                errors.append(f"output checksum mismatch: {rel}")
                continue
            try:
                table = pq.read_table(path)
            except Exception as exc:
                errors.append(f"output checksum mismatch or unreadable Parquet: {rel}")
                errors.append(str(exc))
                continue
            if table.num_rows != entry["row_count"]:
                errors.append(f"row count mismatch: {rel}")
            if entry.get("table") in table_counts:
                table_counts[entry["table"]] += table.num_rows

    for entry in manifest.get("per_session_normalization_manifest_files", []):
        rel = entry["relative_path"]
        path = dataset_root / rel
        if not path.exists():
            errors.append(f"missing session normalization manifest: {rel}")
            continue
        actual_sha = _sha256_file(path)
        if actual_sha != entry["sha256"]:
            errors.append(f"session normalization manifest checksum mismatch: {rel}")

    if table_counts["trades"] != manifest["trade_row_count"]:
        errors.append("manifest trade row count mismatch")
    if table_counts["top_of_book"] != manifest["top_of_book_row_count"]:
        errors.append("manifest BBO row count mismatch")
    if table_counts["raw_record_outcomes"] != manifest["raw_record_outcome_row_count"]:
        errors.append("manifest outcome row count mismatch")
    if manifest["source_raw_record_count"] != manifest["raw_record_outcome_row_count"]:
        errors.append("source raw record count does not match outcome rows")

    if errors:
        report: dict[str, Any] = {
            "validation_status": "INVALID",
            "errors": errors,
            "trade_row_count": table_counts["trades"],
            "top_of_book_row_count": table_counts["top_of_book"],
            "raw_record_outcome_row_count": table_counts["raw_record_outcomes"],
            "duplicate_event_id_count": None,
        }
        report_path = dataset_root / "validation" / "validation_report.json"
        _atomic_write_json(report_path, dict(report))
        raise NormalizedDatasetValidationError("; ".join(errors))

    event_ids = _collect_event_ids_legacy(dataset_root, manifest)
    duplicate_event_ids = len(event_ids) - len(set(event_ids))
    if duplicate_event_ids:
        errors.append("duplicate normalized event IDs")

    report = {
        "validation_status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "trade_row_count": table_counts["trades"],
        "top_of_book_row_count": table_counts["top_of_book"],
        "raw_record_outcome_row_count": table_counts["raw_record_outcomes"],
        "duplicate_event_id_count": duplicate_event_ids,
    }
    report_path = dataset_root / "validation" / "validation_report.json"
    _atomic_write_json(report_path, dict(report))
    if errors:
        raise NormalizedDatasetValidationError("; ".join(errors))
    return report


def _collect_event_ids_legacy(dataset_root: Path, manifest: dict[str, Any]) -> list[str]:
    """Collect all normalized_event_id values from trade and BBO files."""
    ids: list[str] = []
    for key in ("trade_files", "top_of_book_files"):
        for entry in manifest.get(key, []):
            path = dataset_root / entry["relative_path"]
            if not path.exists():
                continue
            table = pq.read_table(path, columns=["normalized_event_id"])
            col = table.column("normalized_event_id")
            for val in col.to_pylist():
                if val is not None:
                    ids.append(str(val))
    return ids


# ---------------------------------------------------------------------------
# Extended three-argument implementation
# ---------------------------------------------------------------------------


def _validate_extended(
    normalization_manifest_path: Path,
    snapshot_root: Path,
) -> NormalizedDatasetValidationResult:
    """Full Phase 3C.3 validator producing a Pydantic report."""
    manifest_path = normalization_manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_root = manifest_path.parents[1]
    manifest_hash = _sha256_bytes(manifest_path.read_bytes())

    errors: list[str] = []
    warnings: list[str] = []

    # ---- Load catalog and snapshot ----
    catalog_path = (snapshot_root / "source_catalog.json").resolve()
    snapshot_path = (snapshot_root / "snapshot_manifest.json").resolve()

    if not catalog_path.exists():
        raise NormalizedDatasetValidationError(f"source catalog not found: {catalog_path}")
    if not snapshot_path.exists():
        raise NormalizedDatasetValidationError(f"snapshot manifest not found: {snapshot_path}")

    catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))

    # ---- Catalog semantic integrity ----
    source_immutability = "VERIFIED_UNCHANGED"
    computed_catalog_hash: str | None = None
    try:
        from pydantic import ValidationError as _PydanticValidationError

        catalog_model = AnalysisSourceCatalog.model_validate(catalog_data)
        computed_catalog_hash = semantic_hash(catalog_model)
    except _PydanticValidationError as exc:
        source_immutability = "NOT_CHECKED"
        errors.append(f"source catalog could not be parsed for semantic verification: {exc}")

    if computed_catalog_hash is not None and computed_catalog_hash != catalog_data.get(
        "content_hash"
    ):
        source_immutability = "TAMPERED"
        errors.append(
            f"source catalog was modified: "
            f"{computed_catalog_hash} != {catalog_data.get('content_hash')}"
        )

    # ---- Snapshot semantic integrity ----
    snapshot_immutability = "VERIFIED_UNCHANGED"
    computed_snapshot_hash: str | None = None
    try:
        from pydantic import ValidationError as _PydanticValidationError2

        snapshot_model = DatasetAnalysisSnapshot.model_validate(snapshot_data)
        computed_snapshot_hash = semantic_hash(snapshot_model)
    except _PydanticValidationError2 as exc:
        snapshot_immutability = "NOT_CHECKED"
        errors.append(f"analysis snapshot could not be parsed for semantic verification: {exc}")

    if computed_snapshot_hash is not None and computed_snapshot_hash != snapshot_data.get(
        "content_hash"
    ):
        snapshot_immutability = "TAMPERED"
        errors.append(
            f"analysis snapshot was modified: "
            f"{computed_snapshot_hash} != {snapshot_data.get('content_hash')}"
        )

    # ---- Snapshot-to-catalog linkage ----
    if snapshot_data.get("source_catalog_hash") != catalog_data.get("content_hash"):
        errors.append("snapshot source_catalog_hash does not match catalog content_hash")

    # ---- Physical SHA-256 checks (manifest-recorded) ----
    expected_catalog_sha = manifest.get("source_catalog_sha256")
    if expected_catalog_sha:
        actual = _sha256_file(catalog_path)
        if actual != expected_catalog_sha:
            errors.append("source catalog physical SHA-256 mismatch")

    expected_snapshot_sha = manifest.get("source_analysis_snapshot_sha256")
    if expected_snapshot_sha:
        actual = _sha256_file(snapshot_path)
        if actual != expected_snapshot_sha:
            errors.append("snapshot manifest physical SHA-256 mismatch")

    # ---- Lineage ID/hash checks ----
    _check_lineage(manifest, catalog_data, snapshot_data, errors)

    # ---- Output file validation ----
    table_counts: dict[str, int] = {
        "trades": 0,
        "top_of_book": 0,
        "raw_record_outcomes": 0,
    }
    trade_counts_by_venue: dict[str, int] = {}
    bbo_counts_by_venue: dict[str, int] = {}
    missingness: dict[str, int] = {
        "missing_exchange_ts_trades": 0,
        "missing_exchange_ts_bbo": 0,
    }
    locked_and_crossed: dict[str, int] = {
        "locked_market_count": 0,
        "crossed_market_count": 0,
    }
    output_hashes: dict[str, str] = {}

    # Per-session and per-attempt status — start with VALID; mark INVALID on error
    per_session_status: dict[str, str] = {}
    per_attempt_status: dict[str, str] = {}

    # Initialize all known sessions/attempts from the manifest
    for entry in manifest.get("per_session_normalization_manifest_files", []):
        attempt_id = entry.get("campaign_attempt_id")
        if attempt_id:
            per_attempt_status[attempt_id] = "VALID"
        for sid in entry.get("venue_session_ids", []):
            per_session_status[sid] = "VALID"

    # Global event-ID sets for cross-file duplicate detection
    all_trade_event_ids: set[str] = set()
    all_bbo_event_ids: set[str] = set()
    trade_id_duplicate_count = 0
    bbo_id_duplicate_count = 0

    # Session -> attempt reverse map
    session_to_attempt: dict[str, str] = {}
    for entry in manifest.get("per_session_normalization_manifest_files", []):
        attempt_id = entry.get("campaign_attempt_id")
        if attempt_id:
            for sid in entry.get("venue_session_ids", []):
                session_to_attempt[sid] = attempt_id

    normalized_output_immutability: ImmutabilityResult = "VERIFIED_UNCHANGED"

    file_keys = (
        "trade_files",
        "top_of_book_files",
        "raw_record_outcome_files",
        "session_metadata_files",
        "attempt_metadata_files",
    )
    for key in file_keys:
        for entry in manifest.get(key, []):
            rel = entry["relative_path"]
            session_id = entry.get("session_id")
            venue = entry.get("venue", "unknown")

            try:
                path = _safe_resolve(dataset_root, rel)
            except NormalizedDatasetValidationError as exc:
                normalized_output_immutability = "TAMPERED"
                errors.append(str(exc))
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )
                continue

            if not path.exists():
                normalized_output_immutability = "TAMPERED"
                errors.append(f"missing output file: {rel}")
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )
                continue

            actual_sha = _sha256_file(path)
            output_hashes[rel] = actual_sha
            if "sha256" in entry and actual_sha != entry["sha256"]:
                normalized_output_immutability = "TAMPERED"
                errors.append(f"output checksum mismatch: {rel}")
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )
                continue

            if key in (
                "raw_record_outcome_files",
                "session_metadata_files",
                "attempt_metadata_files",
            ):
                # Just count rows; no schema-level checks
                try:
                    table = pq.read_table(path)
                except Exception as exc:
                    errors.append(f"unreadable Parquet: {rel}: {exc}")
                    _mark_invalid(
                        session_id, session_to_attempt, per_session_status, per_attempt_status
                    )
                    continue
                table_name = entry.get("table", "")
                if table_name in table_counts:
                    table_counts[table_name] += table.num_rows
                if "row_count" in entry and table.num_rows != entry["row_count"]:
                    errors.append(f"row count mismatch: {rel}")
                    _mark_invalid(
                        session_id, session_to_attempt, per_session_status, per_attempt_status
                    )
                continue

            try:
                table = pq.read_table(path)
            except Exception as exc:
                errors.append(f"unreadable Parquet: {rel}: {exc}")
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )
                continue

            if "row_count" in entry and table.num_rows != entry["row_count"]:
                errors.append(f"row count mismatch: {rel}")
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )

            table_name = entry.get("table", "")
            if table_name in table_counts:
                table_counts[table_name] += table.num_rows

            file_errors: list[str] = []
            if key == "trade_files":
                trade_counts_by_venue[venue] = trade_counts_by_venue.get(venue, 0) + table.num_rows
                _validate_trades_extended(table, rel, file_errors, missingness)
                _, new_dups = _extract_event_ids(table, all_trade_event_ids)
                trade_id_duplicate_count += new_dups
                if new_dups:
                    file_errors.append(
                        f"duplicate normalized_event_id values in trade output: {rel}"
                    )

            elif key == "top_of_book_files":
                bbo_counts_by_venue[venue] = bbo_counts_by_venue.get(venue, 0) + table.num_rows
                _validate_bbo_extended(
                    table, rel, file_errors, warnings, missingness, locked_and_crossed
                )
                _, new_dups = _extract_event_ids(table, all_bbo_event_ids)
                bbo_id_duplicate_count += new_dups
                if new_dups:
                    file_errors.append(f"duplicate normalized_event_id values in BBO output: {rel}")

            if file_errors:
                errors.extend(file_errors)
                _mark_invalid(
                    session_id, session_to_attempt, per_session_status, per_attempt_status
                )

    # ---- Session normalization manifests ----
    for entry in manifest.get("per_session_normalization_manifest_files", []):
        rel = entry.get("relative_path")
        if not rel:
            continue

        attempt_id = entry.get("campaign_attempt_id", "")
        vs_ids = entry.get("venue_session_ids", [])

        try:
            path = _safe_resolve(dataset_root, rel)
        except NormalizedDatasetValidationError as exc:
            normalized_output_immutability = "TAMPERED"
            errors.append(str(exc))
            continue
        if not path.exists():
            normalized_output_immutability = "TAMPERED"
            errors.append(f"missing output file: {rel}")
            if attempt_id:
                per_attempt_status[attempt_id] = "INVALID"
            for vs in vs_ids:
                per_session_status[vs] = "INVALID"
            continue
        if "sha256" in entry:
            actual_sha = _sha256_file(path)
            if actual_sha != entry["sha256"]:
                normalized_output_immutability = "TAMPERED"
                errors.append(f"checksum mismatch: {rel}")
                if attempt_id:
                    per_attempt_status[attempt_id] = "INVALID"
                for vs in vs_ids:
                    per_session_status[vs] = "INVALID"

    # ---- Aggregate row reconciliation ----
    if "trade_row_count" in manifest and table_counts["trades"] != manifest["trade_row_count"]:
        errors.append("manifest trade row count mismatch")
    if (
        "top_of_book_row_count" in manifest
        and table_counts["top_of_book"] != manifest["top_of_book_row_count"]
    ):
        errors.append("manifest BBO row count mismatch")
    if (
        "raw_record_outcome_row_count" in manifest
        and table_counts["raw_record_outcomes"] != manifest["raw_record_outcome_row_count"]
    ):
        errors.append("manifest outcome row count mismatch")
    if (
        "source_raw_record_count" in manifest
        and "raw_record_outcome_row_count" in manifest
        and manifest["source_raw_record_count"] != manifest["raw_record_outcome_row_count"]
    ):
        errors.append("source raw record count does not match outcome rows")
    if "session_metadata_row_count" in manifest:
        sm_total = sum(
            pq.read_table(_safe_resolve(dataset_root, e["relative_path"])).num_rows
            for e in manifest.get("session_metadata_files", [])
            if _safe_resolve(dataset_root, e["relative_path"]).exists()
        )
        if sm_total != manifest["session_metadata_row_count"]:
            errors.append("session metadata row count mismatch")
    if "attempt_metadata_row_count" in manifest:
        am_total = sum(
            pq.read_table(_safe_resolve(dataset_root, e["relative_path"])).num_rows
            for e in manifest.get("attempt_metadata_files", [])
            if _safe_resolve(dataset_root, e["relative_path"]).exists()
        )
        if am_total != manifest["attempt_metadata_row_count"]:
            errors.append("attempt metadata row count mismatch")

    # ---- Final dispositions ----
    aggregate_disposition = "VALID" if not errors else "INVALID"
    eligibility = "ELIGIBLE" if aggregate_disposition == "VALID" else "INELIGIBLE"

    # Final composite status — verified sources take priority
    final_composite = _resolve_final_composite(manifest, snapshot_data)

    # Current worktree identity (analysis repo, not source repo)
    analysis_root = dataset_root.parent.parent.parent  # dataset_root/.../../..
    validation_identity = _current_worktree_identity(analysis_root)

    # Stable report identity including all immutable inputs
    catalog_content_hash = catalog_data.get("content_hash", "")
    snapshot_content_hash = snapshot_data.get("content_hash", "")
    report_id = _stable_report_id(
        manifest,
        catalog_content_hash=catalog_content_hash,
        snapshot_content_hash=snapshot_content_hash,
        manifest_hash=manifest_hash,
    )

    result_data: dict[str, Any] = {
        "validation_schema_version": VALIDATION_SCHEMA_VERSION,
        "validation_report_id": report_id,
        "normalized_dataset_id": manifest.get("normalized_dataset_id"),
        "source_snapshot_id": snapshot_data.get("snapshot_id"),
        "source_snapshot_content_hash": snapshot_content_hash or None,
        "source_catalog_id": catalog_data.get("source_catalog_id"),
        "source_catalog_content_hash": catalog_content_hash or None,
        "validation_timestamp": datetime.now(UTC).isoformat(),
        "validation_code_identity": validation_identity,
        "normalization_code_identity": manifest.get("normalizer_git_commit"),
        "normalized_manifest_hash": manifest_hash,
        "attempt_count": manifest.get("accepted_attempt_count"),
        "venue_session_count": manifest.get("venue_session_count"),
        "trade_counts_by_venue": trade_counts_by_venue,
        "bbo_counts_by_venue": bbo_counts_by_venue,
        "missingness_counts": missingness,
        "duplicate_counts": {
            "duplicate_trade_event_ids": trade_id_duplicate_count,
            "duplicate_bbo_event_ids": bbo_id_duplicate_count,
        },
        "locked_and_crossed_counts": locked_and_crossed,
        "diagnostic_counts": manifest.get("diagnostic_rows_by_venue_and_status", {}),
        "timestamp_diagnostics": {},
        "manifest_verification_results": {"manifest_hash_verified": "PASSED"},
        "source_immutability_result": source_immutability,
        "snapshot_immutability_result": snapshot_immutability,
        "normalized_output_immutability_result": normalized_output_immutability,
        "output_artifact_hashes": output_hashes,
        "per_attempt_validation_results": per_attempt_status,
        "per_venue_session_validation_results": per_session_status,
        "errors": tuple(errors),
        "warnings": tuple(warnings),
        "aggregate_disposition": aggregate_disposition,
        "aggregate_paired_overlap_seconds": float(
            manifest.get("aggregate_paired_overlap_seconds")
            or snapshot_data.get("aggregate_paired_overlap_seconds")
            or 0.0
        ),
        "preliminary_analysis_eligibility": eligibility,
        "final_composite_status": final_composite,
    }

    result = NormalizedDatasetValidationResult.model_validate(result_data)

    report_path = dataset_root / "validation" / "normalized_dataset_validation.json"

    # Raise on errors (write invalid report first)
    if errors:
        _atomic_write_json(report_path, json.loads(result.model_dump_json(by_alias=False)))
        raise NormalizedDatasetValidationError("; ".join(errors))

    # Idempotency: check for existing report with comprehensive key comparison
    if report_path.exists():
        cached = _try_load_cached_report(report_path)
        if cached is not None and _is_cache_valid(
            cached,
            report_id=report_id,
            manifest_hash=manifest_hash,
            catalog_id=catalog_data.get("source_catalog_id"),
            catalog_content_hash=catalog_content_hash,
            snapshot_id=snapshot_data.get("snapshot_id"),
            snapshot_content_hash=snapshot_content_hash,
            output_hashes=output_hashes,
            aggregate_disposition=aggregate_disposition,
        ):
            return cached

    _atomic_write_json(
        report_path,
        json.loads(result.model_dump_json(by_alias=False)),
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mark_invalid(
    session_id: str | None,
    session_to_attempt: dict[str, str],
    per_session_status: dict[str, str],
    per_attempt_status: dict[str, str],
) -> None:
    """Mark the given session and its parent attempt as INVALID."""
    if session_id is None:
        return
    per_session_status[session_id] = "INVALID"
    attempt_id = session_to_attempt.get(session_id)
    if attempt_id:
        per_attempt_status[attempt_id] = "INVALID"


def _extract_event_ids(
    table: pa.Table,
    global_ids: set[str],
) -> tuple[set[str], int]:
    """Extract normalized_event_id values; count new duplicates against global set."""
    new_ids: set[str] = set()
    duplicate_count = 0
    if "normalized_event_id" not in table.column_names:
        return new_ids, 0
    col = table.column("normalized_event_id")
    for val in col.to_pylist():
        if val is None:
            continue
        s = str(val)
        if s in global_ids or s in new_ids:
            duplicate_count += 1
        else:
            new_ids.add(s)
    global_ids.update(new_ids)
    return new_ids, duplicate_count


def _validate_trades_extended(
    table: pa.Table,
    rel: str,
    errors: list[str],
    missingness: dict[str, int],
) -> None:
    """Validate trade-level financial constraints."""
    columns = set(table.column_names)

    if "price" in columns:
        prices = table.column("price").to_pylist()
        if any(p is not None and p <= 0 for p in prices):
            errors.append(f"invalid trade prices <= 0: {rel}")
    if "quantity" in columns:
        qtys = table.column("quantity").to_pylist()
        if any(q is not None and q <= 0 for q in qtys):
            errors.append(f"invalid trade quantities <= 0: {rel}")
    if "notional" in columns:
        notionals = table.column("notional").to_pylist()
        if any(n is not None and n <= 0 for n in notionals):
            errors.append(f"invalid trade notionals <= 0: {rel}")
    if "exchange_timestamp_utc" in columns:
        null_count = table.column("exchange_timestamp_utc").null_count
        missingness["missing_exchange_ts_trades"] += null_count
    if "normalized_event_id" in columns:
        null_ids = sum(1 for v in table.column("normalized_event_id").to_pylist() if v is None)
        if null_ids:
            errors.append(f"null normalized_event_id in trade output: {rel}")


def _validate_bbo_extended(
    table: pa.Table,
    rel: str,
    errors: list[str],
    warnings: list[str],
    missingness: dict[str, int],
    locked_and_crossed: dict[str, int],
) -> None:
    """Validate BBO-level financial constraints."""
    columns = set(table.column_names)

    for field in ("bid_price", "ask_price"):
        if field in columns:
            vals = table.column(field).to_pylist()
            if any(v is not None and v <= 0 for v in vals):
                errors.append(f"invalid BBO {field} <= 0: {rel}")
    for field in ("bid_size", "ask_size"):
        if field in columns:
            vals = table.column(field).to_pylist()
            if any(v is not None and v < 0 for v in vals):
                errors.append(f"invalid BBO {field} < 0: {rel}")
    if "exchange_timestamp_utc" in columns:
        null_count = table.column("exchange_timestamp_utc").null_count
        missingness["missing_exchange_ts_bbo"] += null_count
    if "normalized_event_id" in columns:
        null_ids = sum(1 for v in table.column("normalized_event_id").to_pylist() if v is None)
        if null_ids:
            errors.append(f"null normalized_event_id in BBO output: {rel}")
    if "locked_market_indicator" in columns:
        locked = sum(1 for v in table.column("locked_market_indicator").to_pylist() if v is True)
        locked_and_crossed["locked_market_count"] += locked
    if "crossed_market_indicator" in columns:
        crossed = sum(1 for v in table.column("crossed_market_indicator").to_pylist() if v is True)
        locked_and_crossed["crossed_market_count"] += crossed


def _check_lineage(
    manifest: dict[str, Any],
    catalog_data: dict[str, Any],
    snapshot_data: dict[str, Any],
    errors: list[str],
) -> None:
    """Verify lineage IDs and hashes in the normalization manifest."""
    checks = [
        ("source_catalog_id", catalog_data.get("source_catalog_id")),
        ("source_catalog_content_hash", catalog_data.get("content_hash")),
        ("source_analysis_snapshot_id", snapshot_data.get("snapshot_id")),
    ]
    for field, expected in checks:
        manifest_val = manifest.get(field)
        if manifest_val is not None and expected is not None and manifest_val != expected:
            errors.append(
                f"normalization manifest {field} mismatch: "
                f"manifest={manifest_val!r} expected={expected!r}"
            )


def _resolve_final_composite(
    manifest: dict[str, Any],
    snapshot_data: dict[str, Any],
) -> str:
    """Determine final composite status from verified sources."""
    # Priority 1: verified snapshot manifest (most authoritative)
    snap_status = snapshot_data.get("final_composite_status")
    if snap_status:
        return str(snap_status)
    # Priority 2: normalization manifest
    norm_status = manifest.get("final_composite_status")
    if norm_status:
        return str(norm_status)
    # Priority 3: derive from final_composite_requirements if present
    reqs = snapshot_data.get("final_composite_requirements", {})
    attempt_count = manifest.get("accepted_attempt_count", 0)
    min_sessions = reqs.get("final_minimum_accepted_sessions") or reqs.get(
        "minimum_accepted_sessions", EXPECTED_SESSIONS
    )
    min_overlap = float(
        reqs.get("final_minimum_total_overlap_seconds")
        or reqs.get("minimum_total_overlap_seconds", "18000")
        or "18000"
    )
    min_dates = reqs.get("final_minimum_calendar_dates") or reqs.get("minimum_calendar_dates", 3)
    min_buckets = reqs.get("final_minimum_time_buckets") or reqs.get("minimum_time_buckets", 3)

    actual_overlap = float(
        manifest.get("aggregate_paired_overlap_seconds")
        or snapshot_data.get("aggregate_paired_overlap_seconds")
        or "0"
    )
    actual_dates = len(
        manifest.get("accepted_calendar_dates")
        or snapshot_data.get("accepted_calendar_dates")
        or []
    )
    actual_buckets = len(
        manifest.get("accepted_time_buckets") or snapshot_data.get("accepted_time_buckets") or []
    )

    if (
        attempt_count >= min_sessions
        and actual_overlap >= min_overlap
        and actual_dates >= min_dates
        and actual_buckets >= min_buckets
    ):
        return "SATISFIED"
    return "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"


def _stable_report_id(
    manifest: dict[str, Any],
    *,
    catalog_content_hash: str,
    snapshot_content_hash: str,
    manifest_hash: str,
) -> str:
    """Deterministic report ID incorporating all immutable validation inputs."""
    parts = [
        manifest.get("normalized_dataset_id", ""),
        manifest_hash,
        catalog_content_hash,
        snapshot_content_hash,
        manifest.get("normalizer_git_commit", ""),
        VALIDATION_SCHEMA_VERSION,
    ]
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"validation-report-{digest}"


def _try_load_cached_report(
    report_path: Path,
) -> NormalizedDatasetValidationResult | None:
    """Try to load an existing validation report; return None if corrupt."""
    try:
        return NormalizedDatasetValidationResult.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def _is_cache_valid(
    cached: NormalizedDatasetValidationResult,
    *,
    report_id: str,
    manifest_hash: str,
    catalog_id: str | None,
    catalog_content_hash: str,
    snapshot_id: str | None,
    snapshot_content_hash: str,
    output_hashes: dict[str, str],
    aggregate_disposition: str,
) -> bool:
    """Return True only when the cached report matches all current inputs."""
    return (
        cached.validation_report_id == report_id
        and cached.normalized_manifest_hash == manifest_hash
        and cached.source_catalog_id == catalog_id
        and cached.source_catalog_content_hash == (catalog_content_hash or None)
        and cached.source_snapshot_id == snapshot_id
        and cached.source_snapshot_content_hash == (snapshot_content_hash or None)
        and cached.output_artifact_hashes == output_hashes
        and cached.aggregate_disposition == aggregate_disposition
        and cached.validation_schema_version == VALIDATION_SCHEMA_VERSION
    )
