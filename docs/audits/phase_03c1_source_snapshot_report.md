# Phase 3C.1 Source Snapshot Report

Review date: 2026-08-05.

## Objective

Phase 1 creates the immutable source-catalog layer for preliminary multi-day BTC-USD
analysis. It derives membership from validated campaign state, not from a typed list,
and writes a seven-session analysis snapshot without mutating the source collection
checkout.

## Source And Output Roots

The implementation separates source and derived artifacts:

- `source_collection_root`: read-only collection checkout containing ignored campaign,
  quality, validated-manifest, and raw archive artifacts.
- `analysis_output_root`: analysis worktree output root for generated source snapshots.

For the current local build:

- Source root: `/Users/ansh/Developer/cross-venue-price-discovery`
- Output root: `/Users/ansh/Developer/cross-venue-price-discovery-analysis/data/analysis`

The snapshot identity does not include absolute source paths, usernames, wall-clock
creation time, or output paths.

## Source Selection

The source catalog includes only attempts satisfying all of these rules:

- Campaign role is `MULTI_DAY_VALIDATION`.
- Attempt status is `ACCEPTED`.
- Inclusion status is `INCLUDED`.
- Paired, Coinbase, and Kraken dispositions are all `ACCEPTED`.
- A validated-pair manifest is present and its file hash matches the registry.
- Source session manifest hashes, quality report hashes, paired quality report hash,
  raw shard checksums, runtime commit, and quality policy lineage are present.
- The campaign registry and append-only ledger agree after read-only reconstruction.

The formal multi-day source campaign remains:

- `btc-usd-coinbase-kraken-2026-07-31-v1`

The exploratory intraday campaign remains separate and is not included.

## Accepted Inventory

The generated snapshot includes exactly these seven accepted attempts:

1. `btc-usd-coinbase-kraken-2026-07-31-v1-P02-001`
2. `btc-usd-coinbase-kraken-2026-07-31-v1-P03-001`
3. `btc-usd-coinbase-kraken-2026-07-31-v1-P09-001`
4. `btc-usd-coinbase-kraken-2026-07-31-v1-P10-001`
5. `btc-usd-coinbase-kraken-2026-07-31-v1-R01-001`
6. `btc-usd-coinbase-kraken-2026-07-31-v1-R02-001`
7. `btc-usd-coinbase-kraken-2026-07-31-v1-R05-001`

Excluded:

- `btc-usd-coinbase-kraken-2026-07-31-v1-P08-001` is quarantined with
  `inclusion_status = EXCLUDED`.
- Missed slots `P01`, `P04`, `P05`, `P06`, `P07`, `R03`, and `R04` contribute no data.

## Snapshot Identity

Source-catalog ID:

- `analysis-source-catalog-3b3ad1fa97ef60a1`

Snapshot ID:

- `analysis-snapshot-7-session-v1-5f796ab67a5c801c`

Hashing rules:

- JSON is canonicalized with sorted keys and compact separators.
- Accepted attempts are ordered by planned UTC start, slot ID, and campaign attempt ID.
- Overlap aggregation uses Decimal values quantized to six decimal places.
- Creation timestamps are recorded as metadata but excluded from deterministic content
  and identity hashes.
- Absolute source and output paths are excluded from identity material.

Aggregate totals:

- Accepted attempts: `7`
- Aggregate paired-overlap seconds: `13005.314148`
- Accepted calendar dates: `2026-07-31`, `2026-08-02`, `2026-08-03`, `2026-08-04`
- Accepted time buckets: `AFTERNOON`, `EVENING`, `MORNING`

Disposition:

- Snapshot status: `SOURCE_SNAPSHOT_VALID`
- Final composite status: `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`

This is valid for preliminary multi-day analysis. It is not the final ten-session /
eighteen-thousand-second composite validation dataset.

## Artifact Layout

Generated local artifacts are ignored by Git:

```text
data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c/source_catalog.json
data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c/snapshot_manifest.json
data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c/snapshot_validation.json
```

If the same deterministic snapshot already exists, rebuild is a no-op when content
hashes match and fails when conflicting content is present.

## Validation Behavior

Snapshot validation verifies:

- Source campaign registry and ledger hash-chain validity.
- Registry/ledger agreement.
- Deterministic source-catalog and snapshot IDs.
- Validated-pair manifest hash preservation.
- Attempt inclusion/exclusion rules.
- Duplicate attempt and manifest rejection.
- Exact Decimal overlap aggregation.
- Runtime and quality policy lineage.

Future accepted sessions create a new snapshot directory and do not mutate the
seven-session snapshot.

## Reproduction Commands

```bash
cd /Users/ansh/Developer/cross-venue-price-discovery-analysis
export PATH=/Users/ansh/Developer/cross-venue-price-discovery/.venv/bin:$PATH
export PYTHONPATH=src

python -m cross_venue build-analysis-source-snapshot \
  --source-collection-root /Users/ansh/Developer/cross-venue-price-discovery \
  --analysis-output-root data/analysis \
  --campaign-id btc-usd-coinbase-kraken-2026-07-31-v1

python -m cross_venue validate-analysis-source-snapshot \
  --snapshot-root data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c \
  --source-collection-root /Users/ansh/Developer/cross-venue-price-discovery

python -m cross_venue analysis-snapshot-status \
  --snapshot-root data/analysis/snapshots/analysis-snapshot-7-session-v1-5f796ab67a5c801c
```

## Known Limitations

- This phase does not normalize raw market data.
- This phase does not run descriptive, lead-lag, formal model, or robustness analysis.
- Source campaign completion is not changed; the original campaign remains formally
  unsatisfied.
- The final composite dataset still depends on future supplemental multi-day accepted
  sessions.
