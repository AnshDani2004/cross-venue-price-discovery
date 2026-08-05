from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from quality_helpers import coinbase_ticker, coinbase_trade, make_session

from cross_venue.config import (
    NormalizationConfig,
    load_data_quality_config,
    load_normalization_config,
    load_storage_config,
)
from cross_venue.normalization.catalog import build_normalized_catalog
from cross_venue.normalization.decimal_utils import validate_decimal
from cross_venue.normalization.determinism import verify_normalization_determinism
from cross_venue.normalization.exceptions import DecimalRepresentationError, ValidatedManifestError
from cross_venue.normalization.identifiers import stable_event_id
from cross_venue.normalization.normalizer import (
    load_analysis_snapshot_normalization_inputs,
    normalize_dataset,
)
from cross_venue.normalization.parquet_writer import read_rows
from cross_venue.normalization.validation import validate_normalized_dataset
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.io import model_sha256, persist_model_json, portable_relative_path
from cross_venue.quality.models import (
    PairedQualityReport,
    QualityDisposition,
    ValidatedDatasetManifest,
)
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import build_validated_dataset_manifest
from cross_venue.research.source_snapshot import (
    AcceptedSourceAttemptEntry,
    AnalysisSourceCatalog,
    DatasetAnalysisSnapshot,
    SourceCampaignEntry,
    SourceSelectionConfig,
    build_snapshot_manifest,
    semantic_hash,
)
from cross_venue.schemas import Exchange
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json


def test_normalization_config_loads_defaults_and_rejects_bad_values(tmp_path: Path) -> None:
    config = load_normalization_config(Path("configs/normalization.toml"))

    assert config.normalization_schema_version == "3a.1"
    assert config.decimal_precision == 38
    assert config.decimal_scale == 18

    bad = tmp_path / "bad.toml"
    bad.write_text(
        Path("configs/normalization.toml").read_text(encoding="utf-8") + "\nunknown = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_normalization_config(bad)

    bad.write_text(
        Path("configs/normalization.toml")
        .read_text(encoding="utf-8")
        .replace('parquet_compression = "zstd"', 'parquet_compression = "gzip"'),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_normalization_config(bad)


def test_stable_event_id_is_path_and_time_independent() -> None:
    first = stable_event_id(["3a.1", "manifest", "coinbase", "session", "raw/part", 1, "trade", 0])
    second = stable_event_id(["3a.1", "manifest", "coinbase", "session", "raw/part", 1, "trade", 0])
    child = stable_event_id(["3a.1", "manifest", "coinbase", "session", "raw/part", 1, "trade", 1])
    ambiguous = stable_event_id(["ab", "c"])
    unambiguous = stable_event_id(["a", "bc"])

    assert first == second
    assert first != child
    assert ambiguous != unambiguous


def test_decimal_boundary_rejects_float_and_overflow() -> None:
    assert validate_decimal(
        Decimal("100.010000000000000000"),
        field_name="price",
        precision=38,
        scale=18,
        lineage="row",
    ) == Decimal("100.010000000000000000")

    with pytest.raises(DecimalRepresentationError, match="float"):
        validate_decimal(1.0, field_name="price", precision=38, scale=18, lineage="row")  # type: ignore[arg-type]
    with pytest.raises(DecimalRepresentationError, match="scale"):
        validate_decimal(
            Decimal("0.0000000000000000001"),
            field_name="qty",
            precision=38,
            scale=18,
            lineage="row",
        )


def test_synthetic_normalization_reconciles_and_builds_catalog(tmp_path: Path) -> None:
    manifest_path, storage_config, quality_config, normalization_config = asyncio.run(
        _accepted_manifest_fixture(tmp_path)
    )

    result = normalize_dataset(
        manifest_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )

    assert not isinstance(result, dict)
    assert result.manifest["reconciliation_status"] == "PASSED"
    assert (
        result.manifest["raw_record_outcome_row_count"]
        == result.manifest["source_raw_record_count"]
    )
    validation = validate_normalized_dataset(result.normalization_manifest_path)
    assert validation["validation_status"] == "VALID"
    catalog = build_normalized_catalog(result.normalization_manifest_path)
    assert catalog["catalog_status"] == "BUILT"


def test_analysis_snapshot_normalization_preserves_snapshot_lineage(tmp_path: Path) -> None:
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path)
    )

    result = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )

    assert not isinstance(result, dict)
    manifest = result.manifest
    assert manifest["source_analysis_snapshot_id"].startswith("analysis-snapshot-1-session")
    assert manifest["normalized_dataset_id"].startswith("normalized-analysis-snapshot-1-session")
    assert manifest["source_catalog_id"].startswith("analysis-source-catalog-fixture")
    assert manifest["accepted_attempt_count"] == 1
    assert manifest["venue_session_count"] == 2
    assert len(manifest["per_session_normalization_manifest_files"]) == 1
    trade_rows = _read_manifest_rows(result.dataset_root, manifest, "trade_files")
    bbo_rows = _read_manifest_rows(result.dataset_root, manifest, "top_of_book_files")
    assert {row["dataset_snapshot_id"] for row in trade_rows + bbo_rows} == {
        manifest["source_analysis_snapshot_id"]
    }
    assert {row["source_catalog_id"] for row in trade_rows + bbo_rows} == {
        manifest["source_catalog_id"]
    }
    assert {row["campaign_attempt_id"] for row in trade_rows + bbo_rows} == {
        "fixture-campaign-P01-001"
    }


def test_analysis_snapshot_rejects_manifest_membership_mismatch(tmp_path: Path) -> None:
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path)
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["ordered_accepted_attempt_ids"] = ["btc-usd-coinbase-kraken-2026-07-31-v1-P08-001"]
    changed = DatasetAnalysisSnapshot.model_validate(payload)
    changed = changed.model_copy(update={"content_hash": semantic_hash(changed)})
    atomic_write_json(snapshot_path, changed.model_dump(mode="json"))

    with pytest.raises(ValidatedManifestError, match="membership"):
        load_analysis_snapshot_normalization_inputs(
            snapshot_path,
            storage_config=storage_config,
            quality_config=quality_config,
            normalization_config=normalization_config,
        )


def test_normalization_noop_reuses_existing_snapshot_output(tmp_path: Path) -> None:
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path)
    )

    first = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )
    assert not isinstance(first, dict)
    manifest_mtime = first.normalization_manifest_path.stat().st_mtime_ns
    second = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )

    assert not isinstance(second, dict)
    assert second.reused_existing is True
    assert (
        second.manifest["normalization_manifest_id"] == first.manifest["normalization_manifest_id"]
    )
    assert second.normalization_manifest_path.stat().st_mtime_ns == manifest_mtime


def test_changed_normalization_config_produces_new_identity(tmp_path: Path) -> None:
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path)
    )

    first = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )
    changed_config = normalization_config.model_copy(update={"parquet_row_group_size": 10})
    second = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=changed_config,
        require_clean=False,
    )

    assert not isinstance(first, dict)
    assert not isinstance(second, dict)
    assert second.manifest["normalized_dataset_id"] != first.manifest["normalized_dataset_id"]


def test_validation_detects_output_hash_mismatch(tmp_path: Path) -> None:
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path)
    )
    result = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )
    assert not isinstance(result, dict)
    manifest = result.manifest
    first_trade_file = result.dataset_root / manifest["trade_files"][0]["relative_path"]
    first_trade_file.write_bytes(first_trade_file.read_bytes() + b"corruption")

    with pytest.raises(Exception, match="checksum mismatch"):
        validate_normalized_dataset(result.normalization_manifest_path)


def test_bbo_derived_fields_and_duplicate_classification(tmp_path: Path) -> None:
    frames = (
        coinbase_trade(1, 1, 0),
        coinbase_ticker(2, 1, bid="100.00", ask="100.00"),
        coinbase_ticker(2, 1, bid="100.00", ask="100.00"),
        coinbase_ticker(3, 2, bid="100.20", ask="100.10"),
        coinbase_trade(4, 4, 3),
    )
    snapshot_path, storage_config, quality_config, normalization_config = asyncio.run(
        _analysis_snapshot_fixture(tmp_path, coinbase_frames=frames, force_accept=True)
    )
    result = normalize_dataset(
        snapshot_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
        require_clean=False,
    )
    assert not isinstance(result, dict)
    bbo_rows = [
        row
        for row in _read_manifest_rows(result.dataset_root, result.manifest, "top_of_book_files")
        if row["venue"] == "coinbase"
    ]

    assert any(row["locked_market_indicator"] for row in bbo_rows)
    assert any(row["crossed_market_indicator"] for row in bbo_rows)
    assert any(row["duplicate_classification"] == "EXACT_RAW_FRAME_DUPLICATE" for row in bbo_rows)
    assert bbo_rows[0]["midprice"] == Decimal("100.000000000000000000")
    assert bbo_rows[0]["spread"] == Decimal("0E-18")


def test_synthetic_normalization_determinism(tmp_path: Path) -> None:
    manifest_path, storage_config, quality_config, normalization_config = asyncio.run(
        _accepted_manifest_fixture(tmp_path)
    )

    result = verify_normalization_determinism(
        manifest_path,
        storage_config=storage_config,
        quality_config=quality_config,
        normalization_config=normalization_config,
    )

    assert result["determinism_status"] == "PASSED"
    assert all(result["comparisons"].values())


@pytest.mark.local_validated_data
def test_local_validated_manifest_dry_run_smoke() -> None:
    if os.getenv("CROSS_VENUE_ENABLE_LOCAL_VALIDATED_DATA") != "1":
        pytest.skip("local validated-data smoke test is opt-in")
    manifest_path = Path(
        os.getenv(
            "CROSS_VENUE_VALIDATED_MANIFEST",
            ("data/validated/manifests/validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd.json"),
        )
    )
    if not manifest_path.exists():
        pytest.skip(f"local validated manifest not found: {manifest_path}")

    plan = normalize_dataset(
        manifest_path,
        storage_config=load_storage_config(Path("configs/storage.toml")),
        quality_config=load_data_quality_config(Path("configs/data_quality.toml")),
        normalization_config=load_normalization_config(Path("configs/normalization.toml")),
        dry_run=True,
    )

    assert isinstance(plan, dict)
    assert plan["source_raw_record_count"] > 0


async def _accepted_manifest_fixture(
    tmp_path: Path,
    *,
    coinbase_frames: tuple[str, ...] | None = None,
    force_accept: bool = False,
) -> tuple[Path, object, object, NormalizationConfig]:
    coinbase_session, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-normalization",
        frames=coinbase_frames,
    )
    kraken_session, _, _ = await make_session(
        tmp_path,
        venue=Exchange.KRAKEN,
        session_id="kraken-normalization",
    )
    quality_config = quality_config.model_copy(update={"policy_version": "2d.2"})
    coinbase_path = (
        quality_config.report_root / "paired" / "normalization-fixture" / "coinbase.json"
    )
    kraken_path = quality_config.report_root / "paired" / "normalization-fixture" / "kraken.json"
    paired_path = quality_config.report_root / "paired" / "normalization-fixture" / "paired.json"
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=quality_config,
        report_path=coinbase_path,
    ).model_copy(
        update={
            "report_relative_path": portable_relative_path(
                quality_config.report_root, coinbase_path
            )
        }
    )
    if force_accept:
        coinbase_report = coinbase_report.model_copy(
            update={"disposition": QualityDisposition.ACCEPTED, "disposition_reasons": ()}
        )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=quality_config,
        report_path=kraken_path,
    ).model_copy(
        update={
            "report_relative_path": portable_relative_path(quality_config.report_root, kraken_path)
        }
    )
    persist_model_json(coinbase_path, coinbase_report)
    persist_model_json(kraken_path, kraken_report)
    paired_report = build_paired_quality_report(
        paired_collection_id="normalization-fixture",
        requested_duration_seconds=2,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    ).model_copy(
        update={
            "paired_report_relative_path": portable_relative_path(
                quality_config.report_root, paired_path
            )
        }
    )
    if force_accept:
        paired_report = paired_report.model_copy(
            update={
                "coinbase_report": coinbase_report,
                "kraken_report": kraken_report,
                "disposition": QualityDisposition.ACCEPTED,
                "disposition_reasons": (),
            }
        )
    persist_model_json(paired_path, paired_report)
    manifest = build_validated_dataset_manifest(paired_report, quality_config=quality_config)
    manifest_path = quality_config.validated_manifest_root / f"{manifest.dataset_manifest_id}.json"
    persist_model_json(manifest_path, manifest)
    normalization_config = NormalizationConfig(
        normalization_schema_version="3a.1",
        output_root=tmp_path / "normalized",
        parquet_compression="zstd",
        parquet_compression_level=6,
        parquet_row_group_size=50_000,
        decimal_precision=38,
        decimal_scale=18,
        timestamp_unit="ns",
        preserve_raw_duplicates=True,
        write_raw_record_outcomes=True,
        write_duckdb_catalog=True,
        require_validated_manifest=True,
        require_quality_policy_version="2d.2",
        require_clean_working_tree_for_final_run=True,
    )
    return manifest_path, storage_config, quality_config, normalization_config


async def _analysis_snapshot_fixture(
    tmp_path: Path,
    *,
    coinbase_frames: tuple[str, ...] | None = None,
    force_accept: bool = False,
) -> tuple[Path, object, object, NormalizationConfig]:
    (
        manifest_path,
        storage_config,
        quality_config,
        normalization_config,
    ) = await _accepted_manifest_fixture(
        tmp_path,
        coinbase_frames=coinbase_frames,
        force_accept=force_accept,
    )
    validated = ValidatedDatasetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    paired_report_path = quality_config.report_root / validated.cross_venue_overlap_report_path
    paired_report = PairedQualityReport.model_validate_json(
        paired_report_path.read_text(encoding="utf-8")
    )
    source_registry_sha = "a" * 64
    source_ledger_sha = "b" * 64
    source_ledger_terminal_hash = "c" * 64
    attempt = AcceptedSourceAttemptEntry(
        campaign_id="fixture-campaign",
        campaign_role="MULTI_DAY_VALIDATION",
        campaign_attempt_id="fixture-campaign-P01-001",
        slot_id="P01",
        slot_type="PLANNED",
        time_bucket="EVENING",
        planned_start_utc=validated.start_time,
        planned_start_local="2026-07-30 16:00:00 CDT",
        actual_started_at=validated.start_time,
        actual_completed_at=validated.end_time,
        paired_overlap_seconds=Decimal(str(validated.overlap_duration_seconds)),
        paired_collection_id=validated.paired_collection_ids[0],
        validated_pair_manifest_id=validated.dataset_manifest_id,
        validated_pair_manifest_relative_path=manifest_path.relative_to(
            quality_config.validated_manifest_root
        ).as_posix(),
        validated_pair_manifest_sha256=sha256_file(manifest_path),
        coinbase_session_id=paired_report.coinbase_report.session_id,
        kraken_session_id=paired_report.kraken_report.session_id,
        source_session_manifest_hashes=dict(validated.raw_manifest_hashes),
        session_quality_report_hashes=dict(validated.session_quality_report_hashes),
        paired_quality_report_hash=model_sha256(paired_report),
        source_raw_shard_checksums={
            paired_report.coinbase_report.session_id: dict(
                paired_report.coinbase_report.input_shard_checksums
            ),
            paired_report.kraken_report.session_id: dict(
                paired_report.kraken_report.input_shard_checksums
            ),
        },
        attempt_runtime_git_commit="98e28b2e026124434fc1bec1d442d7b9bcbc8530",
        quality_code_git_commit=paired_report.quality_code_git_commit,
        quality_policy_version=validated.quality_policy_version,
        inclusion_status="INCLUDED",
        attempt_status="ACCEPTED",
        paired_disposition="ACCEPTED",
        coinbase_disposition="ACCEPTED",
        kraken_disposition="ACCEPTED",
        analysis_calendar_date="2026-07-30",
        source_registry_sha256=source_registry_sha,
        source_ledger_sha256=source_ledger_sha,
        source_ledger_terminal_event_hash=source_ledger_terminal_hash,
        validated_pair_manifest_content_hash=validated.content_sha256,
        raw_session_relative_paths=tuple(validated.raw_session_relative_paths),
        session_quality_report_paths=tuple(validated.session_quality_report_paths),
        paired_quality_report_relative_path=validated.cross_venue_overlap_report_path,
    )
    selection = SourceSelectionConfig(campaign_ids=("fixture-campaign",))
    campaign = SourceCampaignEntry(
        campaign_id="fixture-campaign",
        campaign_role="MULTI_DAY_VALIDATION",
        campaign_schema_version="fixture",
        campaign_status="ACTIVE",
        completion_status="INCOMPLETE",
        instrument="BTC-USD",
        venues=(Exchange.COINBASE, Exchange.KRAKEN),
        runtime_git_commit="98e28b2e026124434fc1bec1d442d7b9bcbc8530",
        quality_policy_version=validated.quality_policy_version,
        quality_policy_sha256="d" * 64,
        campaign_config_path="configs/campaigns/fixture.toml",
        campaign_config_sha256="e" * 64,
        source_registry_sha256=source_registry_sha,
        source_ledger_sha256=source_ledger_sha,
        source_ledger_terminal_event_hash=source_ledger_terminal_hash,
        accepted_attempt_count=1,
        accepted_overlap_seconds=Decimal(str(validated.overlap_duration_seconds)),
        accepted_calendar_dates=("2026-07-30",),
        accepted_time_buckets=("EVENING",),
        missed_slot_count=0,
        quarantined_attempt_count=0,
        rejected_attempt_count=0,
        failed_attempt_count=0,
    )
    catalog = AnalysisSourceCatalog(
        source_catalog_schema_version="3c-source-catalog.1",
        source_catalog_id="analysis-source-catalog-fixture",
        created_at=validated.created_at,
        source_selection_config_hash=semantic_hash(selection),
        source_selection=selection,
        source_campaign_ids=("fixture-campaign",),
        source_campaigns=(campaign,),
        accepted_attempt_count=1,
        aggregate_paired_overlap_seconds=Decimal(str(validated.overlap_duration_seconds)),
        accepted_calendar_dates=("2026-07-30",),
        accepted_time_buckets=("EVENING",),
        accepted_attempts=(attempt,),
        excluded_attempt_summary=(
            {
                "campaign_id": "fixture-campaign",
                "campaign_attempt_id": "fixture-campaign-P08-001",
                "attempt_status": "QUARANTINED",
                "inclusion_status": "EXCLUDED",
                "exclusion_reason": "fixture quarantine",
            },
        ),
        missed_slot_summary=(),
    )
    catalog = catalog.model_copy(update={"content_hash": semantic_hash(catalog)})
    snapshot = build_snapshot_manifest(catalog, snapshot_label="fixture-analysis-snapshot")
    snapshot_root = tmp_path / "analysis" / "snapshots" / snapshot.snapshot_id
    atomic_write_json(snapshot_root / "source_catalog.json", catalog.model_dump(mode="json"))
    atomic_write_json(snapshot_root / "snapshot_manifest.json", snapshot.model_dump(mode="json"))
    return (
        snapshot_root / "snapshot_manifest.json",
        storage_config,
        quality_config,
        normalization_config,
    )


def _read_manifest_rows(
    dataset_root: Path,
    manifest: dict[str, Any],
    manifest_key: str,
) -> list[dict[str, Any]]:
    return [
        row
        for entry in manifest[manifest_key]
        for row in read_rows(dataset_root / entry["relative_path"])
    ]
