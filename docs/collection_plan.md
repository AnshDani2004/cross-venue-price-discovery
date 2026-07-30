# Collection Plan

Review date: 2026-07-30.

This plan bounds Phase 2 after Phase 2B live public smoke collectors. Parser contracts,
the live transport, lifecycle state machine, manifest model, and bounded in-memory dry
runs exist; file writes do not.

## Phase 2A Offline Validation

Before any socket is opened, Phase 2A requires:

- Deterministic parser tests for hand-curated Coinbase and Kraken fixtures.
- Caller-supplied `local_receipt_ts`; parsers must not read the system clock.
- Explicit non-event results for heartbeats, subscription acknowledgements, unsupported
  public messages, and exchange error messages.
- Strict rejection of malformed numerics, missing required fields, timezone-naive
  timestamps, locked/crossed top-of-book events, and credential-like raw payload keys.
- A `SessionManifest` model with counters and timestamp ranges, but no manifest file
  writer yet.

## Phase 2B Bounded Smoke Procedure

Run one venue at a time:

```bash
python -m cross_venue smoke-collect --venue coinbase --duration-seconds 30 --max-messages 500 --public-only --no-write
python -m cross_venue smoke-collect --venue kraken --duration-seconds 30 --max-messages 500 --public-only --no-write
```

Hard limits:

- Maximum Phase 2B smoke duration: 120 seconds.
- Default smoke duration: 30 seconds.
- Default frame limit: 500.
- No output file, database, or raw archive option exists.
- Live smoke tests are opt-in with `CROSS_VENUE_ENABLE_LIVE_SMOKE=1`.

Record for each smoke run: endpoint, subscription request sent, acknowledgement status,
first frame time, normalized event counts, control counts, parse errors, unsupported
messages, reconnect attempts, final state, and actual duration.

## Pilot Sessions

| Session | Duration | Venues | Channels | Purpose |
| --- | ---: | --- | --- | --- |
| Connectivity smoke | 30 seconds per venue | Coinbase, Kraken | Heartbeat/control plus configured public channels | Verify subscriptions, receipt timestamps, parser reuse, and no-write summaries. |
| Short pilot | 30 minutes | Coinbase, Kraken | Trades and top of book | Estimate message rates, disk usage, schema failures, and reconnect behavior. |
| Research pilot | 6 hours | Coinbase, Kraken | Trades and top of book | Validate manifests, data-quality reports, and event construction. |

Do not begin multi-day collection until the 6-hour pilot has clean manifests and
documented exclusion intervals.

## Session Manifest Requirements

Each session manifest must include:

- Collector session ID.
- Git commit and package version.
- Python version and operating system.
- Config file checksums.
- Venue endpoint, symbol, and channels.
- Start and end timestamps in UTC.
- Raw file paths and SHA-256 checksums.
- Message counts by venue, channel, and message type.
- Reconnect counts and reasons.
- Sequence-gap, checksum, parse-error, and timestamp-error counts.
- Host clock offset/jitter audit summary.
- Disk usage summary.

## Operational Limits

- Stay below official public WebSocket rate and subscription limits.
- Use exponential backoff bounded by venue config.
- After disconnects, mark warmup intervals before resuming primary research rows.
- Rotate raw files by session, venue, channel, and time window.
- Stop collection if disk usage exceeds the configured local limit.

## Phase 2 Exit Requirements

Phase 2 can pass only after:

- Offline parser contracts continue to pass against deterministic fixtures.
- Raw public data is collected for both venues.
- Every raw file has a manifest checksum.
- Local receipt timestamps are captured before parsing.
- Basic reconnect and error accounting exists.
- No credentials or private endpoints are introduced.
