# Collection Plan

Review date: 2026-07-30.

This plan bounds Phase 2 after Phase 2A offline contracts. The parser contracts,
lifecycle state machine, and manifest model exist; live public collection and file writes
do not.

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

## Pilot Sessions

| Session | Duration | Venues | Channels | Purpose |
| --- | ---: | --- | --- | --- |
| Connectivity smoke | 5 minutes | Coinbase, Kraken | Heartbeat/control plus configured public channels | Verify subscriptions, receipt timestamps, and raw archive writes. |
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
