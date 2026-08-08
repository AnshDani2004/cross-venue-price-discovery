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
