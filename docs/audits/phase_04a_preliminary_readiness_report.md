# Phase 4A: Preliminary Readiness Report

## Executive Summary

This report documents the preliminary empirical readiness analysis of the 7-session normalized dataset (`normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07`). The Phase 4A diagnostics tool verified that the paired overlapping sessions satisfy the boundary requirements for exploratory empirical readiness.

> [!WARNING]
> This dataset has been declared `ELIGIBLE` for **preliminary exploratory research** only. It holds only 7 verified paired sessions, and thus the final composite status remains `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`. The dataset cannot be used for the final Granger Causality or Vector Autoregression outputs.

## Preliminary Readiness Result

The immutable seven-attempt dataset is `PRELIMINARY_READY` for exploratory
analysis.

All 7 accepted attempts exceed the campaign-compatible minimum of 1,800 seconds
of per-attempt trade-observation overlap.

The aggregate trade-observation overlap calculated from normalized trade
timestamps is approximately 12,972.85 seconds.

This is distinct from the official validated campaign paired overlap of
13,005.314148 seconds recorded by the campaign and quality artifacts.

The two values use different boundaries:

- Validated campaign paired overlap uses the validated collection and quality
  artifact boundaries.
- Trade-observation overlap uses the intersection of observed trade timestamps
  in the normalized Coinbase and Kraken trade files.

The trade-observation overlap is used for Phase 4A exploratory readiness
diagnostics. The validated campaign paired overlap remains the authoritative
measure for the final 18,000-second collection requirement.

## Scope and Limitations

`PRELIMINARY_READY` means that the dataset is structurally valid and suitable
for exploratory price-discovery diagnostics.

It does not mean that the final multi-day empirical composite is complete.

The immutable snapshot contains:

- 7 accepted attempts
- 14 venue sessions
- Approximately 12,972.85 seconds of trade-observation overlap
- 13,005.314148 seconds of official validated campaign paired overlap

The final composite still requires:

- 10 accepted attempts
- At least 18,000 seconds of official validated paired overlap

F01 was accepted after this snapshot was created and is not included in the
Phase 4A report. Including F01, current collection progress is provisionally
8 accepted attempts. Two additional accepted attempts remain necessary.
