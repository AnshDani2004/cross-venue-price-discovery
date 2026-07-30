# Architecture

## Objective

The system will study cross-venue BTC price discovery under realistic latency and
execution assumptions. The architecture separates research from trading simulation so
model exploration does not leak into trading-rule optimization.

## Module Boundaries

- `collectors`: venue-specific public market-data ingestion.
- `schemas`: validated event contracts and timestamp semantics.
- `normalization`: conversion from raw venue messages to normalized events.
- `quality`: completeness, ordering, clock, and sequence checks.
- `storage`: partitioned local data layout and analytical query helpers.
- `features`: point-in-time feature generation.
- `labels`: future-return and event-response labels created after features.
- `research`: descriptive statistics and hypothesis tests.
- `models`: predictive model training and evaluation.
- `fair_value`: frozen research model converted into fair-value estimates.
- `strategy`: simulated trading decisions based on fair value, costs, and risk.
- `execution`: simulated order routing, fills, latency, fees, and queue assumptions.
- `risk`: position limits, drawdown controls, and regime-specific constraints.
- `backtest`: point-in-time event replay and performance accounting.
- `reporting`: tables, figures, and reproducible reports.
- `utils`: shared utilities that do not own domain logic.

## Initial Data Flow

```text
Exchange WebSocket message
  -> local receipt timestamp
  -> raw archive
  -> schema validation
  -> normalized event
  -> quality checks
  -> analytical storage
  -> features and labels
  -> research analysis
  -> frozen fair-value model
  -> simulated strategy and execution
  -> risk and performance reports
```

## Phase 2A Offline Parser Flow

Phase 2A implements the deterministic contract layer that sits between future public
WebSocket clients and later storage. It does not open sockets, reconnect, write datasets,
or promote records into research tables.

```text
Already-received public JSON payload
  -> caller-supplied local receipt timestamp
  -> RawMessageEnvelope
  -> Coinbase or Kraken offline parser
  -> ParseResult
  -> normalized trade, normalized top-of-book, control, unsupported, or exchange error
  -> future raw archive and SessionManifest accounting
```

## Phase 2B Live Public Collector Flow

Phase 2B wraps the offline parser contracts with bounded public WebSocket transport. It
still does not write raw files, normalized datasets, manifests, features, labels, models,
or trading outputs.

```text
Public WebSocket
  -> injectable transport
  -> receive frame
  -> immediate local_receipt_ts capture
  -> safe JSON decode
  -> RawMessageEnvelope in memory
  -> existing venue parser
  -> bounded in-memory sink
  -> in-memory session statistics
  -> concise no-write summary
```

## Timestamp Contract

Every event must preserve:

- Exchange timestamp
- Local receipt timestamp
- Processing timestamp
- Decision timestamp
- Simulated order submission timestamp
- Simulated order arrival timestamp
- Simulated fill timestamp

The first three timestamps describe observation. The remaining timestamps are
simulation-only and must never be populated during raw data collection. See
`docs/timestamp_policy.md` and `configs/timestamp_policy.toml` for ordering rules.

## Configuration Contracts

Phase 01 has four public, validated configuration files that Phase 2A parsers align
with:

- `configs/project.toml`: safe project defaults for environment, paths, timezone, and log level.
- `configs/venues.toml`: Coinbase and Kraken public WebSocket endpoints, symbols, channels,
  channel-specific timestamp/sequence/checksum fields, heartbeat policy, reconnect bounds,
  and documentation review dates.
- `configs/research.toml`: registered research horizons, initiating venues, target type,
  sampling method, baseline, exclusions, holdout policy, and multiple-testing policy.
- `configs/market_rules.toml`: dated fee, tick-size, and minimum-order assumptions with
  official sources.

## Phase 00 Scope

Phase 00 defines structure and contracts only. It does not connect to exchanges, collect
data, estimate lead-lag relationships, backtest, or report strategy performance.

## Phase 01 Scope

Phase 01 defines market foundations for the initial two-venue BTC spot universe. It adds
research hypotheses and config validation, but still does not connect to exchanges or
produce market results.

## Phase 02 Boundary

Phase 2B implements bounded live public collection for the documented trade and
top-of-book channels only. Raw archive writes, persistent manifests, long-duration
stability evidence, and quality reports remain future Phase 2C work. Phase 2 must not
add authenticated exchange clients, order submission, backtests, model training,
fair-value estimation, or trading strategy logic.
