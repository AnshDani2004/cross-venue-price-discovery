# Timestamp Policy

Review date: 2026-07-31.

All normalized event timestamps must be timezone-aware UTC. Naive datetimes are rejected
instead of coerced because silent timezone assumptions can invert lead-lag conclusions.

## Required Timestamp Chain

```text
exchange_ts
  <= local_receipt_ts
  <= processing_ts
  <= decision_ts
  <= simulated_order_submission_ts
  <= simulated_order_arrival_ts
  <= simulated_fill_ts
```

The first three timestamps describe market-data observation. The final four are
simulation-only and must remain null during raw collection and normalization.

## Ordering Rules

Primary research ordering uses `local_receipt_ts` because a model cannot act on a message
before it reaches the process. Exchange timestamps are preserved for diagnostics and
venue reconstruction, but they are not the primary tradability clock.

Phase 2D cross-venue overlap is measured with `local_receipt_ts`, not exchange time.
`local_receipt_ts - exchange_ts` is named `observed_exchange_receipt_delta`; it is not
true network latency because it includes exchange clock offset, network delay, operating
system scheduling, event-loop scheduling, runtime boundaries, and timestamp precision
differences.

When timestamps are equal, order deterministically by:

1. `local_receipt_ts`
2. `venue`
3. `sequence_number`
4. `message_type`

The same policy is encoded in `configs/timestamp_policy.toml`.

## Clock Discipline

- Capture local receipt time immediately after a WebSocket receive operation returns and
  before JSON decoding, schema validation, logging, or parsing.
- In Phase 2C, create and enqueue the exact raw archive record immediately after that
  receipt timestamp capture and before JSON decoding.
- Pass local receipt time into offline parsers explicitly; parsers must not call the
  system clock.
- Record host clock source and offset checks in collection manifests.
- Flag negative observed exchange-receipt deltas for audit; do not silently repair them
  or label them one-way latency.
- Flag nonmonotonic receipt timestamps in raw archive record order; do not sort or repair
  the archive.
- Keep connection epochs and reconnect boundaries as quality metadata rather than
  automatically stitching sequence continuity across reconnects.
- Report jitter and clock-offset outliers before lead-lag analysis.
- Preserve exchange timestamps exactly enough to reconstruct venue-specific event order.

## Phase 2D.1 Calibration

Policy 2d.2 treats stable or low-variance negative
`observed_exchange_receipt_delta` patterns as clock/feed diagnostics rather than
automatic quarantine. This does not correct exchange timestamps, estimate true network
latency, or prove clock synchronization. Host-clock observations are read-only and may
be unavailable when the platform requires administrator access.

## Precision

Normalized timestamps use microsecond precision in Phase 01 contracts. If a future venue
or storage layer supports finer precision, the schema version and timestamp policy must
be updated before using it in research.

Phase 3A Parquet tables store UTC Arrow timestamps and preserve raw record order through
`source_raw_record_index`. Phase 3A applies no clock-offset correction, venue-clock
alignment, or latency inference.
