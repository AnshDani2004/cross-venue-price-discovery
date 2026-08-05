"""Determinism verification for normalized dataset replay."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from cross_venue.config import DataQualityConfig, NormalizationConfig, StorageConfig
from cross_venue.normalization.exceptions import DeterminismError
from cross_venue.normalization.normalizer import normalize_dataset


def verify_normalization_determinism(
    validated_manifest_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    normalization_config: NormalizationConfig,
) -> dict[str, Any]:
    """Normalize twice in isolated temporary roots and compare deterministic outputs."""

    with (
        tempfile.TemporaryDirectory(prefix="cross-venue-normalization-") as first,
        tempfile.TemporaryDirectory(prefix="cross-venue-normalization-") as second,
    ):
        first_result = normalize_dataset(
            validated_manifest_path,
            storage_config=storage_config,
            quality_config=quality_config,
            normalization_config=normalization_config,
            output_root=Path(first),
            require_clean=False,
        )
        second_result = normalize_dataset(
            validated_manifest_path,
            storage_config=storage_config,
            quality_config=quality_config,
            normalization_config=normalization_config,
            output_root=Path(second),
            require_clean=False,
        )
        if not hasattr(first_result, "manifest") or not hasattr(second_result, "manifest"):
            raise DeterminismError("normalization unexpectedly returned dry-run output")
        first_manifest = first_result.manifest
        second_manifest = second_result.manifest
        comparisons = {
            "event_id_equality": _file_hashes(first_manifest, "output_file_checksums")
            == _file_hashes(second_manifest, "output_file_checksums"),
            "semantic_hash_equality": first_manifest["semantic_dataset_hash"]
            == second_manifest["semantic_dataset_hash"],
            "row_count_equality": (
                first_manifest["trade_row_count"],
                first_manifest["top_of_book_row_count"],
                first_manifest["raw_record_outcome_row_count"],
            )
            == (
                second_manifest["trade_row_count"],
                second_manifest["top_of_book_row_count"],
                second_manifest["raw_record_outcome_row_count"],
            ),
            "parquet_checksum_equality": _file_hashes(first_manifest, "output_file_checksums")
            == _file_hashes(second_manifest, "output_file_checksums"),
            "manifest_equivalence": _manifest_equivalence(first_manifest, second_manifest),
        }
        if not all(comparisons.values()):
            raise DeterminismError(f"determinism mismatch: {comparisons}")
        return {
            "determinism_status": "PASSED",
            "comparisons": comparisons,
            "semantic_dataset_hash": first_manifest["semantic_dataset_hash"],
        }


def _file_hashes(manifest: dict[str, Any], key: str) -> dict[str, str]:
    return dict(manifest[key])


def _manifest_equivalence(first: dict[str, Any], second: dict[str, Any]) -> bool:
    ignored = {"created_at", "per_session_normalization_manifest_files"}
    first_filtered = {key: value for key, value in first.items() if key not in ignored}
    second_filtered = {key: value for key, value in second.items() if key not in ignored}
    return first_filtered == second_filtered
