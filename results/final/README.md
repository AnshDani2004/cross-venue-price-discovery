# Final Econometric Results

This directory contains the public FINAL results for the BTC/USD cross-venue price-discovery study of Coinbase and Kraken.

The confirmatory dataset contains 10 accepted paired collection attempts. Nine attempts satisfy the frozen minimum-sample and contiguous-segment requirements for econometric analysis. One accepted attempt is retained in the dataset but is not econometrically usable.

## Main finding

Across the econometrically usable sessions, Coinbase exhibits stronger and more persistent short-horizon price leadership over Kraken. Feedback from Kraken to Coinbase appears in isolated periods, while long-run price-discovery leadership varies across sessions rather than remaining structurally fixed.

The results support directional predictability, not structural or economic causation.

## Key results

| Evidence | Coinbase predicts Kraken | Kraken predicts Coinbase |
|---|---:|---:|
| Econometrically usable sessions | 9 | 9 |
| BH-significant Granger sessions | 6 / 9 | 1 / 9 |
| Aggregate Granger p-value | 1.42175e-264 | 0.000704991 |
| Positive one-step predictive coefficients | 8 / 9 | 7 / 9 |
| Aggregate HAC predictive-regression p-value | 4.2899e-16 | 0.0904574 |

The aggregate tests use Fisher combination of raw per-attempt p-values under the frozen Phase 4C methodology. Aggregate significance does not imply that every individual session exhibits the same relationship.

A fixed economic Coinbase shock produces a positive terminal Kraken response in 8 of the 9 usable sessions under both tested Cholesky orderings.

## Long-run price discovery

Johansen cointegration diagnostics are available for all 9 econometrically usable sessions:

- Rank 0: 2 sessions
- Rank 1: 4 sessions
- Rank 2: 3 sessions

Gonzalo-Granger and Hasbrouck price-discovery measures are reported only for the 4 rank-one sessions, where the frozen VECM requirement is satisfied.

Gonzalo-Granger values are signed normalized permanent-component weights. They are not constrained to the interval from zero to one and therefore should not be interpreted mechanically as percentages.

Hasbrouck information shares are reported as ordering-dependent lower and upper bounds. No methodology-frozen point estimate is inserted between those bounds.

The long-run results are heterogeneous across sessions and do not support a claim that Coinbase universally or permanently dominates price discovery.

## Generated bundle

`generated/` is the exact deterministic Phase 4D reporting output.

- Analysis mode: `FINAL`
- Final inference permitted: `true`
- Reporting ID: `report-6442f4c6e7df6790`
- Source analysis result ID: `9b9a99c19105811c`
- Dataset validation ID: `validation-report-f62c52f63e66d45b`
- Source snapshot ID: `analysis-snapshot-10-session-v1-9ac4e58f7ae79db6`
- Deterministic content hash: `6442f4c6e7df67902e9d5c4f71cefc1b41af084eb98059ece9ee09937e7bbdef`

The SHA-256 hashes of the generated report, figures, and Parquet tables are recorded in `generated/reporting_manifest.json`.

The files under `csv/` are browser-friendly exports of the corresponding Parquet tables. They are convenience derivatives and are not part of the original deterministic reporting manifest.

## Figures

### Directional Granger predictability

![Directional Granger predictability](generated/figures/granger_directional_predictability.png)

### Impulse responses

![Impulse responses](generated/figures/impulse_responses.png)

### Long-run price-discovery measures

![Long-run price-discovery measures](generated/figures/price_discovery_by_attempt.png)

### VAR stability

![VAR stability](generated/figures/robustness_summary.png)

The robustness artifact evaluates VAR stability across the frozen alternative configurations. It should not be interpreted as a comprehensive robustness test of every substantive price-leadership conclusion.

## Detailed outputs

For the complete generated narrative report, see
[`generated/econometric_results_report.md`](generated/econometric_results_report.md).

For a compact per-attempt summary, see
[`generated/tables/attempt_summary.md`](generated/tables/attempt_summary.md).

For browser-friendly data:

- [`csv/aggregate_inference.csv`](csv/aggregate_inference.csv)
- [`csv/attempt_summary.csv`](csv/attempt_summary.csv)
- [`csv/cointegration_results.csv`](csv/cointegration_results.csv)
- [`csv/granger_results.csv`](csv/granger_results.csv)
- [`csv/predictive_regressions.csv`](csv/predictive_regressions.csv)
- [`csv/price_discovery_results.csv`](csv/price_discovery_results.csv)
- [`csv/robustness_results.csv`](csv/robustness_results.csv)

## Interpretation limits

Granger causality is used here in its econometric sense of incremental temporal predictability. It does not establish economic, structural, or physical causation.

The sample covers a finite set of BTC/USD Coinbase and Kraken collection sessions. Results should not be generalized to all market regimes, assets, venues, or future periods.

Long-run price-discovery estimates are conditional on rank-one cointegration and are therefore available for only 4 of the 9 econometrically usable sessions.

The project does not claim that the statistically observed lead-lag relationships are directly tradable after fees, spread, latency, market impact, queue position, and execution uncertainty.
