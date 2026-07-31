# Collection Plan

Review date: 2026-07-30.

This plan bounds Phase 2 after Phase 2C raw archival. Parser contracts, live transport,
lifecycle state machine, rotating raw writer, persistent manifests, quality summaries,
validation, and partial recovery exist. Normalized dataset promotion does not.

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

## Phase 2C Bounded Persistence Smoke Procedure

Run one venue at a time:

```bash
python -m cross_venue smoke-archive --venue coinbase --duration-seconds 20 --max-messages 2000
python -m cross_venue smoke-archive --venue kraken --duration-seconds 20 --max-messages 2000
python -m cross_venue validate-archive --session-path <session_path_under_data/raw>
python -m cross_venue recover-session --session-path <session_path_under_data/raw>
```

Hard limits:

- Maximum Phase 2C persistence smoke duration: 30 seconds.
- Default persistence smoke duration: 20 seconds.
- Default frame limit: 2000.
- Live persistence tests are opt-in with `CROSS_VENUE_ENABLE_LIVE_PERSISTENCE=1`.
- Generated archives, manifests, quality summaries, checksums, and partials stay under
  ignored `data/raw`.

Record for each archival run: session path, frame count, normalized event counts, parser
errors, reconnect attempts, shard count, archive bytes, checksum status, partial count,
manifest path, quality summary path, and validation status.

## Phase 2D Controlled Paired Quality Procedure

Run Coinbase and Kraken together on the same host:

```bash
python -m cross_venue collect-paired-quality --duration-seconds 120 --max-messages-per-venue 20000
python -m cross_venue promote-dataset --paired-report data/quality/paired/<paired_collection_id>/paired_quality_report.json
```

The paired command creates one paired collection ID, starts both public collectors
concurrently, archives each venue independently, validates both archives, analyzes both
sessions, measures local-receipt-time overlap, and writes a paired quality report under
ignored `data/quality`. Promotion is dry-run by default and writes no transformed market
data.

Acceptance requires archive validation, reconciled counters, sufficient duration,
sufficient frames and top-of-book events, acceptable parse-error rate, receipt-time
integrity, acceptable duplicate and continuity diagnostics, no critical quote failures,
and configured cross-venue overlap. Quarantined and rejected sessions are not promoted.

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
