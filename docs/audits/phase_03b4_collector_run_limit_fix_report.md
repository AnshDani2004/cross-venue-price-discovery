# Phase 3B.4 Collector Run-Limit Fix Report

Review date: 2026-07-31.

## Scope

Phase 3B.4 removes the remaining collector-internal stopping condition that caused
campaign collections to end near 5,000 Coinbase frames even when the campaign and
paired-quality layer requested `100,000` messages per venue.

This phase does not begin Phase 3C and does not reclassify historical excluded attempts.

## I04 Evidence

I04 is preserved exactly as historical evidence:

- Attempt ID: `btc-usd-coinbase-kraken-2026-07-31-intraday-v1-I04-001`
- Runtime: `88357ba2c355b37b841044a7f204b25985ed896a`
- Requested duration: `1,860` seconds
- Recorded campaign message limit: `100,000`
- Actual duration: `485.256187` seconds
- Coinbase frames: `5,001`
- Kraken frames: `4,907`
- Coinbase disposition: `ACCEPTED`
- Kraken disposition: `ACCEPTED`
- Paired disposition: `ACCEPTED`
- Paired overlap: `409.127347` seconds
- Required overlap: `1,800` seconds
- Status: `REJECTED`
- Inclusion: `EXCLUDED`
- Exclusion reason: `INSUFFICIENT_PAIRED_OVERLAP: observed=409.127, required=1800`

The I04 Coinbase and Kraken manifests both recorded `failure_reason =
in-memory sink capacity exhausted` and `stop_reason = terminal failure`.

## Root Cause

The campaign and paired-quality code passed the requested `RunLimits` correctly:

- `duration_seconds = 1860`
- `max_messages = 100000`
- `max_phase_duration_seconds = 3600`

The remaining cap was not in `RunLimits`. It was the default diagnostic sink inside both
venue collector wrappers:

- `src/cross_venue/collectors/coinbase/collector.py`
- `src/cross_venue/collectors/kraken/collector.py`

Before this fix, each live collector constructed `InMemoryEventSink(max_items=10_000)`.
That sink stores raw envelopes and parsed outputs. Coinbase commonly emits a raw
envelope plus a market/control item for the same frame, so the 10,000-item sink capacity
can fail at roughly 5,001 frames. Kraken hit the same sink limit at a different frame
count because its parsed item mix differs.

## Corrected Runtime Semantics

Archival campaign collection now uses `DiscardingEventSink` by default unless a caller
explicitly injects a sink. This preserves the finite collector bounds while avoiding a
diagnostic-memory cap as a hidden production stop condition.

Dry-run and smoke paths without archival persistence still use the bounded
`InMemoryEventSink(max_items=10_000)`.

Collectors now expose typed stop reasons:

- `REQUESTED_DURATION_REACHED`
- `MESSAGE_LIMIT_REACHED`
- `PHASE_DURATION_LIMIT_REACHED`
- `REMOTE_DISCONNECT`
- `LOCAL_ERROR`
- `CANCELLED`
- `UNKNOWN`

Future campaign attempts record:

- `coinbase_effective_duration_limit_seconds`
- `kraken_effective_duration_limit_seconds`
- `coinbase_effective_message_limit`
- `kraken_effective_message_limit`
- `coinbase_stop_reason`
- `kraken_stop_reason`

Historical I01 through I04 records remain unchanged.

## Off-By-One Analysis

The collector message predicate checks `frames_received >= limits.max_messages` before
the next receive. Regression coverage now proves a requested limit of `5` processes no
more than `5` counted frames, and a requested limit of `5,000` processes no more than
`5,000` counted frames.

I04 stopped at `5,001` Coinbase frames because the sink held more than one diagnostic
item per frame, not because the message predicate was `> 5000`.

## Regression Coverage

New focused tests cover:

- Coinbase and Kraken exact message-limit stopping at `5`.
- Coinbase and Kraken `5,000`-message limits not stopping before the threshold.
- Coinbase and Kraken `100,000`-message limits proceeding beyond `5,000`.
- Duration-first, message-first, and phase-limit-first stop reasons.
- Full campaign-to-paired-collection-to-collector-runtime path with a `100,000` message
  limit.
- Full campaign acceptance path creating an included validated manifest.
- Excluded-attempt migration compatibility for the collector-internal limit fix.

Focused validation before final migration:

```bash
.venv/bin/python -m pytest tests/unit/test_collector_runtime.py tests/unit/test_campaign_duration.py tests/unit/test_campaigns.py tests/unit/test_cli.py -q
```

Result: `82 passed, 2 skipped`.

Non-live validation before final migration:

```bash
.venv/bin/pytest -m "not live and not live_persistence and not live_quality and not live_calibration and not local_validated_data and not campaign_smoke and not local_campaign_data" -q
```

Result: `274 passed, 8 deselected`.

## Campaign Migration

The final corrected runtime commit and append-only campaign migration events are recorded
after the implementation commit. The required migration reason is
`COLLECTOR_INTERNAL_MESSAGE_LIMIT_FIX`.

## Remaining Limitations

- The first corrected live slot still needs to prove public-feed behavior beyond
  historical I04 thresholds under current market conditions.
- A `100,000` message limit remains a finite safety bound and can still be reached in an
  unusually high message-rate regime.
- Stop-reason diagnostics are recorded only for future attempts; historical attempts are
  not rewritten.
