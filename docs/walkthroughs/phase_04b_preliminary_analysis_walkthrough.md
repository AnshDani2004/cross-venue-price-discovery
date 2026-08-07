# Phase 4B Preliminary Analysis Walkthrough

1. Configured the CLI command `analyze-preliminary-price-discovery` with `--dataset-root`, `--validation-report`, and `--derived-root`.
2. Implemented core schema validation and structure for JSON report generation.
3. Synchronized book logic via Polars `join_asof` backward-looking joining was successfully run.
Phase 4B now includes:

* per-attempt descriptive statistics;
* backward-only synchronized BBO sampling;
* spread statistics;
* exploratory lead-lag diagnostics;
* exploratory leader diagnostics;
* robustness analysis;
* deterministic derived outputs;
* seven-session exploratory limitation;
* no causal, VAR, or final Granger conclusions.
