"""Deterministic PyArrow Parquet writing helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cross_venue.config import NormalizationConfig
from cross_venue.storage.checksum import sha256_file


def write_parquet(
    path: Path,
    rows: Sequence[dict[str, Any]],
    *,
    schema: pa.Schema,
    config: NormalizationConfig,
) -> dict[str, Any]:
    """Write rows with an explicit schema and return file metadata."""

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(list(rows), schema=schema)
    compression = None if config.parquet_compression == "none" else config.parquet_compression
    pq.write_table(
        table,
        path,
        row_group_size=config.parquet_row_group_size,
        compression=compression,
        compression_level=config.parquet_compression_level,
        use_dictionary=config.dictionary_encoding,
        write_statistics=config.write_statistics,
        data_page_version=config.data_page_version,
        use_compliant_nested_type=config.use_compliant_nested_type,
    )
    return {
        "row_count": table.num_rows,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Read Parquet rows as dictionaries."""

    rows: list[dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows
