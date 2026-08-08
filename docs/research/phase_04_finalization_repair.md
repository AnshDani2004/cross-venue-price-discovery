# Phase 04 Finalization Repair

## Status

The previously generated FINAL Phase 4C result
`128f9956ab685e42` is invalidated for scientific inference.

The underlying final 10-session normalized dataset remains valid.

## Reasons for invalidation

1. Phase 4B primary synchronization rejected backward-as-of observations when
   either venue's latest quote was older than 50 ms, despite a separately
   declared 2000 ms stale threshold. This caused severe sample attrition and
   conditioned the primary sample on near-immediate quote updates.

2. Phase 4C series diagnostics hard-coded effective_duration to zero.

3. Phase 4C longest_contiguous_segment was assigned usable_return_pairs rather
   than calculated from contiguous timestamp runs.

4. Phase 4C 250 ms sampling and return-horizon robustness specifications used
   integer floor row stepping and therefore executed as 200 ms on the 100 ms
   baseline grid.

5. Gap detection used a fixed 300 ms threshold for every sampling frequency.

6. Multi-step returns did not reject all returns whose full horizon crossed a
   data gap.

7. no_additional_trim changed only a label and did not reconstruct an
   untrimmed sample.

8. kraken_first changed only a label and did not change variable ordering.

9. Frozen ADF configuration fields were not faithfully consumed.

10. Frozen Johansen configuration fields were not faithfully consumed.

11. Gonzalo-Granger used the Johansen eigenvector as both beta and alpha
    rather than estimating a VECM adjustment matrix.

12. Hasbrouck information shares were scaffolded from the Gonzalo-Granger
    result rather than calculated from common-factor innovation variance.

13. Predictive regressions used HC3 rather than the frozen Newey-West/HAC
    covariance specification and did not implement both directions.

14. Fisher combined p-values and configured aggregate robustness were not
    implemented.

15. Phase 4C report overlap totals were hard-coded rather than derived from
    input artifacts.

## Repair policy

No statistical threshold will be relaxed to obtain significance or increase
the number of usable sessions.

### Contiguous-segment estimation policy

Phase 4C time-series estimators must not create artificial temporal
adjacency by concatenating observations across synchronization gaps,
rejected support, or missing return endpoints.

For each attempt and robustness configuration:

- descriptive `usable_return_pairs` continues to count all individually
  valid return observations;
- return-based time-series models use the earliest longest consecutive
  run of jointly valid Coinbase and Kraken returns;
- Johansen and VECM estimation use the earliest longest timestamp-contiguous
  level segment defined by the frozen Phase 4C gap rule;
- the minimum effective observation threshold is evaluated against the
  actual contiguous model sample rather than the sum of disconnected
  valid observations;
- ties between equally long segments are resolved deterministically by
  selecting the earliest segment.

This policy does not alter the frozen sampling intervals, return horizons,
gap threshold, minimum observation threshold, lag-selection rules, or
statistical significance thresholds.

### Inference aggregation and multiple-testing policy

The frozen Phase 4C multiple-testing family is interpreted as the
direction-by-attempt hypothesis family within each specification. Because
the confirmatory Granger analysis is currently produced for the baseline
specification, the existing Benjamini-Hochberg correction across all
baseline direction-by-attempt Granger hypotheses is retained unchanged.

The frozen aggregation rule requires Fisher combined p-values across
attempts. Aggregate inference is therefore reported separately from
per-attempt inference in `aggregate_inference.parquet`.

Fisher combination uses raw attempt-level p-values, not
Benjamini-Hochberg-adjusted p-values. Aggregation is performed separately
for each analysis and direction:

- Granger causality, Coinbase predicts Kraken.
- Granger causality, Kraken predicts Coinbase.
- Predictive regression, Coinbase predicts Kraken.
- Predictive regression, Kraken predicts Coinbase.

Only estimable attempt-level results contribute to Fisher aggregation.
Failed or non-estimable attempts are excluded rather than imputed.
Each contributing attempt enters Fisher's statistic once; observation
counts do not weight the combined p-value.

Configured aggregate robustness is reported in
`robustness_results.parquet` using `scope = "aggregate"`. Numeric
robustness values use arithmetic equal-attempt weighting across estimable
attempts. Per-attempt observation counts do not influence this aggregate.
The number of contributing attempts is stored separately as
`contributing_attempt_count`; `effective_sample_count` remains reserved
for observation counts and is null at aggregate scope.

This repair does not alter the frozen significance level, multiple-testing
method, family definition, robustness configurations, model estimators,
or minimum observation threshold.

### VAR and impulse-response ordering policy

Phase 4C treats variable ordering as a model specification rather than
reporting metadata.

The baseline VAR ordering is Coinbase first, Kraken second. The frozen
`kraken_first` robustness configuration reverses the actual VAR input
matrix to Kraken first, Coinbase second.

Orthogonalized impulse responses use Cholesky identification and therefore
depend on variable ordering. The frozen impulse-response specification
requires both Coinbase-first and Kraken-first orderings to be evaluated.

For each ordering, array indices are mapped back to the original economic
venue identities. A Coinbase shock and Kraken response therefore represent
the same economic quantities under both Cholesky orderings even though
their matrix indices reverse.

The Kraken-first impulse-response model uses the same selected VAR lag as
the baseline ordering so that the ordering comparison changes only the
Cholesky/model variable order rather than the lag specification.

This repair does not change the frozen VAR lag-selection rule, impulse
response horizon, return construction, statistical thresholds, or
robustness configuration set.

### Predictive-regression covariance and directionality

The frozen Phase 4C predictive-regression specification is interpreted as
one-step bidirectional OLS prediction with Newey-West/HAC covariance
estimation.

The predictive models are estimated separately as:

- Kraken return at time t predicting Coinbase return at time t+1,
  controlling for Coinbase return at time t;
- Coinbase return at time t predicting Kraken return at time t+1,
  controlling for Kraken return at time t.

The frozen `predictive_regression.lag` field is interpreted as the
Newey-West/HAC covariance bandwidth and is passed as the HAC `maxlags`
parameter. It does not redefine the one-step prediction horizon or
predictor lag.

Both directional regressions use the same deterministic contiguous return
sample required by the Phase 4C time-series estimation policy. Reported
effective sample counts therefore reflect the actual lagged regression
sample rather than the total number of individually usable returns.

This repair replaces the historical HC3 covariance implementation and
one-direction-only regression without changing the frozen prediction
horizon, predictor lag, statistical significance threshold, or underlying
return construction.

### VECM deterministic-term interpretation

The frozen Johansen specification remains `johansen_det_order = 0`. For
rank-one VECM estimation in statsmodels, Phase 4C maps this constant case to
`deterministic="co"`, meaning an unrestricted constant outside the
cointegration relation.

This mapping is an implementation interpretation of the already-frozen
Johansen deterministic case. It does not change the statistical threshold,
cointegration lag order, rank decision rule, or any result-dependent
parameter.

The following remain frozen:

- alpha = 0.05
- minimum_effective_observations = 300
- VAR lag-selection criterion = BIC
- multiple-testing method = Benjamini-Hochberg FDR
- equal-attempt weighting
- declared robustness configuration IDs

The original 50 ms freshness restriction will remain reproducible as an
explicit sensitivity analysis, but it will no longer define the primary
backward-as-of sample.

No Phase 4D reporting or final empirical interpretation is permitted until
the corrected Phase 4B and Phase 4C pipelines pass their full validation
gates.
