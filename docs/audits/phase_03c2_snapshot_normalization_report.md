# Phase 3C.2 Snapshot Normalization Report

## Objective

Phase 3C.2 builds the canonical normalization pipeline for the immutable seven-session
analysis snapshot `analysis-snapshot-7-session-v1-5f796ab67a5c801c` from source catalog
`analysis-source-catalog-3b3ad1fa97ef60a1`.

The source collection root was `/Users/ansh/Developer/cross-venue-price-discovery`.
The analysis output root was `data/analysis`. The collection checkout was treated as
read-only and remained pinned to `98e28b2e026124434fc1bec1d442d7b9bcbc8530`.

## Implementation Findings

The existing deterministic normalizer already provided raw JSONL replay, Coinbase and
Kraken offline parsers, validated-pair manifest verification, raw shard checksums,
explicit Parquet schemas, deterministic event IDs, semantic hashes, validation, DuckDB
catalog views, and determinism checks.

Phase 3C.2 adds an analysis-snapshot input adapter, snapshot/catalog lineage columns,
session and attempt metadata tables, per-session normalization manifests, aggregate
normalized-snapshot manifests, no-op reuse, and module CLI execution.

The shared top-of-book event model previously rejected locked/crossed quotes before
normalization. Those observed states are now preserved and classified in canonical BBO
rows.

## Canonical Tables

Trade rows retain snapshot/catalog IDs, campaign/attempt/slot lineage, validated-pair
hashes, raw shard and record identity, venue/session identity, UTC receipt and exchange
timestamps, exact Decimal price/quantity/notional values, source trade IDs, side
interpretation status, duplicate classification, parser version, runtime commit, quality
code commit, and quality policy version.

BBO rows retain the same major lineage fields and add exact Decimal bid/ask prices and
sizes, midprice, spread, relative spread, spread basis points, quoted depth, bid/ask
imbalance, locked-market and crossed-market indicators, and quote-change classification.

Session metadata has one row per venue session. Attempt metadata has one row per accepted
paired attempt.

## Precision And Time

Raw prices and quantities remain `Decimal` values and are stored as Arrow
`decimal128(38,18)`. Derived Decimal fields are quantized to scale 18 with
`ROUND_HALF_EVEN`; raw prices and quantities are not rounded for presentation.

Receipt and exchange timestamps are stored as timezone-aware UTC nanosecond timestamps.
Receipt time is preserved separately from exchange time and is not interpreted as
one-way latency.

## IDs And Reuse

Event IDs use stable JSON component lists containing schema version, snapshot/campaign or
validated-pair identity, venue session, source shard, source record index, event type,
and child ordinal. They do not include absolute paths, usernames, wall-clock processing
time, random UUIDs, or Python hash values.

Session manifest IDs use accepted-attempt identity, validated-pair hash, source session
manifest hashes, raw shard hashes, schema version, config hash, and normalizer commit.
Creation time is metadata only and excluded from identity.

An identical rerun validates existing outputs and returns a no-op instead of rewriting
Parquet or manifest files.

## Artifact Layout

Real output:

`data/analysis/normalized/dataset=normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07/`

Key files:

- `manifests/normalized_snapshot_manifest.json`
- `manifests/sessions/*.json`
- `trades/venue=*/date=*/session=*/part-00000.parquet`
- `top_of_book/venue=*/date=*/session=*/part-00000.parquet`
- `raw_record_outcomes/venue=*/date=*/session=*/part-00000.parquet`
- `metadata/sessions.parquet`
- `metadata/attempts.parquet`
- `catalog/normalized.duckdb`

Generated normalized data remains ignored by Git.

## Real Seven-Session Results

- normalized dataset ID: `normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07`
- normalized manifest ID: `normalized-snapshot-manifest-d233cc36d6d46cad`
- normalizer code commit: `e534e672c074fa12e0a19b85f9797adb535e97a1`
- accepted attempts: 7
- venue sessions: 14
- trade rows: 99,566
- BBO rows: 227,547
- raw diagnostic/outcome rows: 348,744
- session metadata rows: 14
- attempt metadata rows: 7
- output files: 52
- output size: 77 MiB
- semantic dataset hash: `4e7bb1002423f29b0ad3e9e6d83c72d47bac8b7f5f9cdad8f1656dddfc6e6e93`
- final composite status: `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`

Trade rows by venue:

- Coinbase: 90,515
- Kraken: 9,051

BBO rows by venue:

- Coinbase: 90,512
- Kraken: 137,035

Diagnostics:

- Coinbase OK rows: 194,053
- Kraken OK rows: 154,691
- control records: 26,054
- unsupported records: 0
- parse errors: 0

Runtime:

- initial normalization: 85.05 seconds wall time
- maximum resident set size: 2,101,657,600 bytes
- no-op rerun: 1.17 seconds wall time
- no-op maximum resident set size: 668,827,648 bytes
- determinism verifier: 170.42 seconds wall time
- determinism maximum resident set size: 2,153,693,184 bytes

## Validation Results

Snapshot validation was `VALID` with 7 accepted attempts, `13005.314148` accepted overlap
seconds, and final composite status `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`.

Normalized dataset validation was `VALID` with 0 duplicate event IDs.

DuckDB catalog build was `BUILT`; `normalized_event_stream` has 327,113 rows and
`raw_record_outcomes` has 348,744 rows.

Determinism verification was `PASSED` for event IDs, Parquet checksums, semantic hashes,
row counts, and manifest equivalence.

## Reproduction Commands

```bash
cd /Users/ansh/Developer/cross-venue-price-discovery-analysis
export PATH=/Users/ansh/Developer/cross-venue-price-discovery/.venv/bin:$PATH
export PYTHONPATH=src

python -m cross_venue.cli validate-analysis-source-snapshot \
  --snapshot-root data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c \
  --source-collection-root /Users/ansh/Developer/cross-venue-price-discovery

python -m cross_venue.cli normalize-analysis-snapshot \
  --source-collection-root /Users/ansh/Developer/cross-venue-price-discovery \
  --snapshot-root data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c \
  --analysis-output-root data/analysis \
  --expected-commit e534e672c074fa12e0a19b85f9797adb535e97a1

python -m cross_venue.cli validate-normalized-dataset \
  --normalization-manifest data/analysis/normalized/dataset=normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07/manifests/normalized_snapshot_manifest.json

python -m cross_venue.cli build-normalized-catalog \
  --normalization-manifest data/analysis/normalized/dataset=normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07/manifests/normalized_snapshot_manifest.json

python -m cross_venue.cli analysis-normalization-status \
  --normalization-manifest data/analysis/normalized/dataset=normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07/manifests/normalized_snapshot_manifest.json
```

## Limitations

Phase 3C.2 stops at canonical normalization. It does not perform descriptive analysis,
time alignment, lead-lag analysis, statistical modeling, deduplication views, or trading
simulation. The seven-session normalized snapshot remains preliminary because the source
snapshot does not satisfy the final 10-session / 18,000-second composite requirement.
