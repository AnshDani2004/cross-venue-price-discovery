# Phase 3B.2 Long-Duration Collection Fix Report

Review date: 2026-07-31.

## Failure Summary

- Failed slot: `I01`
- Failure timestamp: `2026-07-31T17:02:39Z`
- Attempt ID: `btc-usd-coinbase-kraken-2026-07-31-intraday-v1-I01-001`
- Historical failure classification: `UNKNOWN_FAILURE`
- Historical failure message: `duration exceeds Phase 2D maximum`
- Status: `FAILED`
- Inclusion status: `EXCLUDED`
- Coinbase frames: `0`
- Kraken frames: `0`
- Coinbase session ID: `null`
- Kraken session ID: `null`
- Paired collection ID: `null`
- Paired overlap seconds: `0`
- Validated pair manifest: `null`

No market-data evidence was collected. The I01 failed attempt remains part of the
append-only ledger and is not rewritten or rerun.

## Root Cause

`src/cross_venue/quality/collection.py` enforced
`quality_config.max_controlled_duration_seconds`, which was `300` seconds in
`configs/data_quality.toml`. The campaign requested `1,860` seconds, so Phase 2D
preflight failed before public collectors were loaded.

The existing 180-second smoke and mocked campaign tests stayed below, or bypassed, the
real Phase 2D preflight path. They therefore did not exercise the production campaign
duration.

## Corrected Runtime Limits

The corrected implementation defines shared finite runtime limits:

- Maximum paired collection duration: `3,600` seconds
- Maximum paired collection messages per venue: `100,000`

These are runtime safety limits, not quality-policy thresholds. The `2d.2` quality-policy
thresholds and existing campaign policy hashes are unchanged.

Invalid durations and message limits fail before network access. Requests are never
silently clamped.

## Failure Classification

Future deterministic collection preflight failures are classified as
`COLLECTION_PREFLIGHT_FAILURE`. I01 keeps its historical `UNKNOWN_FAILURE`
classification because ledger history is immutable.

## Migration Rules

The normal pre-collection migration remains available for campaigns with zero attempts.
For campaigns with only strictly zero-data failed attempts, the corrective runtime may be
recorded with `CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE` and reason
`LONG_DURATION_PREFLIGHT_FIX`.

The zero-data migration requires failed attempts with no frames, no sessions, no paired
collection ID, no overlap, no validated manifests, no source hashes, no raw shard
checksums, no quality report hashes, no promotion, and no campaign attempt directory.

## Validation

The regression suite now covers:

- 180-second, 1,860-second, and 3,600-second accepted preflight durations
- 0-second, negative, and 3,601-second rejected durations
- real campaign runner to Phase 2D preflight integration
- explicit preflight failure classification
- normal zero-attempt runtime migration
- zero-data failed-attempt runtime migration
- migration blocked when failed attempts contain collected evidence

Focused duration and migration tests passed with `41 passed, 2 skipped`.

Required validation gates passed before runtime migration:

- `ruff format .`
- `ruff check .`
- `ruff format --check .`
- `mypy src`
- selected non-live pytest: `250 passed, 8 deselected`
- `pre-commit run --all-files`
- `make check`: `250 passed, 3 skipped, 5 deselected`
- `pip check`
- `git diff --check`

## Migration Results

Initial corrective commit: `1546d7f011ba1d27e3f90f8e0119ceafbce0d0d0`.

Multi-day campaign migration:

- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-v1`
- Old runtime: `eecfdee01186bdc1a8d35546f22888dbf50ba5cf`
- New runtime: `1546d7f011ba1d27e3f90f8e0119ceafbce0d0d0`
- Event type: `CAMPAIGN_RUNTIME_MIGRATED`
- Event index: `3`
- Event hash: `f4a30d683ab76d2b08725fc7fccfe89e4f818f3adac828ee179fbfc82bbe1881`
- Validation status: `VALID`

Intraday campaign migration:

- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-intraday-v1`
- Old runtime: `eecfdee01186bdc1a8d35546f22888dbf50ba5cf`
- New runtime: `1546d7f011ba1d27e3f90f8e0119ceafbce0d0d0`
- Event type: `CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE`
- Event index: `3`
- Event hash: `51b3619db77b0e734a37f3cd2f8feec58b945ced4525ab675960c44d81711a20`
- Validation status: `VALID`

Because this report was finalized after the first corrective migration, the campaigns are
expected to receive one additional migration event to the final documentation commit.

## Next Slots

- Intraday next slot: `I02`, planned `2026-07-31 13:45 America/New_York`
- Multi-day next slot: `P02`, planned `2026-07-31 16:00 America/New_York`

No slot was run during this remediation before the report was finalized.
