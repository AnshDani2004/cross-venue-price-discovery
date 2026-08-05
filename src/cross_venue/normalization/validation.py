"""Validation for finalized normalized datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cross_venue.normalization.exceptions import NormalizedDatasetValidationError
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json


def validate_normalized_dataset(normalization_manifest_path: Path) -> dict[str, Any]:
    """Validate a normalized dataset manifest and its Parquet outputs."""

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
            path = dataset_root / entry["relative_path"]
            if not path.exists():
                errors.append(f"missing output file: {entry['relative_path']}")
                continue
            actual_sha = sha256_file(path)
            if actual_sha != entry["sha256"]:
                errors.append(f"output checksum mismatch: {entry['relative_path']}")
                continue
            try:
                table = pq.read_table(path)
            except Exception as exc:
                errors.append(
                    f"output checksum mismatch or unreadable Parquet: {entry['relative_path']}"
                )
                errors.append(str(exc))
                continue
            if table.num_rows != entry["row_count"]:
                errors.append(f"row count mismatch: {entry['relative_path']}")
            if entry["table"] in table_counts:
                table_counts[entry["table"]] += table.num_rows
    for entry in manifest.get("per_session_normalization_manifest_files", []):
        path = dataset_root / entry["relative_path"]
        if not path.exists():
            errors.append(f"missing session normalization manifest: {entry['relative_path']}")
            continue
        actual_sha = sha256_file(path)
        if actual_sha != entry["sha256"]:
            errors.append(
                f"session normalization manifest checksum mismatch: {entry['relative_path']}"
            )
    if table_counts["trades"] != manifest["trade_row_count"]:
        errors.append("manifest trade row count mismatch")
    if table_counts["top_of_book"] != manifest["top_of_book_row_count"]:
        errors.append("manifest BBO row count mismatch")
    if table_counts["raw_record_outcomes"] != manifest["raw_record_outcome_row_count"]:
        errors.append("manifest outcome row count mismatch")
    if manifest["source_raw_record_count"] != manifest["raw_record_outcome_row_count"]:
        errors.append("source raw record count does not match outcome rows")
    if errors:
        report = {
            "validation_status": "INVALID",
            "errors": errors,
            "trade_row_count": table_counts["trades"],
            "top_of_book_row_count": table_counts["top_of_book"],
            "raw_record_outcome_row_count": table_counts["raw_record_outcomes"],
            "duplicate_event_id_count": None,
        }
        report_path = dataset_root / "validation" / "validation_report.json"
        atomic_write_json(report_path, dict(report))
        raise NormalizedDatasetValidationError("; ".join(errors))
    event_ids = _event_ids(dataset_root, manifest)
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
    atomic_write_json(report_path, dict(report))
    if errors:
        raise NormalizedDatasetValidationError("; ".join(errors))
    return report


def _event_ids(dataset_root: Path, manifest: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("trade_files", "top_of_book_files"):
        for entry in manifest.get(key, []):
            table = pq.read_table(
                dataset_root / entry["relative_path"], columns=["normalized_event_id"]
            )
            ids.extend(str(row["normalized_event_id"]) for row in table.to_pylist())
    return ids
