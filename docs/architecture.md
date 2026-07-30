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

## Timestamp Contract

Every event must preserve:

- Exchange timestamp
- Local receipt timestamp
- Processing timestamp
- Decision timestamp
- Simulated order submission timestamp
- Simulated fill timestamp

The first three timestamps describe observation. The final three are simulation-only and
must never be populated during raw data collection.

## Phase 00 Scope

Phase 00 defines structure and contracts only. It does not connect to exchanges, collect
data, estimate lead-lag relationships, backtest, or report strategy performance.

## Phase 01 Scope

Phase 01 defines market foundations for the initial two-venue BTC spot universe. It adds
research hypotheses and config validation, but still does not connect to exchanges or
produce market results.
