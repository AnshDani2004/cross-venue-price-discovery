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

## Phase 2C Raw Archival Flow

Phase 2C adds opt-in persistence around the same bounded public collectors. Receipt
timestamp capture remains immediately after `recv()` and before JSON decoding.

```text
Public WebSocket
  -> receive frame
  -> immediate local_receipt_ts capture
  -> exact raw archive record
  -> bounded writer queue
  -> rotating JSONL shard
  -> SHA-256 sidecar
  -> persistent manifest and quality summary
  -> archive validation or partial recovery
  -> existing JSON decode and parser path
```

## Phase 2D Quality Flow

Phase 2D treats Phase 2C raw archives as immutable evidence and writes separate quality
artifacts.

```text
Immutable raw archive
  -> archive integrity validation
  -> session quality analysis
  -> duplicate, continuity, timestamp, quote, and coverage diagnostics
  -> cross-venue overlap analysis
  -> ACCEPTED / QUARANTINED / REJECTED disposition
  -> dry-run promotion
  -> validated dataset manifest only when all sessions and the pair are accepted
```

## Phase 3A Normalization Flow

Phase 3A starts only from a finalized validated dataset manifest and replays immutable
raw archive records through the existing venue parsers.

```text
Validated dataset manifest
  -> source manifest and shard hash verification
  -> deterministic raw archive replay
  -> existing Coinbase/Kraken parsers
  -> normalized trade and top-of-book rows
  -> raw-record normalization outcomes
  -> strict reconciliation
  -> explicit-schema Parquet files
  -> normalization manifest and semantic hashes
  -> DuckDB inspection views
```

Phase 3A does not compute features, labels, lead-lag statistics, models, backtests,
execution simulation, PnL, or trading signals.

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

Phase 2D implements data-quality validation and controlled paired collection for the
documented public trade and top-of-book channels only. Feature engineering, labels,
models, backtests, fair-value estimation, and trading simulation remain future work.
Phase 2 must not add authenticated exchange clients, order submission, or trading
strategy logic.

## Phase 03A Boundary

Phase 3A creates deterministic analytical storage from accepted raw data. It preserves
raw duplicates and emits one raw-record outcome per source record. Research conclusions
remain out of scope until later phases.

## Phase 03B Campaign Flow

Phase 3B adds an operational campaign layer around the existing public collectors,
archive validation, quality reports, validated manifests, and normalization pipeline.

```text
Campaign config
  -> fixed schedule
  -> append-only attempt ledger
  -> derived campaign registry
  -> paired public collection
  -> archive validation
  -> quality analysis
  -> individual validated pair manifests
  -> campaign completion validation
  -> validated campaign manifest
  -> multi-session normalization
```

The ledger is the audit trail; the registry is a derived current-state view. Every
accepted, quarantined, rejected, failed, aborted, and missed attempt remains visible.
Phase 3B does not add research features, lead-lag analysis, backtests, execution
simulation, PnL, authenticated APIs, or trading.
