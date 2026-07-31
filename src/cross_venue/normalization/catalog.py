"""DuckDB catalog views for normalized datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from cross_venue.normalization.exceptions import CatalogBuildError


def build_normalized_catalog(normalization_manifest_path: Path) -> dict[str, Any]:
    """Build a local DuckDB catalog with read-only views over Parquet outputs."""

    manifest_path = normalization_manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_root = manifest_path.parents[1]
    catalog_path = dataset_root / "catalog" / "normalized.duckdb"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with duckdb.connect(str(catalog_path)) as connection:
            _create_scan_view(connection, "trades", dataset_root, manifest["trade_files"])
            _create_scan_view(
                connection,
                "top_of_book",
                dataset_root,
                manifest["top_of_book_files"],
            )
            _create_scan_view(
                connection,
                "raw_record_outcomes",
                dataset_root,
                manifest["raw_record_outcome_files"],
            )
            connection.execute(
                """
                CREATE OR REPLACE VIEW normalized_event_stream AS
                SELECT normalized_event_id, venue, session_id, connection_epoch,
                       'trade' AS event_type, local_receipt_ts, exchange_ts,
                       source_raw_record_index, normalized_child_index,
                       price, quantity, NULL::DECIMAL(38,18) AS bid_price,
                       NULL::DECIMAL(38,18) AS ask_price
                FROM trades
                UNION ALL
                SELECT normalized_event_id, venue, session_id, connection_epoch,
                       'top_of_book' AS event_type, local_receipt_ts, exchange_ts,
                       source_raw_record_index, normalized_child_index,
                       NULL::DECIMAL(38,18) AS price, NULL::DECIMAL(38,18) AS quantity,
                       bid_price, ask_price
                FROM top_of_book
                """
            )
            connection.execute(
                """
                CREATE OR REPLACE VIEW session_summary AS
                SELECT venue, session_id, count(*) AS raw_record_count,
                       min(local_receipt_ts) AS first_local_receipt_ts,
                       max(local_receipt_ts) AS last_local_receipt_ts,
                       sum(normalized_trade_row_count) AS trade_count,
                       sum(normalized_bbo_row_count) AS top_of_book_count,
                       sum(CASE WHEN parse_status = 'ERROR' THEN 1 ELSE 0 END)
                         AS parse_error_count,
                       sum(CASE WHEN is_raw_frame_duplicate THEN 1 ELSE 0 END)
                         AS duplicate_raw_frame_count
                FROM raw_record_outcomes
                GROUP BY venue, session_id
                """
            )
            connection.execute(
                """
                CREATE OR REPLACE VIEW venue_summary AS
                SELECT venue,
                       count(*) AS raw_record_count,
                       sum(normalized_trade_row_count) AS trade_count,
                       sum(normalized_bbo_row_count) AS top_of_book_count
                FROM raw_record_outcomes
                GROUP BY venue
                """
            )
            counts = {
                "trades": _count(connection, "trades"),
                "top_of_book": _count(connection, "top_of_book"),
                "raw_record_outcomes": _count(connection, "raw_record_outcomes"),
                "normalized_event_stream": _count(connection, "normalized_event_stream"),
            }
    except Exception as exc:
        raise CatalogBuildError(str(exc)) from exc
    return {
        "catalog_path": str(catalog_path),
        "catalog_status": "BUILT",
        "view_counts": counts,
    }


def _create_scan_view(
    connection: duckdb.DuckDBPyConnection,
    view_name: str,
    dataset_root: Path,
    files: list[dict[str, Any]],
) -> None:
    paths = [str(dataset_root / entry["relative_path"]) for entry in files]
    if not paths:
        connection.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT NULL WHERE FALSE")
        return
    literal_paths = ", ".join(_sql_string(path) for path in paths)
    connection.execute(
        f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM parquet_scan([{literal_paths}])"
    )


def _count(connection: duckdb.DuckDBPyConnection, view_name: str) -> int:
    row = connection.execute(f"SELECT count(*) FROM {view_name}").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
