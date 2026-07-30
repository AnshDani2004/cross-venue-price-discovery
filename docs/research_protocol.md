# Research Protocol

Review date: 2026-07-30.

This protocol pre-registers the first empirical questions for later phases. It is not a
result report. No market data has been collected and no claim about venue leadership has
been established.

## Fixed Research Universe

- Canonical instrument: `BTC-USD`
- Market type: spot
- Venues: Coinbase `BTC-USD` and Kraken `BTC/USD`
- Data channels: trades and top of book
- Primary ordering basis: local receipt time
- Secondary diagnostic ordering basis: exchange timestamp, with venue caveats
- Response horizons: `100`, `250`, and `500` milliseconds
- Initiating event threshold: absolute one-tick midpoint move

The externalized version of these choices is `configs/research.toml`.

## Principal Research Questions

1. Do one-tick or larger BTC spot midpoint moves on one venue precede same-direction
   midpoint moves on the other venue within 100, 250, or 500 milliseconds?
2. Does trade-flow or top-of-book imbalance at the initiating venue explain more
   response-venue direction than no-change and unconditional-response baselines?
3. Are any detected lead-lag effects robust across chronological holdouts, volatility
   regimes, spread regimes, and documented data-quality exclusions?

These are the only principal Phase 01 questions. Any additional analysis must be labeled
exploratory.

## Event Definition

An initiating event occurs when the initiating venue's top-of-book midpoint changes by at
least one configured tick relative to its previous valid midpoint:

```text
initiating_move_ticks =
  (midpoint_t - midpoint_previous_valid) / tick_size_initiating_venue
```

Rules:

- Events are generated separately for Coinbase and Kraken.
- Primary event time is the local receipt timestamp of the initiating top-of-book update.
- Events require valid best bid, best ask, and positive top-of-book sizes.
- Simultaneous events across venues at the same receipt timestamp are ordered by the
  deterministic timestamp policy and also flagged for robustness analysis.
- Reversals inside the same millisecond window remain separate events only if distinct
  source messages exist.
- Crossed books, empty books, sequence gaps, reconnect warmup intervals, missing
  timestamps, and host-clock outliers are excluded from primary analysis.

## Target Definition

For each initiating event, the response venue is the other venue. At horizon `h`, find
the first valid response-venue top-of-book event at or after:

```text
event_ts + h milliseconds
```

Then compute:

```text
response_return_h =
  response_midpoint(event_ts + h) / response_midpoint(event_ts) - 1
```

The primary classification target is:

```text
direction_target_h = up          if response_return_h > 0
direction_target_h = down        if response_return_h < 0
direction_target_h = unchanged   if response_return_h = 0
```

Rows with no valid response midpoint at the required horizon are excluded from primary
metrics and counted in the data-quality report.

## Hypothesis Register

| ID | Hypothesis | Economic Rationale | First Feature Set | Baseline | Primary Metrics | Rejection / Unsupported Conditions |
| --- | --- | --- | --- | --- | --- | --- |
| H1 | One-tick initiating midpoint moves on one venue are followed by same-direction response-venue moves more often than baseline within 100-500 ms. | Fragmented BTC spot venues may incorporate information at slightly different times. | Initiating venue, move direction, move size in ticks, spread, relative spread, top-of-book depth. | No-change and unconditional response direction. | Directional accuracy lift, balanced accuracy, response return sign rate, confidence intervals. | Reject if lift is not positive on chronological holdout or confidence interval includes no improvement. |
| H2 | Trade-flow and queue-imbalance features improve response direction prediction beyond event direction alone. | Aggressive flow and displayed liquidity can indicate short-lived pressure. | H1 features plus signed trade flow, queue imbalance, microprice deviation, recent OFI. | Event direction only. | Log loss, Brier score, balanced accuracy, calibration error. | Reject if holdout metrics do not beat baseline after multiple-testing correction. |
| H3 | Apparent venue leadership is materially different when ordered by exchange timestamps versus local receipt timestamps. | Exchange clocks and network paths can change perceived causality. | Event rows built under both ordering policies. | Receipt-time ordering as primary. | Leadership share difference, sign consistency, disagreement rate. | Unsupported if disagreement is small, unstable, or driven by data-quality exclusions. |

## Model And Analysis Progression

The project must progress in this order:

1. Data-quality report and descriptive statistics.
2. No-change and unconditional baselines.
3. Simple event-count and response-rate tests.
4. Linear or logistic regression.
5. Regularized linear model.
6. Tree-based model.
7. Advanced time-series or neural models only after earlier models are reported.

No modeling step may skip the baselines.

## Validation Plan

Use chronological splits only:

- Training window: earliest 60% of valid events.
- Validation window: next 20% of valid events.
- Final holdout: latest 20% of valid events, untouched until the final pre-declared
  evaluation for a phase.

For larger datasets, add walk-forward validation with contiguous time blocks. Random
row-level splits are not allowed for primary results because they leak temporal regimes.

## Multiple-Testing Policy

Primary tests are restricted to:

- Three horizons: 100, 250, 500 ms.
- Two initiating venues: Coinbase and Kraken.
- Three registered hypotheses: H1, H2, H3.

Use Benjamini-Hochberg false-discovery-rate control at 5% across the primary family.
Exploratory horizons, features, regimes, or models must be reported separately and cannot
be used as final evidence without a new pre-registration.

## Robustness And Confounders

Report sensitivity to:

- Volatility regime.
- Spread regime.
- Message-rate regime.
- Reconnect and sequence-gap exclusions.
- Host clock offset and jitter.
- Exchange timestamp ordering versus receipt-time ordering.
- Coinbase/Kraken fee and tick-size assumptions.

Known confounders include regional network path, hidden liquidity, queue priority, venue
maintenance, public feed throttling, and exchange-specific timestamp semantics.

## Point-In-Time Rules

- Features may use only information available at or before the event timestamp under the
  declared ordering policy.
- Labels may look forward only after feature rows are fixed.
- Simulated trading decisions may use only frozen model outputs and information available
  at `decision_ts`.
- Execution simulation may use post-decision market data only to determine simulated
  fills, slippage, and realized PnL.
- Any row built by joining venues must preserve the timestamp basis used for the join.

## Experiment Logging

Every experiment must record the fields in `docs/experiment_log.md`, including negative,
null, and inconclusive results.
