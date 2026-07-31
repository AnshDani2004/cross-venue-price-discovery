from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from quality_helpers import make_session

from cross_venue.config import (
    NormalizationConfig,
    load_data_quality_config,
    load_normalization_config,
    load_storage_config,
)
from cross_venue.normalization.catalog import build_normalized_catalog
from cross_venue.normalization.decimal_utils import validate_decimal
from cross_venue.normalization.determinism import verify_normalization_determinism
from cross_venue.normalization.exceptions import DecimalRepresentationError
from cross_venue.normalization.identifiers import stable_event_id
from cross_venue.normalization.normalizer import normalize_dataset
from cross_venue.normalization.validation import validate_normalized_dataset
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.io import persist_model_json, portable_relative_path
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import build_validated_dataset_manifest
from cross_venue.schemas import Exchange


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
) -> tuple[Path, object, object, NormalizationConfig]:
    coinbase_session, storage_config, quality_config = await make_session(
        tmp_path,
        venue=Exchange.COINBASE,
        session_id="coinbase-normalization",
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
