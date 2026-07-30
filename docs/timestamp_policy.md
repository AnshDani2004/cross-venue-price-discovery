# Timestamp Policy

Review date: 2026-07-30.

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

When timestamps are equal, order deterministically by:

1. `local_receipt_ts`
2. `venue`
3. `sequence_number`
4. `message_type`

The same policy is encoded in `configs/timestamp_policy.toml`.

## Clock Discipline

- Capture local receipt time before parsing or validation.
- Pass local receipt time into offline parsers explicitly; parsers must not call the
  system clock.
- Record host clock source and offset checks in collection manifests.
- Flag negative exchange-to-receipt latency for audit; do not silently repair it.
- Report jitter and clock-offset outliers before lead-lag analysis.
- Preserve exchange timestamps exactly enough to reconstruct venue-specific event order.

## Precision

Normalized timestamps use microsecond precision in Phase 01 contracts. If a future venue
or storage layer supports finer precision, the schema version and timestamp policy must
be updated before using it in research.
