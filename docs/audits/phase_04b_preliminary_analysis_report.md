# Phase 4B: Preliminary Price Discovery Analysis Audit Report

**Date**: 2026-08-06
**Snapshot**: `analysis-snapshot-7-session-v1-5f796ab67a5c801c`
**Dataset**: `normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07`

## Overview
This audit report summarizes the findings of the Phase 4B preliminary price discovery analysis on the 7-attempt BTC/USD dataset.

## Execution and Immutability
The analysis pipeline (`analyze-preliminary-price-discovery`) executed deterministically across all seven sessions without mutating the dataset. No forward-looking joins were used. Synchronized cross-venue observations were strictly constructed via backward-looking as-of joins over the `exchange_timestamp_utc`.

## Empirical Observation Overlap vs Paired Overlap
The pipeline successfully preserved the distinction between structural connection time and empirical trade-observation overlap:

* **Authoritative Paired Overlap (Structural)**: 13,005.31 seconds
* **Empirical Trade Observation Overlap**: 12,972.85 seconds

The variance is due to the natural sparsity of trades at the exact edges of the session boundaries.

## Descriptive Statistics
Across the 7 attempts, trade frequency varied substantially by market conditions:
- **Maximum Coinbase Trade Rate**: 31,993 trades (Attempt P10)
- **Minimum Coinbase Trade Rate**: 4,980 trades (Attempt P09)
- **Kraken Trade Rates**: Ranged from 567 to 3,486 trades per session.

Kraken BBO updates (6,148 to 49,681 updates) consistently outnumbered their trade volumes, reflecting strong passive liquidity provisions.

## Cross-Venue Spread and Spread Threshold
Based on a simple 5.0 bps cross-venue midpoint difference threshold, synchronized midpoint deviations were analyzed. Initial approximations using simple threshold scanning revealed stable tracking between Coinbase and Kraken during these sessions.

> [!WARNING]
> This analysis remains strictly preliminary. The dataset remains `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`. The observations here provide robust diagnostic confirmation of the data structure, but they do not make statistically conclusive or final price-discovery claims.
