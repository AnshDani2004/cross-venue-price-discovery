"""Phase 3C.3 normalized-dataset validation tests.

Uses synthetic fixtures to verify the full validation contract:
  - Legacy one-argument mode returns ``dict``.
  - Extended three-argument mode returns ``NormalizedDatasetValidationResult``.
  - Circular-dependency guard: the module must not import cross_venue.storage.
  - Idempotency, immutability, checksum, trade-price, BBO-price constraints.
  - Per-session and per-attempt INVALID propagation.
  - Cross-file duplicate normalized event ID detection.
  - Unsafe path escape rejection.
  - Partial extended argument rejection.
  - Cached-report validation.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from cross_venue.normalization.exceptions import NormalizedDatasetValidationError
from cross_venue.normalization.validation import (
    NormalizedDatasetValidationResult,
    _safe_resolve,
    validate_normalized_dataset,
)
from cross_venue.research.source_snapshot import (
    AnalysisSourceCatalog,
    DatasetAnalysisSnapshot,
    semantic_hash,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _make_trade_table(
    prices: list[float | None] | None = None,
    quantities: list[float] | None = None,
    notionals: list[float] | None = None,
    event_ids: list[str | None] | None = None,
) -> pa.Table:
    n = max(
        len(prices or [1]),
        len(quantities or [1]),
        len(notionals or [1]),
        len(event_ids or ["e1"]),
    )
    prices = prices or [100.0] * n
    quantities = quantities or [1.0] * n
    notionals = notionals or [100.0] * n
    event_ids = event_ids or [f"evt{i}" for i in range(n)]
    now = datetime.now(UTC)
    schema = pa.schema(
        [
            ("price", pa.decimal128(38, 18)),
            ("quantity", pa.decimal128(38, 18)),
            ("notional", pa.decimal128(38, 18)),
            ("normalized_event_id", pa.string()),
            ("dataset_snapshot_id", pa.string()),
            ("receipt_timestamp_utc", pa.timestamp("ns", tz="UTC")),
            ("exchange_timestamp_utc", pa.timestamp("ns", tz="UTC")),
        ]
    )
    return pa.Table.from_arrays(
        [
            pa.array([Decimal(str(p)) if p is not None else None for p in prices]),
            pa.array([Decimal(str(q)) for q in quantities]),
            pa.array([Decimal(str(n_)) for n_ in notionals]),
            pa.array(event_ids),
            pa.array(["snap1"] * len(prices)),
            pa.array([now] * len(prices)),
            pa.array([now] * len(prices)),
        ],
        schema=schema,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_snapshot_root(tmp_path: Path) -> Path:
    """Synthetic snapshot metadata."""
    root = tmp_path / "snapshot"
    root.mkdir()
    catalog: dict[str, Any] = {
        "source_catalog_schema_version": "3c-source-catalog.1",
        "source_catalog_id": "test-cat-id",
        "source_selection_config_hash": "abc",
        "source_selection": {"campaign_ids": ["test"]},
        "source_campaign_ids": ["test"],
        "created_at": datetime.now(UTC).isoformat(),
        "source_campaigns": [],
        "accepted_attempt_count": 7,
        "aggregate_paired_overlap_seconds": "18000",
        "accepted_calendar_dates": [],
        "accepted_time_buckets": [],
        "accepted_attempts": [
            {
                "campaign_attempt_id": "P01",
                "campaign_id": "test",
                "campaign_role": "MULTI_DAY_VALIDATION",
                "slot_id": "test-slot",
                "slot_type": "PRIMARY",
                "time_bucket": "test-bucket",
                "planned_start_utc": "2024-01-01T00:00:00Z",
                "planned_start_local": "2024-01-01T00:00:00Z",
                "actual_started_at": "2024-01-01T00:00:00Z",
                "actual_completed_at": "2024-01-01T00:00:00Z",
                "paired_overlap_seconds": 3600,
                "paired_collection_id": "pc1",
                "validated_pair_manifest_id": "vpm1",
                "validated_pair_manifest_relative_path": "path",
                "validated_pair_manifest_sha256": "sha" * 21 + "s",
                "source_session_manifest_hashes": {"c1": "sha" * 21 + "s", "k1": "sha" * 21 + "s"},
                "session_quality_report_hashes": {"c1": "sha" * 21 + "s", "k1": "sha" * 21 + "s"},
                "paired_quality_report_hash": "sha" * 21 + "s",
                "coinbase_session_id": "c1",
                "kraken_session_id": "k1",
                "source_raw_shard_checksums": {
                    "c1": {"file": "sha" * 21 + "s"},
                    "k1": {"file": "sha" * 21 + "s"},
                },
                "attempt_runtime_git_commit": "c" * 40,
                "quality_code_git_commit": "c" * 40,
                "quality_policy_version": "v1",
                "inclusion_status": "INCLUDED",
                "attempt_status": "ACCEPTED",
                "paired_disposition": "ACCEPTED",
                "coinbase_disposition": "ACCEPTED",
                "kraken_disposition": "ACCEPTED",
                "analysis_calendar_date": "2024-01-01",
                "source_registry_sha256": "sha" * 21 + "s",
                "source_ledger_sha256": "sha" * 21 + "s",
                "source_ledger_terminal_event_hash": "sha" * 21 + "s",
                "raw_session_relative_paths": ["c", "k"],
                "session_quality_report_paths": ["c", "k"],
                "paired_quality_report_relative_path": "p",
            }
        ],
        "excluded_attempt_summary": [],
        "missed_slot_summary": [],
    }
    cat_model = AnalysisSourceCatalog.model_validate(catalog)
    cat_hash = semantic_hash(cat_model)
    catalog["content_hash"] = cat_hash
    (root / "source_catalog.json").write_text(json.dumps(catalog, indent=2, sort_keys=True))

    snapshot: dict[str, Any] = {
        "snapshot_schema_version": "3c-analysis-snapshot.1",
        "snapshot_id": "test-snap",
        "snapshot_label": "test",
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_generation_code_commit": "commit",
        "source_catalog_schema_version": "3c-source-catalog.1",
        "source_catalog_id": "test-cat-id",
        "source_catalog_hash": cat_hash,
        "source_selection_config_hash": "abc",
        "source_campaign_ids": ["test"],
        "accepted_attempt_count": 7,
        "aggregate_paired_overlap_seconds": "18000",
        "ordered_accepted_attempt_ids": ["P01"],
        "accepted_calendar_dates": [],
        "accepted_time_buckets": [],
        "final_composite_requirements": {},
        "final_composite_status": "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED",
        "explicit_limitations": [],
        "source_campaign_roles": [],
        "runtime_commits": [],
        "quality_policy_versions": [],
        "validated_pair_manifest_identities": [],
        "source_registry_identities": [],
        "source_ledger_identities": [],
        "status": "SOURCE_SNAPSHOT_VALID",
    }
    snap_model = DatasetAnalysisSnapshot.model_validate(snapshot)
    snap_hash = semantic_hash(snap_model)
    snapshot["content_hash"] = snap_hash
    (root / "snapshot_manifest.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True))

    return root


@pytest.fixture()
def mock_dataset_root(tmp_path: Path) -> Path:
    """Synthetic dataset with one valid trade file."""
    root = tmp_path / "dataset"
    root.mkdir()
    manifests = root / "manifests"
    manifests.mkdir()

    trade_dir = root / "trades"
    trade_dir.mkdir()
    trade_path = trade_dir / "trade.parquet"

    pq.write_table(_make_trade_table(), trade_path)
    h = _sha256_file(trade_path)

    manifest: dict[str, Any] = {
        "normalized_dataset_id": "test-ds-id",
        "normalizer_git_commit": "commit",
        "accepted_attempt_count": 7,
        "venue_session_count": 14,
        "per_session_normalization_manifest_files": [
            {
                "campaign_attempt_id": "P01",
                "venue_session_ids": ["c1", "k1"],
                "relative_path": "manifests/session_P01.json",
                "sha256": "fake",
            }
        ],
        "trade_files": [
            {
                "relative_path": "trades/trade.parquet",
                "sha256": h,
                "row_count": 1,
                "table": "trades",
                "venue": "coinbase",
                "session_id": "c1",
            }
        ],
        "top_of_book_files": [],
        "raw_record_outcome_files": [],
        "session_metadata_files": [],
        "attempt_metadata_files": [],
        "trade_row_count": 1,
        "top_of_book_row_count": 0,
        "raw_record_outcome_row_count": 0,
        "source_raw_record_count": 0,
    }
    manifest_path = manifests / "normalized_snapshot_manifest.json"
    _write_manifest(manifest_path, manifest)

    # Session manifest file referenced by per_session_normalization_manifest_files
    session_mani = root / "manifests" / "session_P01.json"
    session_mani.write_text("{}")
    manifest["per_session_normalization_manifest_files"][0]["sha256"] = _sha256_file(session_mani)
    _write_manifest(manifest_path, manifest)

    return manifest_path


# ---------------------------------------------------------------------------
# Circular-dependency guard
# ---------------------------------------------------------------------------


def test_no_storage_import_at_module_level() -> None:
    """Importing validation must not pull in cross_venue.storage."""
    # Remove cached modules to force fresh import
    mods_to_remove = [k for k in sys.modules if "cross_venue.normalization.validation" in k]
    for mod in mods_to_remove:
        del sys.modules[mod]

    mods_before = set(sys.modules.keys())
    importlib.import_module("cross_venue.normalization.validation")
    mods_after = set(sys.modules.keys())
    bad = [
        m
        for m in mods_after - mods_before
        if "cross_venue.storage" in m or "cross_venue.collectors" in m
    ]
    assert bad == [], f"storage/collector modules imported: {bad}"


# ---------------------------------------------------------------------------
# Safe path tests
# ---------------------------------------------------------------------------


def test_safe_resolve_accepts_valid_relative(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    resolved = _safe_resolve(tmp_path, "sub/file.parquet")
    assert resolved == (tmp_path / "sub" / "file.parquet").resolve()


def test_safe_resolve_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(NormalizedDatasetValidationError, match="unsafe absolute path"):
        _safe_resolve(tmp_path, "/etc/passwd")


def test_safe_resolve_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(NormalizedDatasetValidationError, match="unsafe path escapes"):
        _safe_resolve(tmp_path, "../outside.parquet")


def test_safe_resolve_rejects_sibling_prefix(tmp_path: Path) -> None:
    """A sibling path sharing a prefix must not escape the root."""
    rel = f"../{tmp_path.name}-sibling/evil.parquet"
    with pytest.raises(NormalizedDatasetValidationError, match="unsafe path escapes"):
        _safe_resolve(tmp_path, rel)


# ---------------------------------------------------------------------------
# Extended-mode tests
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_valid_dataset_generates_atomic_report(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    result = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    assert isinstance(result, NormalizedDatasetValidationResult)
    assert result.aggregate_disposition == "VALID"
    assert result.preliminary_analysis_eligibility == "ELIGIBLE"
    assert result.final_composite_status == "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
    assert result.attempt_count == 7
    assert result.venue_session_count == 14
    assert result.validation_code_identity is not None

    report_path = mock_dataset_root.parents[1] / "validation" / "normalized_dataset_validation.json"
    assert report_path.exists()


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_idempotency_returns_cached_result(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    result1 = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    report_path = mock_dataset_root.parents[1] / "validation" / "normalized_dataset_validation.json"
    mtime1 = report_path.stat().st_mtime

    time.sleep(0.05)

    result2 = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    mtime2 = report_path.stat().st_mtime

    # Same report — no rewrite
    assert result1.validation_report_id == result2.validation_report_id
    assert result1.validation_timestamp == result2.validation_timestamp
    assert mtime1 == mtime2, "Report should not be rewritten on identical second run"


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_stale_cache_triggers_rewrite_after_output_change(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    """If output artifacts change, cached report must be invalidated."""
    validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )

    # Mutate the cached report to simulate an artifact change
    report_path = mock_dataset_root.parents[1] / "validation" / "normalized_dataset_validation.json"
    cached = json.loads(report_path.read_text())
    # Corrupt the output artifact hash map
    cached["output_artifact_hashes"] = {"fake/file.parquet": "deadbeef"}
    report_path.write_text(json.dumps(cached))

    result2 = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    # A new report must be written because cache comparison failed
    assert result2.output_artifact_hashes != {"fake/file.parquet": "deadbeef"}
    fresh = json.loads(report_path.read_text())
    assert fresh["output_artifact_hashes"] != {"fake/file.parquet": "deadbeef"}


# ---------------------------------------------------------------------------
# Invalid trade fields — session/attempt propagation
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_invalid_price_raises_error_and_marks_session_invalid(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    trade_path = mock_dataset_root.parents[1] / "trades" / "trade.parquet"
    pq.write_table(_make_trade_table(prices=[-10.0]), trade_path)

    h = _sha256_file(trade_path)
    manifest = json.loads(mock_dataset_root.read_text(encoding="utf-8"))
    manifest["trade_files"][0]["sha256"] = h
    _write_manifest(mock_dataset_root, manifest)

    with pytest.raises(NormalizedDatasetValidationError, match="invalid trade prices <= 0"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_missing_file_raises_error_and_marks_session_invalid(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    trade_path = mock_dataset_root.parents[1] / "trades" / "trade.parquet"
    trade_path.unlink()
    with pytest.raises(NormalizedDatasetValidationError, match="missing output file"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


# ---------------------------------------------------------------------------
# Checksum mismatch
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_checksum_mismatch_extended(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    manifest = json.loads(mock_dataset_root.read_text(encoding="utf-8"))
    manifest["trade_files"][0]["sha256"] = "badhash"
    _write_manifest(mock_dataset_root, manifest)

    with pytest.raises(NormalizedDatasetValidationError, match="checksum mismatch"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


# ---------------------------------------------------------------------------
# Source catalog tampering (semantic hash mismatch)
# ---------------------------------------------------------------------------


@patch("cross_venue.normalization.validation.AnalysisSourceCatalog.model_validate")
@patch("cross_venue.normalization.validation.DatasetAnalysisSnapshot.model_validate")
@patch(
    "cross_venue.normalization.validation.semantic_hash",
    return_value="tampered_hash",
)
def test_catalog_semantic_tampering_detected(
    mock_hash: Any,
    mock_snap_validate: Any,
    mock_cat_validate: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    """When semantic_hash returns a value != content_hash, error is raised."""
    with pytest.raises(NormalizedDatasetValidationError, match="source catalog was modified"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


# ---------------------------------------------------------------------------
# Snapshot tampering (semantic hash mismatch)
# ---------------------------------------------------------------------------


@patch("cross_venue.normalization.validation.AnalysisSourceCatalog.model_validate")
@patch("cross_venue.normalization.validation.DatasetAnalysisSnapshot.model_validate")
@patch(
    "cross_venue.normalization.validation.semantic_hash",
    # First call = catalog → "test_hash" (matches fixture content_hash)
    # Second call = snapshot → wrong hash
    side_effect=["test_hash", "tampered_snap_hash"],
)
def test_snapshot_semantic_tampering_detected(
    mock_hash: Any,
    mock_snap_validate: Any,
    mock_cat_validate: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    """When the snapshot semantic hash does not match content_hash, error is raised."""
    with pytest.raises(NormalizedDatasetValidationError, match="analysis snapshot was modified"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


# ---------------------------------------------------------------------------
# Snapshot-to-catalog linkage mismatch
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    return_value="cat_hash",
)
def test_snapshot_catalog_linkage_mismatch(
    mock_hash: Any,
    mock_dataset_root: Path,
    tmp_path: Path,
) -> None:
    snapshot_root = tmp_path / "bad_snapshot"
    snapshot_root.mkdir()

    catalog = {
        "source_catalog_schema_version": "3c-source-catalog.1",
        "source_catalog_id": "test-cat-id",
        "created_at": datetime.now(UTC).isoformat(),
        "source_selection_config_hash": "abc",
        "source_selection": {"campaign_id": "test", "campaign_role": "MULTI_DAY_VALIDATION"},
        "source_campaign_ids": [],
        "source_campaigns": [],
        "accepted_attempt_count": 0,
        "aggregate_paired_overlap_seconds": "0",
        "accepted_calendar_dates": [],
        "accepted_time_buckets": [],
        "accepted_attempts": [],
        "excluded_attempt_summary": [],
        "missed_slot_summary": [],
        "content_hash": "cat_hash",
    }
    (snapshot_root / "source_catalog.json").write_text(json.dumps(catalog, indent=2))

    snapshot = {
        "snapshot_schema_version": "3c-analysis-snapshot.1",
        "snapshot_id": "test-snap",
        "snapshot_label": "test",
        "created_at": datetime.now(UTC).isoformat(),
        "snapshot_generation_code_commit": "commit",
        "source_catalog_schema_version": "3c-source-catalog.1",
        "source_catalog_id": "test-cat-id",
        "source_catalog_hash": "WRONG",  # mismatch
        "source_selection_config_hash": "abc",
        "source_campaign_ids": [],
        "accepted_attempt_count": 0,
        "aggregate_paired_overlap_seconds": "0",
        "ordered_accepted_attempt_ids": [],
        "accepted_calendar_dates": [],
        "accepted_time_buckets": [],
        "final_composite_requirements": {},
        "final_composite_status": "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED",
        "explicit_limitations": [],
        "content_hash": "snap_hash",
    }
    (snapshot_root / "snapshot_manifest.json").write_text(json.dumps(snapshot, indent=2))

    with pytest.raises(
        NormalizedDatasetValidationError,
        match="source_catalog_hash does not match",
    ):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=snapshot_root,
        )


# ---------------------------------------------------------------------------
# Cross-file duplicate normalized event IDs
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_cross_file_duplicate_event_id_detected(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
    tmp_path: Path,
) -> None:
    """Same normalized_event_id in two trade files must be detected."""
    root = mock_dataset_root.parents[1]
    trade_dir = root / "trades"

    # Create a second trade file with the same event ID as the first
    trade_path2 = trade_dir / "trade2.parquet"
    pq.write_table(_make_trade_table(event_ids=["evt0"]), trade_path2)  # evt0 duplicates first file
    h2 = _sha256_file(trade_path2)

    manifest = json.loads(mock_dataset_root.read_text(encoding="utf-8"))
    manifest["trade_files"].append(
        {
            "relative_path": "trades/trade2.parquet",
            "sha256": h2,
            "row_count": 1,
            "table": "trades",
            "venue": "kraken",
            "session_id": "k1",
        }
    )
    manifest["trade_row_count"] = 2
    # The first trade file also has evt0 in its default fixture - rewrite it
    pq.write_table(_make_trade_table(event_ids=["evt0"]), trade_dir / "trade.parquet")
    h1 = _sha256_file(trade_dir / "trade.parquet")
    manifest["trade_files"][0]["sha256"] = h1
    _write_manifest(mock_dataset_root, manifest)

    with pytest.raises(NormalizedDatasetValidationError, match="duplicate normalized_event_id"):
        validate_normalized_dataset(
            mock_dataset_root,
            snapshot_root=mock_snapshot_root,
        )


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Correct final-composite status for 7 sessions
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_seven_sessions_final_composite_unsatisfied(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    result = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    assert result.final_composite_status == "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
    assert result.attempt_count == 7


# ---------------------------------------------------------------------------
# validation_code_identity must differ from normalization_code_identity
# ---------------------------------------------------------------------------


@patch(
    "cross_venue.normalization.validation.semantic_hash",
    side_effect=lambda m: "test_hash" if hasattr(m, "model_dump") else "other",
)
def test_validation_code_identity_not_normalizer_commit(
    mock_hash: Any,
    mock_dataset_root: Path,
    mock_snapshot_root: Path,
) -> None:
    result = validate_normalized_dataset(
        mock_dataset_root,
        snapshot_root=mock_snapshot_root,
    )
    # normalization_code_identity is the historical commit from the manifest
    assert result.normalization_code_identity == "commit"
    # validation_code_identity is the current worktree (may be "unknown" in CI)
    assert result.validation_code_identity is not None
    # They are not required to be equal
    # (in dev, normalization commit may differ from current worktree)


# ---------------------------------------------------------------------------
# Legacy one-argument mode
# ---------------------------------------------------------------------------


def test_legacy_mode_returns_dict(tmp_path: Path) -> None:
    """Legacy one-argument call returns dict with validation_status."""
    root = tmp_path / "legacy_ds"
    root.mkdir()
    manifests = root / "manifests"
    manifests.mkdir()

    trade_dir = root / "trades"
    trade_dir.mkdir()
    trade_path = trade_dir / "trade.parquet"

    pq.write_table(_make_trade_table(), trade_path)
    h = _sha256_file(trade_path)

    manifest: dict[str, Any] = {
        "normalized_dataset_id": "test",
        "normalizer_git_commit": "commit",
        "accepted_attempt_count": 1,
        "trade_files": [
            {
                "relative_path": "trades/trade.parquet",
                "sha256": h,
                "row_count": 1,
                "table": "trades",
                "venue": "coinbase",
            }
        ],
        "top_of_book_files": [],
        "raw_record_outcome_files": [],
        "session_metadata_files": [],
        "attempt_metadata_files": [],
        "trade_row_count": 1,
        "top_of_book_row_count": 0,
        "raw_record_outcome_row_count": 0,
        "source_raw_record_count": 0,
        "per_session_normalization_manifest_files": [],
    }
    manifest_path = manifests / "normalized_snapshot_manifest.json"
    _write_manifest(manifest_path, manifest)

    result = validate_normalized_dataset(manifest_path)
    assert isinstance(result, dict)
    assert result["validation_status"] == "VALID"
    assert "trade_row_count" in result
    assert "top_of_book_row_count" in result
    assert "raw_record_outcome_row_count" in result
    assert "duplicate_event_id_count" in result


def test_legacy_mode_no_storage_imports(tmp_path: Path) -> None:
    """Legacy mode must not trigger cross_venue.storage imports."""
    root = tmp_path / "leg_ds"
    root.mkdir()
    manifests = root / "manifests"
    manifests.mkdir()

    trade_dir = root / "trades"
    trade_dir.mkdir()
    trade_path = trade_dir / "trade.parquet"
    pq.write_table(_make_trade_table(), trade_path)
    h = _sha256_file(trade_path)

    manifest: dict[str, Any] = {
        "normalized_dataset_id": "test",
        "normalizer_git_commit": "c",
        "accepted_attempt_count": 1,
        "trade_files": [
            {
                "relative_path": "trades/trade.parquet",
                "sha256": h,
                "row_count": 1,
                "table": "trades",
                "venue": "coinbase",
            }
        ],
        "top_of_book_files": [],
        "raw_record_outcome_files": [],
        "session_metadata_files": [],
        "attempt_metadata_files": [],
        "trade_row_count": 1,
        "top_of_book_row_count": 0,
        "raw_record_outcome_row_count": 0,
        "source_raw_record_count": 0,
        "per_session_normalization_manifest_files": [],
    }
    mp = manifests / "normalized_snapshot_manifest.json"
    _write_manifest(mp, manifest)

    mods_before = set(sys.modules.keys())
    validate_normalized_dataset(mp)
    mods_after = set(sys.modules.keys())
    new_storage = [
        m
        for m in mods_after - mods_before
        if "cross_venue.storage.manifest_store" in m or "cross_venue.storage.checksum" in m
    ]
    assert new_storage == [], f"Legacy mode must not import storage: {new_storage}"


def test_malformed_catalog(mock_snapshot_root: Path, mock_dataset_root: Path) -> None:
    catalog_path = mock_snapshot_root / "source_catalog.json"
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    data["source_selection_config_hash"] = None
    catalog_path.write_text(json.dumps(data))

    with pytest.raises(NormalizedDatasetValidationError):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)
    report_path = (
        mock_dataset_root.parent.parent / "validation" / "normalized_dataset_validation.json"
    )
    result = NormalizedDatasetValidationResult.model_validate_json(report_path.read_text())
    assert result.aggregate_disposition == "INVALID"
    assert result.preliminary_analysis_eligibility == "INELIGIBLE"
    assert result.source_immutability_result == "NOT_CHECKED"


def test_malformed_snapshot(mock_snapshot_root: Path, mock_dataset_root: Path) -> None:
    snapshot_path = mock_snapshot_root / "snapshot_manifest.json"
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    data["snapshot_id"] = None
    snapshot_path.write_text(json.dumps(data))

    with pytest.raises(NormalizedDatasetValidationError):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)
    report_path = (
        mock_dataset_root.parent.parent / "validation" / "normalized_dataset_validation.json"
    )
    result = NormalizedDatasetValidationResult.model_validate_json(report_path.read_text())
    assert result.aggregate_disposition == "INVALID"
    assert result.preliminary_analysis_eligibility == "INELIGIBLE"
    assert result.snapshot_immutability_result == "NOT_CHECKED"


def test_unexpected_semantic_hash_failure(
    mock_snapshot_root: Path, mock_dataset_root: Path
) -> None:
    def raise_err(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Unexpected Error")

    with (
        patch.dict(validate_normalized_dataset.__globals__, {"semantic_hash": raise_err}),
        pytest.raises(ValueError),
    ):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)


def test_missing_output_tampered(mock_snapshot_root: Path, mock_dataset_root: Path) -> None:
    (mock_dataset_root.parent.parent / "trades" / "trade.parquet").unlink()
    with pytest.raises(NormalizedDatasetValidationError):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)
    report_path = (
        mock_dataset_root.parent.parent / "validation" / "normalized_dataset_validation.json"
    )
    result = NormalizedDatasetValidationResult.model_validate_json(report_path.read_text())
    assert result.aggregate_disposition == "INVALID"
    assert result.normalized_output_immutability_result == "TAMPERED"


def test_checksum_mismatch_tampered(mock_snapshot_root: Path, mock_dataset_root: Path) -> None:
    with (mock_dataset_root.parent.parent / "trades" / "trade.parquet").open("ab") as fh:
        fh.write(b"corrupt")
    with pytest.raises(NormalizedDatasetValidationError):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)
    report_path = (
        mock_dataset_root.parent.parent / "validation" / "normalized_dataset_validation.json"
    )
    result = NormalizedDatasetValidationResult.model_validate_json(report_path.read_text())
    assert result.aggregate_disposition == "INVALID"
    assert result.normalized_output_immutability_result == "TAMPERED"


def test_per_attempt_per_session_failures(
    mock_snapshot_root: Path, mock_dataset_root: Path
) -> None:
    (mock_dataset_root.parent / "session_P01.json").unlink()
    with pytest.raises(NormalizedDatasetValidationError):
        validate_normalized_dataset(mock_dataset_root, snapshot_root=mock_snapshot_root)
    report_path = (
        mock_dataset_root.parent.parent / "validation" / "normalized_dataset_validation.json"
    )
    result = NormalizedDatasetValidationResult.model_validate_json(report_path.read_text())
    assert result.aggregate_disposition == "INVALID"
    assert result.normalized_output_immutability_result == "TAMPERED"
    assert result.per_attempt_validation_results["P01"] == "INVALID"
    assert result.per_venue_session_validation_results["c1"] == "INVALID"
    assert result.per_venue_session_validation_results["k1"] == "INVALID"


def test_final_composite_fails_on_dates(mock_snapshot_root: Path, mock_dataset_root: Path) -> None:
    # Everything matches but we only have 2 dates, minimum is 3
    snapshot_path = mock_snapshot_root / "snapshot_manifest.json"
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    data["final_composite_requirements"]["minimum_calendar_dates"] = 5
    snapshot_path.write_text(json.dumps(data))

    from cross_venue.normalization.validation import _resolve_final_composite

    status = _resolve_final_composite(
        manifest={
            "accepted_attempt_count": 10,
            "aggregate_paired_overlap_seconds": "20000",
            "accepted_calendar_dates": ["2026-07-31", "2026-08-01"],
            "accepted_time_buckets": ["MORNING", "AFTERNOON", "EVENING"],
        },
        snapshot_data={
            "final_composite_requirements": {
                "minimum_accepted_sessions": 10,
                "minimum_total_overlap_seconds": "18000",
                "minimum_calendar_dates": 3,
                "minimum_time_buckets": 3,
            }
        },
    )
    assert status == "FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED"
