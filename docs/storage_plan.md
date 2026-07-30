# Storage Plan

Review date: 2026-07-30.

This plan defines local research storage before collectors are implemented.

## Directory Layout

```text
data/raw/venue=<venue>/channel=<channel>/date=<YYYY-MM-DD>/session=<session_id>/
data/normalized/event_type=<event_type>/venue=<venue>/date=<YYYY-MM-DD>/
data/features/dataset=<dataset_name>/version=<schema_version>/
data/manifests/date=<YYYY-MM-DD>/
```

All generated data directories remain ignored by Git.

## File Formats

| Layer | Format | Compression | Notes |
| --- | --- | --- | --- |
| Raw payloads | JSON Lines | gzip or zstd | Preserve one venue message per line plus receipt metadata. |
| Normalized events | Parquet | zstd | Typed columns matching `docs/data_dictionary.md`. |
| Features and labels | Parquet | zstd | Versioned by schema and feature definition. |
| Manifests | JSON or TOML | none | Human-reviewable checksums and collection summaries. |

## Integrity Controls

- Compute SHA-256 checksums for raw and normalized files.
- Store row counts and min/max timestamps per partition.
- Store config checksums next to each session manifest.
- Validate that normalized files trace back to raw payload references.
- Never overwrite a raw file in place; create a new session or rotation file.

## Partitioning Rules

Partition by venue, channel, event type, date, and session ID. Avoid partitioning by
high-cardinality fields such as trade ID or message sequence.

## Promotion Rules

Raw data can be promoted to normalized data only when:

- Schema validation passes.
- Required timestamp fields are present and monotonic.
- Venue-specific sequence/checksum checks pass or the interval is explicitly flagged.
- Crossed or empty top-of-book events are rejected or quarantined.
- Manifest checksums are available.
