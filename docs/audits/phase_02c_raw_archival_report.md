# Phase 2C Raw Archival Report

Review date: 2026-07-30.

## Stage A Closure

- Phase 2B PR: `#3`, `Implement Phase 2B live public collectors`
- Phase 2B state: `MERGED`
- Phase 2B merge commit: `60e8951ffbc44cdd02b9dca372d1177bbcaaa551`
- Phase 2C branch: `phase/02c-raw-archival`
- Phase 2C starting commit: `60e8951ffbc44cdd02b9dca372d1177bbcaaa551`

## Implemented

- Exact raw WebSocket frame archival before JSON decode and parser normalization.
- Text frame preservation as exact UTF-8 strings and binary frame preservation as reversible Base64.
- Bounded asynchronous writer queue with visible backpressure and storage failure propagation.
- Append-only JSONL raw shards under `data/raw`.
- Atomic shard finalization from `.partial` to `.jsonl`.
- SHA-256 sidecars for finalized shards.
- Persistent atomic session manifests.
- Persistent atomic data-quality summaries.
- Archive validation for manifests, quality summaries, record ordering, shard counts, byte counts, partial files, and checksums.
- Partial-shard recovery with dry-run mode, original partial preservation, valid-prefix rewrite, and checksum sidecar creation.
- CLI commands: `smoke-archive`, `validate-archive`, and `recover-session`.
- Offline tests for archive records, safe paths, writer rotation, checksums, validation, recovery, runtime integration, and CLI behavior.
- Opt-in live persistence tests marked `live_persistence`.

## Validation

Commands run:

```bash
.venv/bin/ruff format .
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/pytest
CROSS_VENUE_ENABLE_LIVE_PERSISTENCE=1 .venv/bin/pytest -s -m live_persistence tests/live/test_public_persistence_smoke.py
```

Results:

- Ruff format/check: passed.
- Mypy strict source check: passed, 43 source files.
- Default offline pytest: passed, 173 passed and 4 deselected.
- Live persistence pytest: passed, 2 passed in 40.51 seconds.

Live persistence evidence:

| Venue | Frames archived | Trades normalized | Top-of-book normalized | Control messages | Parse errors | Shards | Archive bytes | Validation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Coinbase | 210 | 95 | 94 | 21 | 0 | 1 | 167221 | valid |
| Kraken | 327 | 16 | 298 | 23 | 0 | 1 | 246059 | valid |

Generated live archive directories were verified as ignored by Git:

```text
!! data/raw/venue=coinbase/
!! data/raw/venue=kraken/
```

## Scope Boundary

Phase 2C did not add normalized production persistence, feature engineering, labels,
model training, fair-value estimation, backtesting, strategy logic, authenticated APIs,
order submission, PnL, or position management.

## Remaining Work

- Longer controlled collection windows.
- Host clock offset and jitter recording.
- Sequence gap and duplicate detection over persisted archives.
- Cross-session quality gates before normalized dataset promotion.
- Crash-drill validation of partial-shard recovery.

## Verdict

READY FOR PHASE 2D DATA-QUALITY VALIDATION AND CONTROLLED COLLECTION
