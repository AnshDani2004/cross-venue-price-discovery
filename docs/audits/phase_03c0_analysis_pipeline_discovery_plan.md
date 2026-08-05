# Phase 3C.0 Analysis Pipeline Discovery Plan

Review date: 2026-08-05.

Worktree:

- Active collection checkout, read-only: `/Users/ansh/Developer/cross-venue-price-discovery`
- Analysis worktree: `/Users/ansh/Developer/cross-venue-price-discovery-analysis`
- Analysis branch: `phase/03c-analysis-pipeline`
- Analysis base commit: `98e28b2e026124434fc1bec1d442d7b9bcbc8530`

## Phase Boundary

This is Phase 0 only. It records repository discovery, data inventory, architecture,
implementation order, and risks for the post-collection research pipeline. It does not
change collection code, campaign state, source data, registries, ledgers, quality
reports, validated manifests, raw archives, or normalized outputs.

The active collection checkout remains the source of truth for ignored local campaign
artifacts and must stay pinned to `98e28b2e026124434fc1bec1d442d7b9bcbc8530`.

## Current Source Of Truth

Primary multi-day campaign:

- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-v1`
- Role: `MULTI_DAY_VALIDATION`
- Status: `IN_PROGRESS`
- Completion: `UNSATISFIED`
- Accepted attempts: `7`
- Accepted overlap seconds: `13005.314148`
- Accepted calendar dates: `2026-07-31`, `2026-08-02`, `2026-08-03`,
  `2026-08-04`
- Accepted time buckets: `AFTERNOON`, `EVENING`, `MORNING`
- Missed slots: `7`
- Quarantined attempts: `1`
- Rejected attempts: `0`
- Failed attempts: `0`
- Reserve slots remaining: `0`
- Requested duration: `1860` seconds
- Maximum messages per venue: `100000`
- Runtime commit: `98e28b2e026124434fc1bec1d442d7b9bcbc8530`
- Quality policy version: `2d.2`
- Registry ledger hash: `7325b8835c74dff0c86d8e8ca976bd138b1ab50444b8d0b0a1fc3e62ba70018d`

Formal shortfall against the intended multi-day validation target:

```text
sessions_needed = max(0, 10 - 7) = 3
overlap_needed = max(0, 18000 - 13005.314148) = 4994.685852
minimum_supplemental_sessions = max(3, ceil(4994.685852 / 1800)) = 3
```

The original campaign is not complete and must not be made to appear complete.

## Accepted Attempt Inventory

Exactly seven accepted and included attempts are available. Each has a validated-pair
manifest under `data/validated/manifests`; each manifest hash matches the registry;
each accepted pair references six raw archive shards, three per venue.

| Attempt | Slot | Bucket | Planned UTC | Overlap sec | Validated-pair manifest | Hash ok | Raw shards |
|---|---:|---|---|---:|---|---:|---:|
| `btc-usd-coinbase-kraken-2026-07-31-v1-P02-001` | `P02` | `AFTERNOON` | `2026-07-31T20:00:00Z` | 1856.790902 | `validated-paired-0bef4dc2-7b60-4c7c-aa07-a9dc90b3e8bc` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-P03-001` | `P03` | `EVENING` | `2026-08-01T02:00:00Z` | 1855.849980 | `validated-paired-1b78cbcf-62c5-4d5c-9829-bfa6d2999fe2` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-P09-001` | `P09` | `EVENING` | `2026-08-03T02:00:00Z` | 1858.689021 | `validated-paired-a18713dc-b448-4c67-8cd6-917d6410a119` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-P10-001` | `P10` | `MORNING` | `2026-08-03T14:00:00Z` | 1858.812558 | `validated-paired-d943dca9-f0d7-47f9-84d3-f3aa5b83f86c` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-R01-001` | `R01` | `AFTERNOON` | `2026-08-03T20:00:00Z` | 1858.356535 | `validated-paired-bbc595c7-7082-4c07-a603-fdf41d5ad4fb` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-R02-001` | `R02` | `EVENING` | `2026-08-04T02:00:00Z` | 1858.276005 | `validated-paired-a539656a-e7cf-4f32-903c-062f34f41f66` | true | 6 |
| `btc-usd-coinbase-kraken-2026-07-31-v1-R05-001` | `R05` | `EVENING` | `2026-08-05T02:00:00Z` | 1858.539147 | `validated-paired-55c8e33b-4f21-4f8d-b96f-05493254d6c0` | true | 6 |

Excluded data:

- `btc-usd-coinbase-kraken-2026-07-31-v1-P08-001` is `QUARANTINED`, has
  `inclusion_status = EXCLUDED`, `exclusion_reason = PAIRED_QUALITY_QUARANTINED`,
  and must not enter any formal multi-day analysis snapshot.
- Missed slots `P01`, `P04`, `P05`, `P06`, `P07`, `R03`, and `R04` have no included
  attempt data and must contribute no rows.

Intraday exploratory campaign:

- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-intraday-v1`
- Role: `EXPLORATORY_INTRADAY`
- Completion: `UNSATISFIED`
- Accepted attempts: `8`
- Accepted overlap seconds: `14858.860951`
- Accepted dates: `2026-07-31`, `2026-08-01`
- Accepted buckets: `AFTERNOON`, `EVENING`
- Use only for exploratory method development. Do not pool it into formal multi-day
  validation outputs.

## Repository Findings

Package layout already has mature collection, storage, quality, campaign, and
normalization modules. The research-oriented packages exist as placeholders:

- `cross_venue.research`
- `cross_venue.features`
- `cross_venue.labels`
- `cross_venue.models`
- `cross_venue.reporting`
- `cross_venue.fair_value`
- `cross_venue.backtest`
- `cross_venue.execution`

Existing reusable code:

- Raw archival with manifests and shard checksums in `cross_venue.storage`.
- Quality reports, validated-pair manifests, and promotion logic in
  `cross_venue.quality`.
- Campaign registries, append-only ledgers, completion checks, scheduling, and
  validated campaign finalization in `cross_venue.campaigns`.
- Deterministic normalization from validated pair or completed campaign manifests in
  `cross_venue.normalization`.
- Parquet output and DuckDB catalog views already exist.
- Deterministic IDs and semantic table hashing already exist in
  `cross_venue.normalization.identifiers`.
- CLI registration already covers normalization, normalized validation, DuckDB catalog
  build, normalization determinism, and campaign operations.
- `pyproject.toml` already includes DuckDB, Polars, PyArrow, NumPy, SciPy,
  statsmodels, scikit-learn, and matplotlib.
- `Makefile` supports `lint`, `format`, `format-check`, `typecheck`, `test`, and
  `check`.
- Pre-commit runs formatting checks, lint, mypy, pytest, and secrets checks.

Important gap:

The existing `finalize-campaign-manifest` path requires `CampaignStatus.COMPLETE`.
That is correct for completed campaigns, but the primary multi-day campaign is
intentionally incomplete and immutable. Phase 1 therefore needs a new source-catalog
or analysis-snapshot abstraction that validates and freezes the seven accepted
included attempts without finalizing or mutating the original campaign.

Prior branch findings:

- `phase/03b5-intraday-continuation` contains a reusable exploratory composite
  manifest command for separate intraday campaigns.
- `phase/03b6-multiday-supplement` contains a reusable multi-day composite validation
  manifest implementation.
- The `phase/03b6-multiday-supplement` campaign config was calculated from an older
  four-session primary shortfall and requires six supplemental sessions. Current
  repository state requires three supplemental sessions. Treat that config as stale
  for future campaign sizing unless it is recalculated.

## Dependency Graph

```text
Campaign registry + append-only ledger
    -> accepted included attempt references
    -> validated-pair manifests
    -> session quality reports + paired quality reports
    -> raw session manifests + raw shard checksums
    -> source catalog / analysis snapshot
    -> per-session deterministic normalization
    -> aggregate normalized snapshot manifest
    -> normalized dataset validation
    -> descriptive summaries and figures
    -> alignment and feature tables
    -> exploratory lead-lag analysis
    -> formal price-discovery models
    -> robustness and falsification
    -> incremental supplemental ingestion
    -> final composite validation
    -> report and portfolio deliverables
```

## Proposed Modules

Phase 1 should introduce a compact source-snapshot layer:

- `cross_venue.research.source_catalog`: read campaign configs, validate registry and
  ledger, collect accepted included attempts, verify validated-pair manifests and
  hashes, reject excluded attempts, and build deterministic membership.
- `cross_venue.research.snapshot`: immutable analysis snapshot models, deterministic
  snapshot ID, aggregate counts, source lineage, and content hash.
- `cross_venue.research.snapshot_store`: atomic write-once persistence and validation
  helpers.
- `cross_venue.research.exceptions`: source-catalog and snapshot-specific exceptions.

Phase 2 should either extend existing normalization to consume an analysis snapshot
or add an adapter that converts snapshot entries into the current normalization input
bundle without bypassing manifest, quality, or checksum checks.

Later phases should fill the placeholder packages with narrowly scoped modules:

- `features.alignment` and `features.microstructure`
- `research.descriptive`
- `research.lead_lag`
- `models.price_discovery`
- `research.robustness`
- `reporting.figures`
- `reporting.reports`

## Proposed CLI Commands

Do not rename existing commands. Add new commands only where the existing CLI lacks
the needed concept:

- `build-analysis-source-snapshot`
  - Inputs: campaign ID or campaign config, optional snapshot label, config paths.
  - Output: immutable seven-session source snapshot and validation report.
- `validate-analysis-source-snapshot`
  - Revalidates registry, ledger, manifest hashes, inclusion status, duplicate
    attempts, source manifests, quality report hashes, and raw shard references.
- `normalize-analysis-snapshot`
  - Reuses the existing normalizer where possible, but preserves snapshot ID and
    supports per-session incremental manifests.
- `validate-analysis-normalized-snapshot`
  - Extends current normalized validation to enforce snapshot membership and lineage.
- Later phase commands:
  - `build-descriptive-report`
  - `build-aligned-research-dataset`
  - `run-exploratory-lead-lag`
  - `run-formal-price-discovery`
  - `run-robustness-suite`
  - `ingest-supplemental-sessions`
  - `validate-composite-analysis-dataset`

## Proposed Artifact Paths

Use ignored data directories for generated data and committed docs for reproducible
plans and methodology:

```text
data/analysis/source_snapshots/snapshot=<snapshot_id>/manifest/source_snapshot.json
data/analysis/source_snapshots/snapshot=<snapshot_id>/reports/source_snapshot_validation.json
data/analysis/normalized/snapshot=<snapshot_id>/sessions/session=<session_id>/manifest/normalization_manifest.json
data/analysis/normalized/snapshot=<snapshot_id>/aggregate/manifest/normalization_snapshot_manifest.json
data/analysis/normalized/snapshot=<snapshot_id>/catalog/normalized.duckdb
data/analysis/reports/snapshot=<snapshot_id>/descriptive/
data/analysis/research/snapshot=<snapshot_id>/aligned/
data/analysis/research/snapshot=<snapshot_id>/lead_lag/
data/analysis/research/snapshot=<snapshot_id>/formal_models/
data/analysis/research/snapshot=<snapshot_id>/robustness/
docs/research/
docs/audits/
```

Snapshots must be write-once. Future supplemental sessions create a new snapshot ID
instead of mutating the seven-session snapshot.

## Phase Plan

Phase 1:

- Build immutable source catalog and seven-session analysis snapshot.
- Validate inclusion, manifests, hashes, ledger, registry, deterministic ordering,
  duplicate rejection, and no source mutation.

Phase 2:

- Normalize the snapshot into canonical trades, BBO, metadata, and diagnostic tables.
- Reuse existing parser, Parquet, checksum, and DuckDB machinery.
- Add incremental no-op and changed-input behavior.

Phase 3:

- Validate normalized outputs for lineage, row counts, timestamp ranges, spread and
  price sanity, partitions, event IDs, output hashes, and excluded-attempt absence.

Phase 4:

- Produce session-level descriptive microstructure tables and figures.

Phase 5:

- Build leakage-safe alignment and feature tables across exchange time, receipt time,
  clock-time sampling, event-time sampling, and previous-tick style alignment.

Phase 6:

- Run exploratory event-ordering, cross-correlation, and conditional response
  analysis with dependence-aware uncertainty.

Phase 7:

- Implement a small formal model set: VAR lead-lag, Granger causality, and one
  justified price-discovery measure if assumptions hold.

Phase 8:

- Run robustness, leave-one-session-out, timestamp-choice, sampling-choice, outlier,
  stale-interval, and placebo/falsification checks.

Phase 9:

- Implement deterministic incremental ingestion before future supplemental sessions
  arrive.

Phase 10:

- Integrate the future correctly sized supplemental multi-day campaign after it
  exists and is validated.

Phase 11:

- Validate the final composite multi-day dataset across separate source campaign
  registries and ledgers.

Phase 12:

- Produce the final research report, reproduction guide, data dictionary, figure
  gallery, README, lineage diagrams, resume bullets, and portfolio copy.

## Testing Plan

Phase 1 tests:

- Accepted attempts included.
- Quarantined P08 excluded.
- Missed slots excluded.
- Deterministic ordering and snapshot ID.
- Missing manifest failure.
- Validated-pair hash mismatch failure.
- Invalid registry or ledger failure.
- Duplicate attempt identity failure.
- No mutation of source campaign registry or ledger.

Phase 2 tests:

- Snapshot input adapter validation.
- Coinbase and Kraken trade and BBO parsing through snapshot lineage.
- Deterministic event IDs.
- Timestamp normalization.
- Decimal precision.
- Duplicate handling.
- Malformed-event diagnostics.
- Partition stability.
- Incremental no-op behavior.
- Rebuild on changed input hash.
- Lineage completeness.

Later phases should add synthetic fixtures for statistical routines and use local
ignored source-data tests only behind opt-in markers.

## Risks And Open Questions

- Existing normalization consumes validated-pair manifests or completed campaign
  manifests, not incomplete campaign snapshots. The adapter should be minimal and
  should preserve the existing validation behavior.
- The current seven-session sample is acceptable for preliminary analysis, but
  session-level inference remains limited until the supplemental campaign fills the
  three-session and overlap shortfall.
- The prior supplemental branch is useful reference code but has stale completion
  sizing. Any future supplemental campaign must be recalculated from the then-current
  primary campaign and source state.
- Calendar dates in the campaign registry are local campaign dates, while some
  planned UTC timestamps fall on the following UTC date. Analysis metadata must carry
  both UTC and campaign-local dates.
- Receipt timestamps must not be interpreted as network latency. All latency-sensitive
  wording needs explicit timestamp semantics.
- Event-level observations are dependent. Tests and reports must keep session-level
  replication visible and avoid overconfident pooled standard errors.
- Several later modeling choices need explicit approval when reached: sampling grids,
  lead-lag horizon grid, formal price-discovery measure, bootstrap design, and
  multiple-testing policy.
