# Storage Plan

Review date: 2026-07-31.

This plan defines local research storage after Phase 2C raw archival. Phase 2C persists
exact public WebSocket frames, per-session manifests, quality summaries, and checksums.
It still does not write normalized datasets, features, labels, model artifacts, or
trading outputs.

## Directory Layout

```text
data/raw/venue=<venue>/instrument=<canonical_instrument>/date=<YYYY-MM-DD>/session=<session_id>/
  raw/part-00000.jsonl
  raw/part-00000.jsonl.sha256
  manifest/session_manifest.json
  quality/quality_summary.json
data/normalized/event_type=<event_type>/venue=<venue>/date=<YYYY-MM-DD>/
data/features/dataset=<dataset_name>/version=<schema_version>/
data/manifests/date=<YYYY-MM-DD>/
```

All generated data directories remain ignored by Git.

## File Formats

| Layer | Format | Compression | Notes |
| --- | --- | --- | --- |
| Raw payloads | JSON Lines | none in Phase 2C | Preserve one exact text frame or Base64 binary frame per line plus receipt metadata. |
| Normalized events | Parquet | zstd | Typed columns matching `docs/data_dictionary.md`. |
| Features and labels | Parquet | zstd | Versioned by schema and feature definition. |
| Manifests | JSON or TOML | none | Human-reviewable checksums and collection summaries. |

## Integrity Controls

- Compute SHA-256 checksums for finalized raw shards.
- Store row counts and min/max timestamps per partition.
- Store session counters, shard metadata, and checksum status in each session manifest.
- Validate that normalized files trace back to raw payload references.
- Never overwrite a raw file in place; create a new session or rotation file.
- Archive exact raw frames before JSON decoding; never reconstruct raw archives from
  decoded dictionaries.
- Keep `.partial` files recoverable and visible if a session is interrupted.

## Partitioning Rules

Partition raw archives by venue, canonical instrument, UTC date, and session ID. Avoid
partitioning by high-cardinality fields such as trade ID or message sequence.

## Promotion Rules

Raw data can be promoted to normalized data only when:

- Schema validation passes.
- Required timestamp fields are present and monotonic.
- Venue-specific sequence/checksum checks pass or the interval is explicitly flagged.
- Crossed or empty top-of-book events are rejected or quarantined.
- Manifest checksums are available.

Phase 2D quality reports are separate artifacts under ignored `data/quality`. Validated
dataset manifests live under ignored `data/validated/manifests`, reference accepted raw
sessions and quality report hashes, and do not move, rewrite, deduplicate, interpolate,
or transform raw frames.

## Phase 3A Normalized Layout

Phase 3A writes ignored deterministic outputs under:

```text
data/normalized/dataset=<normalized_dataset_id>/
  trades/venue=<venue>/date=<YYYY-MM-DD>/session=<session-id>/part-00000.parquet
  top_of_book/venue=<venue>/date=<YYYY-MM-DD>/session=<session-id>/part-00000.parquet
  raw_record_outcomes/venue=<venue>/date=<YYYY-MM-DD>/session=<session-id>/part-00000.parquet
  manifest/normalization_manifest.json
  validation/validation_report.json
  catalog/normalized.duckdb
```

Parquet files use explicit PyArrow schemas, zstd compression, deterministic file names,
UTC timestamps, and `decimal128(38,18)` financial values. Finalization uses a
`.partial` dataset directory and publishes only after reconciliation, output checksums,
semantic hashes, and source hash reverification pass.

DuckDB catalogs are local ignored inspection catalogs that expose views over Parquet
files. They are not authoritative storage and can be rebuilt from the normalization
manifest.
