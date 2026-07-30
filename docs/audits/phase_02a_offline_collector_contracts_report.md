# Phase 2A Offline Collector Contracts Report

Review date: 2026-07-30.

## 1. Starting Branch And Commit

- Branch: `phase/02-data-collectors`
- Starting commit: `7c4ec6feb361a8c83ad1118141d7364ff6e157ca`
- Starting commit subject: `fix: align timestamp and venue sequencing contracts`
- Initial working tree: clean before Phase 2A edits.

## 2. Scope

Phase 2A implemented offline, deterministic collector contracts and parsers for the
existing BTC spot Coinbase/Kraken public market-data scope. It did not implement live
networking, subscriptions, reconnection, heartbeat monitoring, raw archive writes,
Parquet writes, DuckDB persistence, features, labels, models, backtests, strategy logic,
execution simulation, authenticated exchange access, or live trading.

Official source review used:

- Coinbase Exchange WebSocket channels:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/channels
- Coinbase Exchange WebSocket errors:
  https://docs.cdp.coinbase.com/exchange/websocket-feed/errors
- Kraken Spot WebSocket v2 trade:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade
- Kraken Spot WebSocket v2 ticker:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker
- Kraken Spot WebSocket v2 heartbeat:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/heartbeat
- Kraken Spot WebSocket v2 status/control reference:
  https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/status

## 3. Files Added

- `src/cross_venue/collectors/__init__.py`
- `src/cross_venue/collectors/base.py`
- `src/cross_venue/collectors/coinbase/__init__.py`
- `src/cross_venue/collectors/coinbase/parser.py`
- `src/cross_venue/collectors/exceptions.py`
- `src/cross_venue/collectors/kraken/__init__.py`
- `src/cross_venue/collectors/kraken/parser.py`
- `src/cross_venue/collectors/lifecycle.py`
- `src/cross_venue/collectors/manifest.py`
- `src/cross_venue/collectors/parsing.py`
- `src/cross_venue/schemas/events.py`
- `src/cross_venue/schemas/raw.py`
- `src/cross_venue/schemas/top_of_book.py`
- `src/cross_venue/schemas/trade.py`
- Coinbase fixture JSON files under `tests/fixtures/coinbase/`
- Kraken fixture JSON files under `tests/fixtures/kraken/`
- `tests/unit/test_coinbase_parser.py`
- `tests/unit/test_collector_contract.py`
- `tests/unit/test_collector_lifecycle.py`
- `tests/unit/test_kraken_parser.py`
- `tests/unit/test_normalized_events.py`
- `tests/unit/test_session_manifest.py`
- `docs/audits/phase_02a_offline_collector_contracts_report.md`

## 4. Files Modified

- `CHANGELOG.md`
- `README.md`
- `docs/architecture.md`
- `docs/collection_plan.md`
- `docs/data_dictionary.md`
- `docs/data_sources.md`
- `docs/limitations.md`
- `docs/storage_plan.md`
- `docs/timestamp_policy.md`
- `src/cross_venue/cli.py`
- `src/cross_venue/schemas/__init__.py`

## 5. Collector Interface Design

`MarketDataCollector` is a `Protocol` defining venue, canonical instrument,
venue-native symbol, session ID, lifecycle state, `start`, `stop`, and `parse_message`.
Parsers require `local_receipt_ts` as an explicit argument. The default `run_live`
method raises `LiveCollectorNotImplemented`, keeping Phase 2A offline while documenting
the future live boundary.

## 6. Lifecycle Design

`CollectorState` defines `created`, `starting`, `running`, `stopping`, `stopped`, and
`failed`. `CollectorLifecycle` is immutable and validates explicit transitions.
`CREATED -> STOPPED` is allowed for cancellation before startup, and `STOPPED -> STOPPED`
is allowed for idempotent repeated stops. Invalid transitions raise
`InvalidCollectorStateTransition`.

## 7. Raw-Envelope Design

`RawMessageEnvelope` is a frozen Pydantic model with strict extra-field rejection. It
preserves venue, instrument, venue symbol, channel, message type, original JSON payload,
local receipt timestamp, session ID, schema version, optional exchange timestamp, and
optional raw sequence value. Payloads must be JSON-compatible and must not contain
credential-like keys.

## 8. Normalized-Event Design

`NormalizedTrade` and `NormalizedTopOfBook` share immutable event metadata:
venue, canonical instrument, venue symbol, event type, exchange timestamp, local receipt
timestamp, collector session ID, source channel, schema version, raw message type, and
optional raw sequence/checksum values. Prices and quantities use `Decimal`. Trades
require positive price and quantity. Top-of-book events require positive prices,
nonnegative sizes, and strictly non-crossed/non-locked bid/ask prices. No midpoint,
spread, microprice, or imbalance is calculated in this phase.

## 9. Coinbase Fixture Coverage

Fixtures cover valid `match`, valid `ticker`, `heartbeat`, `subscriptions`, exchange
`error`, unsupported public message, wrong product, missing required field, invalid
numeric field, and invalid timestamp. Coinbase `side` is treated as maker side, so maker
`sell` maps to buyer aggressor and maker `buy` maps to seller aggressor.

## 10. Kraken Fixture Coverage

Fixtures cover trade snapshot, trade update, multiple trades in source order, ticker
snapshot, ticker update, heartbeat, subscription acknowledgement, exchange error,
unsupported public message, wrong symbol, missing required field, invalid numeric field,
and invalid timestamp. Kraken ticker events intentionally have no sequence or checksum.
Kraken `trade_id` is scoped only to trade events.

## 11. Session-Manifest Design

`SessionManifest` is a frozen typed model for future collection summaries. It validates
nonempty session ID, venue, instrument, channels, UTC-aware timestamp ranges, final
state, collector version, git commit, schema version, nonnegative counters, and optional
first/last exchange and receipt timestamps. `make_session_id` accepts venue, canonical
instrument, timestamp, and injected UUID factory so tests remain deterministic.

## 12. Error-Handling Policy

- Malformed supported messages raise `MessageParseError`.
- Valid but out-of-scope public messages return `UnsupportedPublicMessage`.
- Wrong Coinbase product or Kraken symbol returns a nonfatal unsupported result.
- Heartbeats and subscription acknowledgements return `ParsedControlMessage`.
- Exchange error payloads return `ExchangeErrorMessage`.
- Parsers never return ambiguous `None` and never fabricate missing market fields.

## 13. Tests Added

- Collector contract tests
- Lifecycle transition tests
- Raw envelope validation tests
- Normalized trade and top-of-book validation tests
- Coinbase fixture parser tests
- Kraken fixture parser tests
- Session manifest and session ID tests

All tests use fixed timezone-aware timestamps and local fixture files.

## 14. Validation Results

Required commands were run from `/Users/ansh/Developer/cross-venue-price-discovery`.

| Command | Result |
| --- | --- |
| `.venv/bin/python -m pip install -e ".[dev]"` | Passed; editable package installed. |
| `.venv/bin/ruff format .` | Passed; final rerun reported `55 files left unchanged`. |
| `.venv/bin/ruff check .` | Passed; `All checks passed!`. |
| `.venv/bin/ruff format --check .` | Passed; `55 files already formatted`. |
| `.venv/bin/mypy src` | Passed; `Success: no issues found in 23 source files`. |
| `.venv/bin/pytest` | Passed; `131 passed in 0.27s`. |
| `PATH="$PWD/.venv/bin:$PATH" .venv/bin/pre-commit run --all-files` | Passed all hooks, including Ruff, mypy, pytest, large-file, private-key, and detect-secrets checks. |
| `PATH="$PWD/.venv/bin:$PATH" make check` | Passed; Ruff, format check, mypy, and pytest all passed; pytest reported `131 passed in 0.22s`. |
| `.venv/bin/python -m pip check` | Passed; `No broken requirements found.` |
| `git diff --check` | Passed; no whitespace errors. |
| `git status --short` | Showed only intended Phase 2A edits before commit. |

Network review:

- `rg` over tests found no socket, DNS, HTTP client, or connection calls. Hits were
  existing endpoint string validation tests and path resolution tests only.
- `rg` over Phase 2A collectors and parser tests found no `websockets.connect`,
  `aiohttp`, or `connect(` usage.
- Parsers and parser tests contain no `datetime.now`, `datetime.utcnow`, `time.time`, or
  equivalent current-clock calls.

## 15. Security And Privacy Review

No credentials, private keys, account identifiers, order endpoints, private channels, or
authenticated trading functionality were added. Raw envelopes reject credential-like
payload keys. Fixture files are small hand-curated public-message examples and contain no
private data. Pre-commit private-key and detect-secrets hooks passed.

Search review notes:

- Credential-term hits are the explicit raw-envelope denylist, secret-safety tests, and
  older audit/security documentation.
- Trading-action hits are existing docs/tests that prohibit live trading or discuss
  future simulated execution risk.
- `websockets` remains a declared dependency/config topic, but no live WebSocket connect
  call exists.

## 16. Remaining Limitations

- Fixtures cannot prove live-feed stability.
- Network timing is not measured.
- Reconnection, heartbeat monitoring, rate-limit handling, and ping/pong behavior are not
  implemented.
- Raw archive writes and manifest file writes are not implemented.
- No data has been collected.
- Parser schemas may need updates if official Coinbase or Kraken public message schemas
  change after this review date.
- No models, features, labels, backtests, fair-value estimates, strategy logic, execution
  simulation, PnL, or position tracking exists.

## 17. Phase 2B Readiness Verdict

READY FOR PHASE 2B LIVE PUBLIC COLLECTOR IMPLEMENTATION
