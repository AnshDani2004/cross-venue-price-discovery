# Research Protocol

## Research Questions

The first reliable research phase should answer descriptive questions before prediction:

1. Which venue updates first during observable BTC spot price moves?
2. How long does the apparent lag last after accounting for local receipt timestamps?
3. Do results change across high-volatility or low-liquidity periods?
4. Are findings stable across collection days?

## Hypothesis Register

| ID | Hypothesis | Earliest Phase That Can Test It |
| --- | --- | --- |
| H1 | Coinbase and Kraken BTC spot midpoint returns are highly correlated over short horizons. | Phase 06 |
| H2 | Apparent venue leadership is not constant across all market regimes. | Phase 06 |
| H3 | Ordering by local receipt timestamp can change measured lead-lag relationships relative to exchange timestamp ordering. | Phase 06 |
| H4 | Cross-venue signals may be statistically detectable but economically weak after spread, fees, latency, and fill uncertainty. | Phase 09 |

Hypotheses must be evaluated against pre-declared data intervals and logged whether the
results are positive, negative, or inconclusive.

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
- Any row built by joining venues must preserve the timestamp basis used for the join.
- When exchange-time and receipt-time orderings disagree, both cases should be reported
  before drawing venue-leadership conclusions.

## Initial Universe Constraints

- Use BTC spot only.
- Include exactly Coinbase `BTC-USD` and Kraken `BTC/USD` until Phase 02 collectors and
  Phase 04 data-quality checks are reliable.
- Do not add perpetual futures before the two-venue spot pipeline has passed validation.

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
