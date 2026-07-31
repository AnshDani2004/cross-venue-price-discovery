import asyncio
from pathlib import Path

import pytest
from quality_helpers import make_session

from cross_venue.cli import main
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.collection import PairedCollectionResult
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.schemas import Exchange


@pytest.mark.asyncio
async def test_analyze_session_quality_cli_writes_report(tmp_path: Path, capsys) -> None:
    session_path, storage_config, quality_config = await make_session(tmp_path)
    storage_path = tmp_path / "storage.toml"
    quality_path = tmp_path / "quality.toml"
    storage_path.write_text(_storage_toml(storage_config), encoding="utf-8")
    quality_path.write_text(_quality_toml(quality_config), encoding="utf-8")

    exit_code = main(
        [
            "analyze-session-quality",
            "--session-path",
            str(session_path),
            "--storage-config",
            str(storage_path),
            "--quality-policy",
            str(quality_path),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Disposition: ACCEPTED" in output
    assert next(quality_config.report_root.rglob("*session_quality_report.json")).exists()


def test_collect_paired_quality_cli_uses_fake_runner(tmp_path: Path, capsys) -> None:
    coinbase_session, storage_config, quality_config = asyncio.run(
        make_session(
            tmp_path,
            venue=Exchange.COINBASE,
            session_id="coinbase-session",
        )
    )
    kraken_session, _, _ = asyncio.run(
        make_session(
            tmp_path,
            venue=Exchange.KRAKEN,
            session_id="kraken-session",
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
        paired_collection_id="fake-pair",
        requested_duration_seconds=2,
        start_skew_seconds=0,
        coinbase_report=coinbase_report,
        kraken_report=kraken_report,
        quality_config=quality_config,
    )

    async def fake_runner(
        _storage_config: StorageConfig,
        _quality_config: DataQualityConfig,
        _duration_seconds: float,
        _max_messages_per_venue: int,
    ) -> PairedCollectionResult:
        return PairedCollectionResult(
            paired_report=paired_report,
            coinbase_summary=object(),  # type: ignore[arg-type]
            kraken_summary=object(),  # type: ignore[arg-type]
            coinbase_report_path=tmp_path / "coinbase.json",
            kraken_report_path=tmp_path / "kraken.json",
            paired_report_path=tmp_path / "paired.json",
        )

    exit_code = main(
        ["collect-paired-quality", "--duration-seconds", "2", "--max-messages-per-venue", "2"],
        paired_quality_runner=fake_runner,
    )

    assert exit_code == 0
    assert "Paired disposition: ACCEPTED" in capsys.readouterr().out


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
default_controlled_duration_seconds = 2
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
minimum_session_duration_seconds = 2
minimum_frames_per_venue = 2
minimum_trades_per_venue = 1
minimum_top_of_book_events_per_venue = 1
minimum_cross_venue_overlap_seconds = 1
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
