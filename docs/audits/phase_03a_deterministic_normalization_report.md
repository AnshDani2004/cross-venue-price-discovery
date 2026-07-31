# Phase 03A Deterministic Normalization Report

Review date: 2026-07-31

## Scope

Phase 3A implemented deterministic analytical replay from a finalized Phase 2D.1
validated dataset manifest into normalized Parquet tables and DuckDB views. This phase
does not compute lead-lag statistics, features, labels, models, backtests, strategies,
PnL, authenticated APIs, or trading logic.

## Stage A Closure

PR #6, "Calibrate Phase 2D quality semantics", was reviewed and merged before Phase 3A
development began.

- PR: https://github.com/AnshDani2004/cross-venue-price-discovery/pull/6
- Final Phase 2D.1 commit: `9c73117f2236fc816ffa88c144662c3d198df62b`
- Merge commit on `main`: `6f0b4a51f7ceab7698cf0a77ada96f01e88139ce`
- Merged at: `2026-07-31T01:39:15Z`
- CI status before merge: successful

The Phase 3A branch was created from `main` at
`6f0b4a51f7ceab7698cf0a77ada96f01e88139ce`.

## Input Evidence

The accepted local validated manifest was:

```text
data/validated/manifests/validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd.json
```

- Validated manifest ID: `validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd`
- Validated manifest SHA-256:
  `d4c5d7153eb1a04770370c42c9ea9f584316dfc2213a2bfa7a46c2e2591de0e1`
- Paired collection ID: `paired-0806e90a-201e-4ee5-89ab-277d4531defd`
- Quality policy version: `2d.2`
- Quality policy SHA-256:
  `375eb5655d0d9212814502663a6284a316c1d6913585acece35ded2137332024`
- Canonical instrument: `BTC-USD`
- Venues: Coinbase, Kraken
- Overlap window:
  `2026-07-31T01:17:38.181719+00:00` to
  `2026-07-31T01:20:36.467885+00:00`

Source sessions:

- `coinbase_BTC-USD_20260731T011736Z_95179e8e-fad3-485e-8c81-f63736c5c8ef`
- `kraken_BTC-USD_20260731T011736Z_4bee45cf-d425-4b8e-b38b-8439d853a4c6`

## Implementation Summary

Phase 3A added:

- `configs/normalization.toml`
- `src/cross_venue/normalization/`
- CLI commands:
  - `normalize-dataset`
  - `validate-normalized-dataset`
  - `build-normalized-catalog`
  - `verify-normalization-determinism`
- Opt-in pytest marker: `local_validated_data`

The normalizer requires a validated manifest, accepted session and paired quality
reports, unchanged source manifests, unchanged raw shard checksums, expected venues,
single canonical instrument, and a clean working tree for final runs.

Output rows preserve raw duplicate records, connection epoch, source shard lineage,
source raw record index, raw frame hash, local receipt timestamp, exchange timestamp,
and deterministic event IDs. Financial price and size fields are written as exact
`decimal128(38, 18)` Arrow values and are rejected if they cannot be represented
without rounding or truncation.

## Real Accepted-Data Run

Command:

```bash
python -m cross_venue normalize-dataset \
  --validated-manifest data/validated/manifests/validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd.json \
  --normalization-config configs/normalization.toml \
  --expected-commit f05c658c54cacb5469a5b1afda900e3183d6bd48
```

Result:

- Normalizer commit: `f05c658c54cacb5469a5b1afda900e3183d6bd48`
- Normalized dataset ID:
  `normalized-paired-0806e90a-201e-4ee5-89ab-277d4531defd-03be5d51b07b`
- Manifest path:
  `data/normalized/dataset=normalized-paired-0806e90a-201e-4ee5-89ab-277d4531defd-03be5d51b07b/manifest/normalization_manifest.json`
- Output files: 6 Parquet files
- Output bytes: 795,575
- Reconciliation status: `PASSED`
- Manifest validation status: `VALID`

Row counts:

| Table | Rows |
| --- | ---: |
| Trades | 1,257 |
| Top of book | 3,803 |
| Raw record outcomes | 5,361 |
| Source raw records | 5,361 |

Venue counts:

| Venue | Raw records | Trades | Top of book | Duplicate raw frames |
| --- | ---: | ---: | ---: | ---: |
| Coinbase | 2,422 | 1,120 | 1,120 | 0 |
| Kraken | 2,939 | 137 | 2,683 | 226 |

Outcome counts:

| Venue | Outcome | Count |
| --- | --- | ---: |
| Coinbase | `HEARTBEAT` | 181 |
| Coinbase | `NORMALIZED_TOP_OF_BOOK` | 1,120 |
| Coinbase | `NORMALIZED_TRADE` | 1,120 |
| Coinbase | `SUBSCRIPTION_ACKNOWLEDGEMENT` | 1 |
| Kraken | `HEARTBEAT` | 178 |
| Kraken | `NORMALIZED_MULTIPLE_TRADES` | 40 |
| Kraken | `NORMALIZED_TOP_OF_BOOK` | 2,683 |
| Kraken | `NORMALIZED_TRADE` | 35 |
| Kraken | `STATUS_MESSAGE` | 1 |
| Kraken | `SUBSCRIPTION_ACKNOWLEDGEMENT` | 2 |

No unsupported messages or parse errors were produced.

## Validation And Determinism

Validation command:

```bash
python -m cross_venue validate-normalized-dataset \
  --normalization-manifest data/normalized/dataset=normalized-paired-0806e90a-201e-4ee5-89ab-277d4531defd-03be5d51b07b/manifest/normalization_manifest.json
```

Validation result:

- Status: `VALID`
- Errors: none
- Duplicate normalized event IDs: 0

Catalog command:

```bash
python -m cross_venue build-normalized-catalog \
  --normalization-manifest data/normalized/dataset=normalized-paired-0806e90a-201e-4ee5-89ab-277d4531defd-03be5d51b07b/manifest/normalization_manifest.json
```

Catalog result:

- Catalog status: `BUILT`
- `trades`: 1,257
- `top_of_book`: 3,803
- `raw_record_outcomes`: 5,361
- `normalized_event_stream`: 5,060

Determinism command:

```bash
python -m cross_venue verify-normalization-determinism \
  --validated-manifest data/validated/manifests/validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd.json
```

Determinism result:

- Status: `PASSED`
- Event ID equality: true
- Row count equality: true
- Semantic hash equality: true
- Parquet checksum equality: true
- Manifest equivalence: true

Semantic hashes:

- Trades: `714e093b8f82497240d6db9711206ef4b99ad27cc10a59f2e4bf8cdedd192a99`
- Top of book: `a8c3bac5461b0449ef0d34836fe69758e6eea84e52356a44004339c88f26c85e`
- Raw outcomes: `d8f2831d4ed691f6def70e6390aff726230c8db318e791180c7dcf97105e0fcb`
- Dataset: `e08a57c5eb6e904126727ee10eb0700f170d512161a5861de11c7f176c3082bb`

## Artifact Boundary

Generated raw, quality, validated, and normalized local data remain ignored by Git.
The learning documents remain local and ignored:

- `docs/interview_guide.md`
- `docs/learning_log.md`

Only source code, configuration, tests, and recruiter-safe documentation were committed.

## Known Limitations

- Phase 3A preserves timestamps but applies no clock correction or latency inference.
- Phase 3A preserves duplicate raw frames and flags them; it does not deduplicate.
- Physical Parquet byte equality is verified within the local dependency environment.
- The DuckDB catalog is an analytical convenience over Parquet files, not a new source
  of truth.
- No lead-lag or trading conclusion is produced in this phase.

## Verdict

READY FOR PHASE 3B MULTI-SESSION COLLECTION CAMPAIGN
