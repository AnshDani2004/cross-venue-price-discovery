# Phase 2D Data-Quality Report

Review date: 2026-07-30.

## Phase 2C Milestone

- Phase 2C PR: `#4`, `Implement Phase 2C raw archival persistence`
- Merge status: `MERGED`
- Merge commit: `f2ab1882fe2d14be916c994ef39d7ffb8fe7d476`
- CI result: passed before merge

## Phase 2D Starting State

- Branch: `phase/02d-data-quality`
- Starting commit: `f2ab1882fe2d14be916c994ef39d7ffb8fe7d476`
- Initial working tree: clean

## Scope

Implemented data-quality validation and controlled paired collection only. No feature
engineering, lead-lag analysis, models, backtests, trading rules, execution simulation,
PnL, authenticated APIs, or live trading were added.

## Files Added

- `configs/data_quality.toml`
- `src/cross_venue/quality/`
- `tests/live/test_public_quality.py`
- `tests/unit/quality_helpers.py`
- `tests/unit/test_data_quality_config.py`
- `tests/unit/test_quality_analyzer.py`
- `tests/unit/test_quality_cli.py`
- `tests/unit/test_quality_models.py`
- `tests/unit/test_quality_overlap_promotion.py`
- `data/quality/.gitkeep`
- `data/validated/.gitkeep`

## Files Modified

- `.gitignore`
- `pyproject.toml`
- `src/cross_venue/cli.py`
- `src/cross_venue/config.py`
- README, changelog, architecture, collection, data dictionary, timestamp, storage,
  research protocol, risk, and limitations docs.

## Quality Policy

Policy file: `configs/data_quality.toml`.

The policy records version `2d.1`, effective date `2026-07-30`, integrity gates, parser
thresholds, timestamp thresholds, stale quote threshold, minimum coverage, duplicate
thresholds, and quarantine switches. Unknown fields are rejected and rates are bounded to
`[0, 1]`.

## Diagnostics

- Archive integrity: reuses Phase 2C validation, manifest loading, quality summary
  loading, shard checksums, record counts, partial detection, and writer-failure checks.
- Duplicate diagnostics: exact raw-frame duplicates, consecutive duplicate runs, maximum
  duplicate run, duplicate trade identifiers, conflicting duplicate trades, exact
  duplicate trades, and repeated quote states.
- Continuity diagnostics: Coinbase sequence observations/discontinuities, Kraken
  trade-ID duplicate/nonmonotonic checks, and explicit Kraken ticker sequence-skip flag.
- Timestamp diagnostics: receipt ordering, equal receipts, interarrival percentiles,
  exchange timestamp ordering, and `observed_exchange_receipt_delta` distributions.
- Quote diagnostics: locked/crossed raw evidence, missing/nonpositive prices, negative
  sizes, zero sizes, quote state changes, repeated states, timestamp reversals, and
  local-receipt-time stale intervals.
- Coverage diagnostics: duration, frames, raw records, trades, top-of-book events,
  controls, unsupported messages, parse errors, exchange errors, reconnects,
  acknowledgements, rates, bytes, and shard counts.

## Paired Collection And Overlap

`collect-paired-quality` starts Coinbase and Kraken collectors concurrently, archives
each venue independently, persists manifests and quality summaries, validates both
archives, runs session quality analysis, computes local-receipt-time overlap, writes a
paired quality report, and leaves promotion as dry-run by default.

Overlap uses first/last valid market event and top-of-book local receipt timestamps. It
does not align prices, resample, infer leadership, or use exchange clocks as synchronized
clocks.

## Disposition Policy

Critical and error findings force `REJECTED`. Warning findings produce `QUARANTINED`.
Only reports without critical/error/warning findings are `ACCEPTED`. Paired reports are
rejected if either session is rejected or overlap fails the policy. Quarantined and
rejected reports cannot be promoted.

## Validated Dataset Manifest

Promotion is dry-run by default. Applied promotion writes an immutable manifest under
ignored `data/validated/manifests`, references accepted raw sessions and quality reports,
stores raw manifest hashes and shard checksums, and copies no raw data. Promotion rejects
quarantined or rejected sessions/pairs.

## Offline And Adversarial Tests

Default offline tests cover:

- Quality config loading, unknown fields, invalid rates, and invalid overlap thresholds.
- Quality finding schema validation, missing evidence, invalid severity, and critical
  finding rejection for accepted reports.
- Clean archive acceptance.
- Archive checksum mismatch rejection.
- Exact raw duplicate quarantine.
- Locked quote rejection.
- Kraken trade-ID duplicate diagnostics without Kraken ticker sequence analysis.
- Paired overlap acceptance and quarantine.
- Promotion dry-run, apply, and blocked promotion.
- Aggregate report counts.
- CLI session analysis and fake paired collection.

## Live Paired Collection Result

Command:

```bash
CROSS_VENUE_ENABLE_LIVE_QUALITY=1 .venv/bin/pytest -s -m live_quality tests/live/test_public_quality.py
```

Result: passed, `1 passed in 121.12s`.

Live paired run:

- Paired collection ID: `paired-36289696-9fde-4b08-9a07-694b1328ecc5`
- Coinbase session ID: `coinbase_BTC-USD_20260731T001656Z_30f1ae4e-cb38-4598-a6da-5566bcb68434`
- Kraken session ID: `kraken_BTC-USD_20260731T001656Z_b9af39bb-1ff3-4cdf-b1fb-a077301852ff`
- Requested duration: `120.0` seconds
- Start skew: `0.017484` seconds
- Market-event overlap: `117.346718` seconds
- Coinbase frames: `732`
- Kraken frames: `1312`
- Coinbase trades: `305`
- Kraken trades: `91`
- Coinbase top-of-book events: `305`
- Kraken top-of-book events: `1146`
- Coinbase parse errors: `0`
- Kraken parse errors: `0`
- Coinbase reconnects: `0`
- Kraken reconnects: `0`
- Coinbase archive validation: passed
- Kraken archive validation: passed

Quality findings:

- Coinbase: 3 warnings: negative observed exchange-receipt deltas, Coinbase sequence
  discontinuity diagnostics, and stale quote intervals.
- Kraken: 3 warnings: negative observed exchange-receipt deltas, exact raw-frame
  duplicate rate, and stale quote intervals.
- Paired report: no paired-level findings.

Dispositions:

- Coinbase disposition: `QUARANTINED`
- Kraken disposition: `QUARANTINED`
- Paired disposition: `QUARANTINED`
- Promotion dry-run: blocked, because the paired report is not accepted.

## Security Review

- Public market data only.
- No credentials or authenticated channels.
- No order, account, deposit, withdrawal, or private API functionality.
- No raw payloads printed by default.
- Quality and validated artifacts are written under ignored data directories.
- Portable reports use relative paths and hashes for lineage.

## Remaining Limitations

- The live paired run is short and does not prove long-term stability.
- Quality thresholds are policy choices.
- No clock synchronization correction is applied.
- No gap repair, deduplication, interpolation, or cleaning is performed.
- No normalized dataset was promoted from the quarantined live pair.
- No feature dataset, predictive analysis, model, backtest, strategy, execution
  simulation, PnL, or trading functionality exists.

## Phase 3 Readiness Recommendation

The Phase 2D quality system is implemented, but the bounded live paired run was
quarantined and promotion was blocked. Phase 3 should not begin from this live pilot.
Either collect an accepted paired session under the policy or explicitly review and
resolve quarantine findings before normalization.

## Verdict

NOT READY FOR PHASE 3 NORMALIZATION AND EXPLORATORY MICROSTRUCTURE ANALYSIS
