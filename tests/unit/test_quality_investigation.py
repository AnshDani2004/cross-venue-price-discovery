from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from quality_helpers import (
    coinbase_heartbeat,
    coinbase_ticker,
    coinbase_trade,
    kraken_heartbeat,
    kraken_ticker,
    kraken_trade,
    make_session,
)

from cross_venue.cli import main
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.investigation import investigate_quality_findings
from cross_venue.quality.io import persist_model_json
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.schemas import Exchange


def test_investigate_quality_findings_classifies_quarantine_evidence(tmp_path: Path) -> None:
    paired_path, storage_config, quality_config = _write_paired_report(tmp_path)
    before = paired_path.read_bytes()

    result = investigate_quality_findings(
        paired_path,
        storage_config=storage_config,
        quality_config=quality_config,
    )

    assert paired_path.read_bytes() == before
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert result.recommendations_path.exists()
    assert (
        result.output_root == quality_config.report_root / "investigations" / "investigation-pair"
    )
    assert result.report["summary"]["coinbase_negative_delta"] == "stable offset"
    assert result.report["summary"]["coinbase_continuity"] == "confirmed missing-match evidence"
    assert result.report["summary"]["kraken_negative_delta"] == "stable offset"
    assert result.report["summary"]["kraken_duplicates"] == "classified duplicate groups present"

    coinbase = result.report["sessions"]["coinbase"]
    product_view = coinbase["coinbase_continuity"]["product_wide_view"]
    assert product_view["numeric_discontinuities"] > 0
    assert len(product_view["examples"]) <= 10
    assert (
        coinbase["coinbase_continuity"]["message_type_diagnostic_view"]["ticker"]["classification"]
        == "per-message-type diagnostic jump"
    )
    assert coinbase["coinbase_continuity"]["trade_continuity_view"]["suspicious_intervals"]
    assert coinbase["quote_staleness"]["classifications"]["healthy unchanged quote"] >= 1
    assert (
        coinbase["quote_staleness"]["classifications"]["active trading without quote refresh"] >= 1
    )

    kraken = result.report["sessions"]["kraken"]
    duplicate_classes = {
        group["classification"] for group in kraken["kraken_duplicates"]["groups_by_raw_hash"]
    }
    assert {"heartbeat", "ticker update", "trade update"} <= duplicate_classes
    assert kraken["kraken_duplicates"]["ticker_sequence_analysis_performed"] is False
    assert (
        kraken["kraken_duplicates"]["ticker_duplicate_view"]["ticker_sequence_analysis_performed"]
        is False
    )
    assert kraken["kraken_duplicates"]["trade_duplicate_view"]["duplicate_trade_ids"]
    assert (
        kraken["quote_staleness"]["classifications"]["connection quiet but heartbeat healthy"] >= 1
    )
    assert kraken["quote_staleness"]["classifications"]["active trading without quote refresh"] >= 1
    assert len(kraken["quote_staleness"]["interval_examples"]) <= 10

    recommendations = result.recommendations["recommendations"]
    assert recommendations
    assert all("regression_test_required" in item for item in recommendations)
    assert all("confidence" in item for item in recommendations)


def test_investigate_quality_findings_cli_writes_report(tmp_path: Path, capsys: Any) -> None:
    paired_path, storage_config, quality_config = _write_paired_report(tmp_path)
    storage_path = tmp_path / "storage.toml"
    quality_path = tmp_path / "quality.toml"
    storage_path.write_text(_storage_toml(storage_config), encoding="utf-8")
    quality_path.write_text(_quality_toml(quality_config), encoding="utf-8")

    exit_code = main(
        [
            "investigate-quality-findings",
            "--paired-report",
            str(paired_path),
            "--storage-config",
            str(storage_path),
            "--quality-policy",
            str(quality_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Paired collection ID: investigation-pair" in output
    assert (quality_config.report_root / "investigations" / "investigation-pair").exists()


def _write_paired_report(tmp_path: Path) -> tuple[Path, StorageConfig, DataQualityConfig]:
    coinbase_session, storage_config, quality_config = asyncio.run(
        make_session(
            tmp_path,
            venue=Exchange.COINBASE,
            frames=_coinbase_frames(),
            duration_seconds=20,
            session_id="coinbase-investigation",
        )
    )
    kraken_session, _, _ = asyncio.run(
        make_session(
            tmp_path,
            venue=Exchange.KRAKEN,
            frames=_kraken_frames(),
            duration_seconds=20,
            session_id="kraken-investigation",
        )
    )
    coinbase_report = analyze_session_quality(
        coinbase_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )
    kraken_report = analyze_session_quality(
        kraken_session,
        storage_config=storage_config,
        quality_config=quality_config,
    )
    paired_report = build_paired_quality_report(
        paired_collection_id="investigation-pair",
        requested_duration_seconds=20,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    )
    paired_path = quality_config.report_root / "paired" / "investigation-pair" / "paired.json"
    persist_model_json(paired_path, paired_report)
    return paired_path, storage_config, quality_config


def _coinbase_frames() -> tuple[str, ...]:
    return (
        coinbase_ticker(1, 20, bid="100.00", ask="100.10", trade_id=100),
        coinbase_trade(5, 100, 21),
        coinbase_heartbeat(6, 102, 22),
        coinbase_ticker(10, 23, bid="100.00", ask="100.10", trade_id=102),
        coinbase_trade(11, 103, 24),
        coinbase_heartbeat(12, 103, 25),
        coinbase_trade(13, 104, 26),
        coinbase_ticker(20, 27, bid="101.00", ask="101.10", trade_id=104),
        coinbase_trade(21, 105, 28),
        coinbase_trade(22, 106, 29),
        coinbase_heartbeat(23, 106, 30),
        coinbase_ticker(30, 31, bid="102.00", ask="102.10", trade_id=106),
    )


def _kraken_frames() -> tuple[str, ...]:
    conflicting_trade = (
        '{"channel":"trade","type":"update","data":[{"symbol":"BTC/USD",'
        '"side":"sell","price":"101.00","qty":"0.15","trade_id":200,'
        '"timestamp":"2026-07-30T21:00:25Z"}]}'
    )
    return (
        kraken_ticker(20, bid="100.00", ask="100.10"),
        kraken_heartbeat(),
        kraken_heartbeat(),
        kraken_heartbeat(),
        kraken_ticker(24, bid="101.00", ask="101.10"),
        kraken_trade(200, 25),
        kraken_trade(200, 25),
        conflicting_trade,
        kraken_ticker(28, bid="102.00", ask="102.10"),
        kraken_ticker(28, bid="102.00", ask="102.10"),
        kraken_trade(201, 30),
        kraken_ticker(31, bid="103.00", ask="103.10"),
        kraken_trade(202, 32),
        kraken_ticker(33, bid="104.00", ask="104.10"),
    )


def _storage_toml(config: StorageConfig) -> str:
    return "\n".join(
        [
            f'archive_root = "{config.archive_root}"',
            'archive_format = "jsonl"',
            'archive_schema_version = "0.1.0"',
            "writer_queue_capacity = 100",
            "writer_enqueue_timeout_seconds = 1",
            "flush_every_records = 1",
            "flush_interval_seconds = 1",
            "fsync_on_flush = false",
            "rotate_max_records = 1000",
            "rotate_max_uncompressed_bytes = 1000000",
            "rotate_max_seconds = 900",
            'checksum_algorithm = "sha256"',
            "manifest_checkpoint_every_records = 100",
            "manifest_checkpoint_interval_seconds = 10",
            'partial_file_suffix = ".partial"',
        ]
    )


def _quality_toml(config: DataQualityConfig) -> str:
    return f"""
policy_version = "{config.policy_version}"
effective_date = 2026-07-30
report_root = "{config.report_root}"
validated_manifest_root = "{config.validated_manifest_root}"
default_controlled_duration_seconds = 20
max_controlled_duration_seconds = 300
max_messages_per_venue = 20000

[quality.integrity]
require_archive_validation = true
require_all_checksums = true
allow_partial_shards = false
allow_writer_errors = false
allow_missing_manifest = false
allow_missing_quality_summary = false

[quality.parsing]
max_parse_error_rate = 0.01
max_unsupported_message_rate = 0.5
max_wrong_symbol_messages = 0

[quality.timestamps]
max_nonmonotonic_receipt_events = 0
max_missing_exchange_timestamp_rate = 0.05
stale_quote_threshold_ms = 2000

[quality.coverage]
minimum_session_duration_seconds = 20
minimum_frames_per_venue = 2
minimum_trades_per_venue = 1
minimum_top_of_book_events_per_venue = 1
minimum_cross_venue_overlap_seconds = 10
maximum_start_skew_seconds = 15

[quality.duplicates]
max_exact_raw_duplicate_rate = 0.25
max_duplicate_trade_id_rate = 0.25

[quality.decisions]
quarantine_on_sequence_anomaly = true
quarantine_on_timestamp_outlier = true
quarantine_on_duplicate_warning = true
quarantine_on_stale_quote_warning = true
"""
