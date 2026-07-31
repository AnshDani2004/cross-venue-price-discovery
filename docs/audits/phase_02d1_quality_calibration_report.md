# Phase 2D.1 Quality Calibration Report

## Starting State

- Branch: `phase/02d1-quality-calibration`
- Investigation commit: `8caa70ad13d28ab0e2c8a7faffaf87986ed3156f`
- Phase 2D merge commit: `301b2ad14b9074e0f56e280a2145c7558b5a674b`
- Original paired collection: `paired-36289696-9fde-4b08-9a07-694b1328ecc5`

## Corrections

- Replaced the investigation host-clock commands with read-only observation commands.
- Removed the prior `sntp -sS` path and added command safety checks against privileged
  or clock-setting invocations.
- Added calibrated reanalysis lineage fields: analysis commit, clean-tree status,
  policy version, policy hash, source paired-report hash, source manifest hashes, source
  shard checksums, and analysis start/completion timestamps.
- Final calibrated reports are refused when generated from a dirty working tree.

## Policy 2d.2

Policy 2d.2 changes interpretation, not raw evidence:

- Stable and low-variance observed exchange-receipt deltas are informational clock/feed
  diagnostics.
- Coinbase product sequence jumps are diagnostic under the current partial subscription
  unless heartbeat or trade-correspondence evidence indicates subscribed-message loss.
- Kraken exact duplicates are typed by heartbeat, status, subscription, ticker, and
  trade semantics.
- Quote age is separated from connection inactivity and expected feed behavior.

Official sources reviewed:

- Coinbase Exchange WebSocket channels:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/channels
- Kraken ticker:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker
- Kraken heartbeat:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/heartbeat
- Kraken trades:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade

## Original Pair Before/After

Output root:
`data/quality/calibrated/policy=2d.2/paired-36289696-9fde-4b08-9a07-694b1328ecc5/`

| Finding | Original classification | Calibrated classification | Original severity | Calibrated severity | Evidence | Policy justification |
| --- | --- | --- | --- | --- | --- | --- |
| Coinbase negative deltas | Negative observed exchange-receipt deltas | `STABLE_OFFSET` | `WARNING` | `INFO` | 490 negative out of 610 eligible; median `-30.9055 ms` | Stable offset is not one-way latency and is not a feed-integrity failure by itself. |
| Coinbase sequence | Identifier anomaly | Product sequence diagnostic | `WARNING` | `INFO` | Product sequence discontinuity count `304` | Partial subscription does not imply every product sequence jump is a missed subscribed message. |
| Coinbase quote age | Stale interval | Quote-age diagnostic | `WARNING` | `INFO` | 12 quote-age intervals | Quote age is separated from connection inactivity and match/ticker correspondence. |
| Kraken negative deltas | Negative observed exchange-receipt deltas | `LOW_VARIANCE_OFFSET` | `WARNING` | `INFO` | 759 negative out of 1237 eligible; median `-2.232 ms`, p95 `53.992 ms` | Low-variance offset remains visible but does not quarantine alone. |
| Kraken duplicates | Aggregate raw duplicate rate | Typed raw duplicate diagnostic | `WARNING` | `INFO` | Exact raw duplicate rate `0.10899390243902439`; no duplicate trade IDs | Heartbeat/ticker duplicates do not inflate a general market-data duplicate failure gate. |
| Kraken quote age | Stale interval | Quote-age diagnostic | `WARNING` | `INFO` | 7 quote-age intervals | Kraken `event_trigger=bbo` means trades need not force BBO updates. |

Original disposition: `QUARANTINED`

Calibrated disposition: `ACCEPTED`

Promotion dry-run for the recalibrated original pair: allowed. This was not used as the
Phase 3 gate because a newly collected accepted pair is required.

## New Calibration Pilots

All pilots were bounded public unauthenticated paired collections:

- Duration: 180 seconds
- Maximum frames per venue: 20,000
- Policy: `2d.2`
- Runs were sequential, so they do not demonstrate time-of-day or regime diversity.

| Pair | Start skew | Overlap | Coinbase frames/trades/BBO | Kraken frames/trades/BBO | Coinbase disposition | Kraken disposition | Pair disposition | Promotion dry-run |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `paired-a046b6d7-56a1-42e5-967b-f06f059143fd` | `0.026742` | `176.207628` | `2977 / 1399 / 1398` | `3468 / 212 / 3201` | `ACCEPTED` | `ACCEPTED` | `ACCEPTED` | `ALLOWED` |
| `paired-b831401f-8be1-4239-a2c5-247a28eeefaa` | `0.013277` | `176.738885` | `2607 / 1214 / 1213` | `2801 / 133 / 2548` | `ACCEPTED` | `ACCEPTED` | `ACCEPTED` | `ALLOWED` |
| `paired-0806e90a-201e-4ee5-89ab-277d4531defd` | `0.014893` | `178.286166` | `2422 / 1120 / 1120` | `2939 / 137 / 2683` | `ACCEPTED` | `ACCEPTED` | `ACCEPTED` | `ALLOWED` |

Archive validation passed for all six venue sessions. Parse errors, exchange errors, and
reconnect counts were zero in all three pilot pairs.

Pilot 3 was selected for applied manifest creation because it had the largest overlap.
Applied manifest:
`data/validated/manifests/validated-paired-0806e90a-201e-4ee5-89ab-277d4531defd.json`

The manifest records policy `2d.2`, relative raw-session paths, raw manifest hashes,
raw shard checksums, session quality report hashes, overlap boundaries, and a content
hash. The manifest remains ignored and is not committed.

## Security And Scope

- Public market data only.
- No API keys or authenticated feeds.
- No account APIs, order APIs, order placement, or trading functionality.
- No normalization, feature engineering, modeling, backtesting, strategy, execution,
  PnL, or live-trading code was added.
- No generated raw archives, quality reports, calibrated reports, or validated manifests
  are tracked.
- Local learning documents remain ignored.

## Regression Tests

Added coverage for:

- Historical 2d.1-shaped policy loading and 2d.2 validation.
- Read-only host-clock observation and prohibited clock-setting commands.
- Dirty-tree calibrated report refusal.
- Expected-commit mismatch refusal.
- Source manifest hash drift refusal.
- Low-variance negative offsets producing informational severity under 2d.2.

## Remaining Limitations

- Three sequential 180-second pilots are not long-horizon stability evidence.
- Sequential runs do not prove time-of-day, weekday/weekend, volatility-regime, or
  liquidity-regime diversity.
- Host-clock status is observed read-only and may be unavailable; no timestamp
  correction is applied.
- Raw duplicates are preserved, not cleaned.
- Accepted data does not imply predictive usefulness.
- No lead-lag conclusion has been tested.

## Phase 3 Recommendation

The minimum Phase 3 entry gate is satisfied by the newly collected accepted pilot
`paired-0806e90a-201e-4ee5-89ab-277d4531defd` and its validated manifest. Phase 3 may
begin only from the validated manifest, not from ignored raw sessions directly.
