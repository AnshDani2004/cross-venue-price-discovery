# Research Protocol

## Research Questions

The first reliable research phase should answer descriptive questions before prediction:

1. Which venue updates first during observable BTC spot price moves?
2. How long does the apparent lag last after accounting for local receipt timestamps?
3. Do results change across high-volatility or low-liquidity periods?
4. Are findings stable across collection days?

## Model Progression

The project must progress in this order:

1. Descriptive statistics
2. Naive baseline
3. Linear or logistic regression
4. Regularized linear model
5. Tree-based model
6. Advanced time-series model
7. Neural model only when justified

## Point-In-Time Rules

- Features may use only data available at or before the feature timestamp.
- Labels may look forward, but they must be built after feature timestamps are fixed.
- Trading decisions may use only frozen model outputs and information available at
  `decision_ts`.
- Execution simulation may use post-decision market data only to determine simulated fills,
  slippage, and realized PnL.

## Experiment Logging

Every experiment should record:

- Hypothesis
- Data interval and venue universe
- Feature set
- Label definition
- Model or statistic
- Costs and latency assumptions
- Commands run
- Results
- Negative findings
- Follow-up questions

