# Phase 2B Live Public Collectors Report

Review date: 2026-07-30.

## 1. Starting Branch And Commit

- Phase 2B branch: `phase/02b-live-collectors`
- Starting commit: `fb43109c185a01ca182a7499fe5c298637e8c6cb`
- Working-tree status at branch creation: clean.

## 2. Phase 2A PR And Merge Commit

- Phase 2A pull request: https://github.com/AnshDani2004/cross-venue-price-discovery/pull/2
- Merge status: `MERGED`
- Merged at: `2026-07-30T22:57:31Z`
- Merge commit: `fb43109c185a01ca182a7499fe5c298637e8c6cb`
- CI result before merge: GitHub Actions `test` checks passed.

## 3. Phase 2B Scope

Phase 2B adds bounded public WebSocket smoke collectors for Coinbase and Kraken. The
implementation remains public-only, unauthenticated, and no-write. It does not add raw
archive persistence, manifest file writes, Parquet, DuckDB, SQLite, feature generation,
labels, models, backtests, fair-value estimation, strategy logic, execution simulation,
PnL, positions, or trading functionality.

## 4. Official Sources Reviewed

- Coinbase Exchange WebSocket overview:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/overview
- Coinbase Exchange WebSocket channels:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/channels
- Coinbase Exchange WebSocket rate limits:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/rate-limits
- Coinbase Exchange WebSocket errors:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/errors
- Coinbase Exchange WebSocket best practices:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/best-practices
- Kraken Spot WebSocket introduction:
  https://docs.kraken.com/exchange/guides/websockets/introduction
- Kraken Spot WebSocket v2 trade:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade
- Kraken Spot WebSocket v2 ticker:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker
- Kraken Spot WebSocket v2 heartbeat:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/heartbeat
- Kraken Spot WebSocket v2 status:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/status

No material conflict was found with `configs/venues.toml`, `docs/data_sources.md`, or
the Phase 2A parsers.

## 5. Files Added

- `src/cross_venue/collectors/transport.py`
- `src/cross_venue/collectors/runtime.py`
- `src/cross_venue/collectors/sink.py`
- `src/cross_venue/collectors/retry.py`
- `src/cross_venue/collectors/supervision.py`
- `src/cross_venue/collectors/coinbase/collector.py`
- `src/cross_venue/collectors/coinbase/subscription.py`
- `src/cross_venue/collectors/kraken/collector.py`
- `src/cross_venue/collectors/kraken/subscription.py`
- `tests/live/test_public_smoke.py`
- `tests/unit/test_collector_runtime.py`
- `tests/unit/test_heartbeat_supervision.py`
- `tests/unit/test_in_memory_sink.py`
- `tests/unit/test_live_collectors.py`
- `tests/unit/test_live_subscriptions.py`
- `tests/unit/test_retry_policy.py`
- `tests/unit/test_websocket_transport.py`
- `docs/audits/phase_02b_live_public_collectors_report.md`

## 6. Files Modified

- `CHANGELOG.md`
- `README.md`
- `docs/architecture.md`
- `docs/collection_plan.md`
- `docs/data_sources.md`
- `docs/limitations.md`
- `docs/risk_register.md`
- `docs/storage_plan.md`
- `docs/timestamp_policy.md`
- `pyproject.toml`
- `src/cross_venue/cli.py`
- `src/cross_venue/collectors/__init__.py`
- `src/cross_venue/collectors/kraken/parser.py`
- `tests/fixtures/kraken/unsupported_message.json`
- `tests/unit/test_cli.py`
- `tests/unit/test_collector_contract.py`
- `tests/unit/test_kraken_parser.py`

## 7. Transport Design

`WebSocketConnector` and `WebSocketConnection` are small protocols used by the runtime.
`WebsocketsConnector` is the only production connector and is isolated in
`transport.py`. Tests inject fake connectors and never open external sockets. The
transport enforces open timeout, maximum message size, receive timeout, explicit text or
UTF-8 binary frame handling, and close in `finally`.

## 8. Receipt Timestamp Capture

The runtime awaits `recv_with_timeout`, then immediately calls the injected UTC clock to
capture `local_receipt_ts`. JSON decoding, raw envelope construction, parsing, sink
append, and logging-equivalent summary work happen only after that timestamp is captured.
The venue parsers still receive `local_receipt_ts` externally and do not call the system
clock.

## 9. Coinbase Subscription Behavior

Coinbase sends one public subscription payload:

```json
{"type":"subscribe","product_ids":["BTC-USD"],"channels":["matches","ticker","heartbeat"]}
```

The runtime tracks the `subscriptions` acknowledgement and requires `matches`, `ticker`,
and `heartbeat` for the configured product. Heartbeats and subscription acknowledgements
are control messages, not market events. Coinbase exchange errors containing invalid,
unauthorized, too many, or too big text are terminal for the bounded run.

## 10. Kraken Subscription Behavior

Kraken sends two public subscription payloads:

```json
{"method":"subscribe","params":{"channel":"trade","symbol":["BTC/USD"]}}
```

```json
{"method":"subscribe","params":{"channel":"ticker","symbol":["BTC/USD"],"event_trigger":"bbo"}}
```

The runtime tracks `trade` and `ticker` acknowledgements separately. Automatic heartbeat
and status messages are control liveness. Kraken ticker events do not receive a sequence
or checksum, and `trade_id` remains scoped to trade events.

## 11. Heartbeat Supervision

`HeartbeatSupervisor` tracks monotonic last-frame, last-control, and last-market-event
times. Inactivity uses monotonic time only. Heartbeats and status/control messages prove
connection liveness but are not counted as trade or top-of-book events.

## 12. Reconnection Policy

`RetryPolicy` implements bounded exponential backoff with configurable initial delay,
multiplier, maximum delay, maximum attempts, optional bounded jitter, and stable reset
interval metadata. Phase 2B uses venue reconnect delays from `configs/venues.toml`.
Retryable failures include transport timeout, unexpected temporary connection failures,
and inactivity timeout. Terminal exchange/configuration errors are not retried
indefinitely.

## 13. Shutdown Behavior

Runs stop on duration reached, message limit reached, external stop event, retry budget
exhaustion, terminal runtime failure, or cancellation. Connections are closed in
`finally`. Normal bounded completion transitions to `stopped`; terminal failures produce
`failed` with a visible reason.

## 14. In-Memory Sink

`InMemoryEventSink` stores raw envelopes, normalized market events, control messages,
unsupported messages, and exchange errors in FIFO order. Capacity is required and
positive. Full sinks wait for a configured short timeout and then raise
`SinkBackpressureError`; market events are not silently dropped.

## 15. Session Statistics

`SessionStatistics` tracks frames received, raw envelopes, trade events, top-of-book
events, control messages, unsupported messages, exchange errors, parse errors, reconnect
attempts, connections opened, subscription requests, subscription acknowledgements,
heartbeat messages, first/last receipt timestamps, first/last exchange timestamps, final
state, and failure reason. Statistics remain in memory only.

## 16. Offline Tests

Default offline tests cover transport decoding, sink backpressure, retry delay math,
heartbeat supervision, runtime lifecycle/counters/retry/parse-error behavior,
subscription payloads, venue runtime specs, CLI smoke command behavior, and the existing
Phase 2A parser/contracts.

Offline result:

```text
159 passed, 2 deselected in 1.02s
```

The two deselected tests are opt-in live smoke tests.

## 17. Live Smoke Tests

Marker behavior without environment flag:

```text
2 skipped in 0.15s
```

Opt-in public smoke pytest:

```text
CROSS_VENUE_ENABLE_LIVE_SMOKE=1 .venv/bin/pytest -m live tests/live/
2 passed in 61.15s
```

Bounded CLI smoke results:

| Venue | Connection | Ack | Frames | Trades | Top Of Book | Control | Unsupported | Exchange Errors | Parse Errors | Reconnects | Final State | Stop Reason |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Coinbase | yes | yes | 234 | 101 | 101 | 32 | 0 | 0 | 0 | 0 | stopped | duration reached |
| Kraken | yes | yes | 374 | 7 | 338 | 32 | 0 | 0 | 0 | 0 | stopped | duration reached |

No captured market data was committed or persisted.

## 18. Validation Commands And Exact Results

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pip install -e ".[dev]"` | Passed; editable package installed. |
| `.venv/bin/ruff format .` | Passed; `73 files left unchanged`. |
| `.venv/bin/ruff check .` | Passed; `All checks passed!`. |
| `.venv/bin/ruff format --check .` | Passed; `73 files already formatted`. |
| `.venv/bin/mypy src` | Passed; `Success: no issues found in 32 source files`. |
| `.venv/bin/pytest -m "not live"` | Passed; `159 passed, 2 deselected in 1.02s`. |
| `PATH="$PWD/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files` | Passed all hooks after allowlisting one intentional false-positive dummy `api_key` rejection test. |
| `PATH="$PWD/.venv/bin:$PATH" make check` | Passed; Ruff, format check, mypy, and pytest passed; pytest reported `159 passed, 2 deselected in 1.04s`. |
| `.venv/bin/python -m pip check` | Passed; `No broken requirements found.` |
| `git diff --check` | Passed; no whitespace errors. |

## 19. Security And Privacy Review

Phase 2B uses only public unauthenticated WebSocket endpoints. No API keys, private
endpoints, request signing, order placement, cancellation, account access, transfers,
deposits, withdrawals, positions, or trading functionality were added. The CLI accepts
no credential, output-file, database, or persistence options. Raw envelopes still reject
credential-like payload keys. Pre-commit private-key and detect-secrets hooks passed.

## 20. Remaining Limitations

- Smoke runs are short and do not prove long-duration stability.
- No raw archive, manifest persistence, or checksum pipeline exists.
- Live reconnection failure modes were tested offline but not forced against the real
  exchanges.
- No host clock offset or jitter audit is persisted.
- No data-quality reports, gap repair, deduplication, or persistent promotion exists.
- Exchange schemas and operational behavior may change after this review date.
- Local receipt timestamps include local OS scheduling, event-loop, and runtime effects.

## 21. Phase 2C Readiness Verdict

READY FOR PHASE 2C RAW ARCHIVAL AND MANIFEST PERSISTENCE
