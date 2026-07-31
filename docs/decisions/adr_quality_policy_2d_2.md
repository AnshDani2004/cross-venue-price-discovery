# ADR: Quality Policy 2d.2

Date: 2026-07-31

## Status

Accepted for Phase 2D.1 calibration.

## Context

Policy 2d.1 correctly preserved raw evidence but used broad warning gates for negative
observed exchange-receipt deltas, Coinbase sequence diagnostics, exact raw-frame
duplicates, and stale quote intervals. The quarantined paired collection
`paired-36289696-9fde-4b08-9a07-694b1328ecc5` showed that those broad gates mixed
different mechanisms:

- Stable or low-variance exchange-clock offsets were treated like timestamp failures.
- Coinbase product sequence jumps were treated as subscribed-message loss even though
  this project subscribes only to `matches`, `ticker`, and `heartbeat`.
- Kraken heartbeat/ticker duplicate frames inflated an aggregate duplicate rate.
- Quote age was treated like feed inactivity even when controls or market activity were
  still present.

## Decision

Policy 2d.2 keeps all original metrics and raw evidence, but changes disposition logic
to typed, venue-aware findings:

- Observed exchange-receipt deltas are classified as offset patterns and are not named
  latency.
- Coinbase product-level sequence jumps are diagnostic under partial subscription unless
  heartbeat or trade correspondence evidence indicates missing subscribed messages.
- Kraken duplicate handling separates heartbeat, status, subscription acknowledgements,
  ticker raw/semantic duplicates, trade raw duplicates, identical trade IDs, and
  conflicting trade IDs.
- Quote freshness separates quote age from connection inactivity, heartbeat-healthy
  quiet intervals, market activity without BBO change, and Coinbase match/ticker
  correspondence.

## Official Basis

- Coinbase heartbeats include sequence and `last_trade_id`; Coinbase also documents that
  `matches` messages can be dropped and that `ticker` batches cascading matches:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/channels
- Kraken ticker supports `event_trigger=bbo`, where BBO changes drive ticker updates:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker
- Kraken heartbeats are automatic liveness messages with no other payload:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/heartbeat
- Kraken trade IDs are unique per book for trade messages:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade

## What Did Not Change

- Raw archives are not modified.
- Duplicate raw frames are not dropped.
- Quotes are not interpolated.
- Sequence gaps are not repaired.
- Timestamps are not rewritten.
- Promotion still requires accepted venue reports, accepted pair reports, validated
  archives, checksums, and minimum overlap.

## Consequences

2d.2 reduces false-positive quarantine from known public-feed semantics while preserving
warnings for unstable offsets, confirmed missing match evidence, conflicting trade
identity, critical integrity failures, and insufficient coverage.

Remaining uncertainty: the calibration evidence is short and sequential. It does not
prove time-of-day diversity, predictive usefulness, or robustness across volatility
regimes.

## Rollback

Historical 2d.1-shaped policies remain loadable. Reverting `configs/data_quality.toml`
to `policy_version = "2d.1"` restores broad warning behavior without raw-data migration.
