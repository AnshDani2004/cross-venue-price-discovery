# Collection Plan

Review date: 2026-07-30.

This plan bounds Phase 2 before any collector exists. It covers public market data only.

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

- Raw public data is collected for both venues.
- Every raw file has a manifest checksum.
- Local receipt timestamps are captured before parsing.
- Basic reconnect and error accounting exists.
- No credentials or private endpoints are introduced.
