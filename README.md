# BTC/USD Cross-Venue Price Discovery: Coinbase vs Kraken

[![CI](https://github.com/AnshDani2004/cross-venue-price-discovery/actions/workflows/ci.yml/badge.svg)](https://github.com/AnshDani2004/cross-venue-price-discovery/actions/workflows/ci.yml)

An empirical market microstructure study of short-horizon information transmission between Coinbase and Kraken using synchronized BTC/USD trades and top-of-book data.

**Status:** Final confirmatory analysis complete. The repository includes the research pipeline, validation and econometric code, tests, audit documentation, and the deterministic FINAL reporting bundle.

## Research question

When BTC/USD prices move across Coinbase and Kraken, which venue tends to incorporate information first, and is that leadership stable across sessions?

The study separates short-horizon directional predictability from long-run price discovery. It uses a pre-specified, phase-gated workflow designed to reduce lookahead, data-quality leakage, and post-hoc specification changes.

## Main finding

Across 9 econometrically usable sessions, **Coinbase exhibits stronger and more persistent short-horizon price leadership over Kraken**. Coinbase returns Granger-predict Kraken returns in 6 of 9 sessions, against 1 of 9 in the reverse direction. These counts are after a Benjamini-Hochberg correction at a 5% false discovery rate applied jointly to all 18 session-by-direction tests (`results/final/csv/granger_results.csv`, columns `adjusted_p_value`, `decision`, `multiple_testing_method`). Before the correction the counts are 7 of 9 and 2 of 9 at raw p < 0.05; under a Holm or Bonferroni correction over the same 18 tests they stay 6 of 9 and 1 of 9 (audit recomputation from the committed raw p-values). Kraken-to-Coinbase feedback appears in isolated periods, but the reverse-direction evidence is materially weaker in the one-step predictive regressions.

The one-step predictive regressions are weaker at the session level than the Granger tests: the Coinbase coefficient is positive in 8 of 9 sessions but individually significant (HAC p < 0.05) in only 2 of 9. The aggregate Fisher p-values are dominated by one session (`P10`, which has the longest contiguous sample, 7,831 returns); dropping it, the Coinbase-to-Kraken predictive-regression Fisher p-value is about 0.012 instead of 4.3e-16, and the Granger Fisher p-value is about 2e-70 instead of 1.4e-264 (audit recomputation from the committed per-session p-values).

Long-run price-discovery leadership is more heterogeneous. Only 4 of the 9 usable sessions satisfy the frozen rank-one cointegration requirement for VECM-based Gonzalo-Granger and Hasbrouck analysis, and those sessions do not support a claim that Coinbase universally or permanently dominates price discovery.

These results measure directional predictability and price discovery. They do **not** establish structural causation or direct tradability.

## Key results

| Evidence                                    | Coinbase predicts Kraken | Kraken predicts Coinbase |
| ------------------------------------------- | -----------------------: | -----------------------: |
| Econometrically usable sessions             |                        9 |                        9 |
| BH-significant Granger sessions             |                **6 / 9** |                    1 / 9 |
| Aggregate Granger p-value                   |         **1.42175e-264** |              0.000704991 |
| Positive one-step predictive coefficients   |                **8 / 9** |                    7 / 9 |
| Aggregate HAC predictive-regression p-value |           **4.2899e-16** |                0.0904574 |

Additional evidence:

* A fixed economic Coinbase shock produces a positive terminal Kraken response in **8 of 9** usable sessions under both tested Cholesky orderings.
* Johansen cointegration ranks across the 9 usable sessions are: rank 0 in 2 sessions, rank 1 in 4 sessions, and rank 2 in 3 sessions.
* Gonzalo-Granger and Hasbrouck measures are reported only for the 4 rank-one sessions.
* The long-run measures are session-dependent rather than structurally fixed.

Aggregate inference uses Fisher combination of raw per-attempt p-values under the frozen methodology. Aggregate significance should be interpreted alongside the per-session results.

## Results at a glance

### Directional Granger predictability

![Directional Granger predictability](results/final/generated/figures/granger_directional_predictability.png)

### Coinbase shock to Kraken: impulse responses

![Impulse responses](results/final/generated/figures/impulse_responses.png)

### Long-run price discovery

![Long-run price-discovery measures](results/final/generated/figures/price_discovery_by_attempt.png)

The complete result package, including deterministic Parquet tables, browser-friendly CSV exports, figures, provenance identifiers, hashes, and interpretation notes, is available in [`results/final/`](results/final/).

## Dataset

The confirmatory dataset contains:

* **10 accepted paired collection attempts**
* **9 econometrically usable attempts**
* **18,571.366221 seconds** of authoritative paired overlap
* **18,528.188261 seconds** of empirical paired trade overlap
* synchronized BTC/USD public market data from Coinbase and Kraken

**Source.** Public, unauthenticated WebSocket feeds collected by this repository's own collectors: Coinbase Exchange `matches` (trades) and `ticker` (best bid and offer), and Kraken v2 `trade` and `ticker` with `event_trigger=bbo` (`configs/venues.toml`). No vendor data is used.

**Sessions.** Each attempt is a scheduled collection window of about 31 minutes (`requested_duration_seconds = 1860` in `configs/campaigns/`), so the 10 accepted attempts total about 5.2 hours of paired overlap. The scheduled windows fall between 2026-07-31 and 2026-08-08 (UTC); the exact date of the multi-day supplement attempt (`P05`) is not recorded in the committed outputs. Six of the nine usable sessions come from the first multi-day campaign (`...-2026-07-31-v1-*`); the other three are follow-up and supplement attempts. Five minutes are trimmed from each end of every window before synchronization.

**What "econometrically usable" means.** Models are estimated on the single longest unbroken run of valid 100 ms returns in each session, so that lags never bridge a data gap. A return is valid only if both of its 100 ms endpoints are accepted grid points, and a grid point is rejected if either venue's latest quote is more than 2 seconds old, so the run ends at the first such stale point. A session is usable if that run has at least 300 returns (`minimum_effective_observations` in the frozen config). One accepted attempt (`P03`, the attempt in the seven-session snapshot that does not appear in the final nine) fails that rule. Before acceptance, one other attempt (`P08`) was quarantined by the data-quality policy and seven scheduled slots were missed and contributed no data (`docs/audits/phase_03c1_source_snapshot_report.md`).

**Effective sample per session.** The contiguous estimation runs are short: 343 to 7,831 returns per session (about 34 seconds to 13 minutes of 100 ms data), 12,033 returns in total across the nine sessions (`effective_sample_count` in `results/final/csv/granger_results.csv`). The Granger and VAR results therefore rest on roughly 20 minutes of synchronized data, not on the full 5.2 hours of overlap.

Raw market-data archives are intentionally not committed to Git. The repository contains the collection, archival, validation, normalization, and analysis code plus the compact FINAL result artifacts.

## Research design

The project uses a staged research process:

1. **Public data collection**
   Bounded Coinbase and Kraken WebSocket collectors capture trades and top-of-book information.

2. **Raw archival and validation**
   Exact raw frames are stored with manifests, checksums, timestamp diagnostics, continuity checks, recovery tooling, and explicit quality dispositions.

3. **Deterministic normalization**
   Accepted raw sessions are replayed into normalized analysis datasets with validation and provenance tracking.

4. **Synchronization and preliminary analysis**
   Cross-venue series are constructed on a fixed 100 ms UTC grid with backward-only as-of joins (each grid point takes the latest quote at or before it, so no future quote can enter), staleness controls and gap handling.

5. **Frozen econometric analysis**
   Session-level and aggregate inference is computed only after methodology and configuration are fixed.

6. **Deterministic reporting**
   FINAL tables, figures, and the narrative report are generated with a manifest containing SHA-256 hashes and source identifiers.

The audit trail for these stages is preserved under [`docs/audits/`](docs/audits/).

## Econometric methodology

The final analysis includes:

* Augmented Dickey-Fuller stationarity diagnostics
* VAR lag selection using BIC with a frozen maximum lag of 10 grid steps (1 second); the selected lags were 1, 2 or 6 steps (100 ms, 200 ms or 600 ms)
* bidirectional Granger-causality F-tests from the per-session VAR
* Benjamini-Hochberg multiple-testing correction at alpha = 0.05 over one family of 18 tests (9 sessions by 2 directions)
* one-step predictive regressions with HAC/Newey-West covariance
* Fisher aggregation of raw per-attempt p-values
* Johansen cointegration testing
* rank-one VECM estimation where supported
* Gonzalo-Granger permanent-component weights
* Hasbrouck information-share bounds under both Cholesky orderings
* impulse-response analysis under both orderings
* gap-safe sample construction and model-stability diagnostics

The baseline analysis uses a 100 ms sampling interval and a 100 ms return horizon. Methodological choices are frozen in [`configs/research/phase_04c_econometric_analysis.toml`](configs/research/phase_04c_econometric_analysis.toml).

## Long-run interpretation

The long-run results require special care.

Gonzalo-Granger outputs are **signed normalized permanent-component weights** and are not constrained to the interval from zero to one. They should not be interpreted mechanically as percentages.

Hasbrouck information shares are reported as ordering-dependent **bounds**. The frozen methodology does not insert an arbitrary point estimate between the lower and upper bounds.

Because only 4 sessions satisfy the rank-one requirement, the project treats long-run venue leadership as heterogeneous rather than universal.

## Robustness

The committed robustness artifact evaluates **VAR stability** across frozen alternative sampling, horizon, trimming, and ordering configurations.

It should not be interpreted as a comprehensive robustness test of every substantive price-leadership conclusion. In particular, the Granger tests are run only on the 100 ms baseline; the 250 ms and 500 ms sampling and horizon variants record VAR stability, not Granger decisions, so the 6 of 9 count has not been checked at other grid sizes. The project deliberately distinguishes model-stability checks from broader economic robustness claims.

## Reproducibility

The project targets Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the local validation suite:

```bash
python -m ruff check .
python -m pytest -q tests/unit
```

At the release commit the unit suite reported **481 passing tests**, with 3 additional local or live smoke tests skipped by default. Many tests in `tests/unit/test_preliminary_analysis.py` only check that an output table exists and is non-empty; for example `test_no_lookahead_synchronization` does not itself test for lookahead. The no-lookahead property comes from the backward-only as-of join in `src/cross_venue/research/preliminary_analysis.py` (the two `join_asof(..., strategy="backward")` calls), not from that test.

Common project checks are also available through:

```bash
make check
python -m cross_venue --help
python -m cross_venue --version
```

The exact FINAL generated reporting bundle is committed under [`results/final/generated/`](results/final/generated/). Its manifest records the reporting ID, source analysis result ID, dataset validation ID, source snapshot ID, deterministic content hash, and SHA-256 hashes for the generated report, figures, and Parquet tables.

The raw market-data archives and large local analysis datasets are not committed. Reproducing the exact empirical study from raw exchange messages therefore requires the corresponding source data, while the repository itself exposes the collection, validation, normalization, econometric, testing, and reporting implementation.

## Final result artifacts

Useful entry points:

* [`results/final/README.md`](results/final/README.md): interpretation guide and headline results
* [`results/final/generated/econometric_results_report.md`](results/final/generated/econometric_results_report.md): deterministic narrative report
* [`results/final/generated/tables/attempt_summary.md`](results/final/generated/tables/attempt_summary.md): compact session-level summary
* [`results/final/csv/aggregate_inference.csv`](results/final/csv/aggregate_inference.csv): aggregate inference
* [`results/final/csv/granger_results.csv`](results/final/csv/granger_results.csv): session-level Granger results
* [`results/final/csv/predictive_regressions.csv`](results/final/csv/predictive_regressions.csv): HAC predictive regressions
* [`results/final/csv/price_discovery_results.csv`](results/final/csv/price_discovery_results.csv): Gonzalo-Granger and Hasbrouck outputs
* [`results/final/generated/reporting_manifest.json`](results/final/generated/reporting_manifest.json): deterministic provenance and hashes

## Repository structure

```text
configs/        Frozen project, venue, data-quality, normalization, campaign, and research configuration
data/           Ignored raw and normalized data areas plus tiny public placeholders or samples
docs/           Architecture, research protocol, limitations, audit reports, and walkthroughs
notebooks/      Exploratory and report notebook area
reports/        Local generated-report workspace
results/final/  Compact public FINAL result bundle and browser-friendly exports
scripts/        Command wrappers and project utilities
src/            Reusable Python package
tests/          Unit, integration, property, regression, and opt-in smoke tests
```

## Engineering and research safeguards

The repository includes:

* explicit collector lifecycle state machines
* bounded public WebSocket collection
* raw-frame archival with SHA-256 sidecars
* persistent session manifests
* recovery and validation tooling
* quality-policy calibration and acceptance gates
* deterministic normalization
* source snapshotting and provenance identifiers
* backward-only as-of synchronization (no future quotes by construction)
* frozen analysis configuration
* fail-closed FINAL reporting gates
* deterministic artifact hashing
* extensive unit and regression tests

## Limitations

This is a finite-sample study of BTC/USD on two spot venues over a limited set of collection sessions.

* **Small sample.** Nine usable sessions of about 31 minutes each, scheduled within roughly one week (2026-07-31 to 2026-08-08), and six of the nine from one campaign. Each session's models use only its longest unbroken run of 100 ms returns (343 to 7,831 returns, about 20 minutes in total), which by construction is an active stretch in which both venues updated their quotes at least every 2 seconds. Counts such as 6 of 9 are descriptive of these sessions and carry wide uncertainty; one session (`P10`) dominates the aggregate Fisher p-values.
* **Venue clocks and timestamp latency.** Synchronization uses each venue's own exchange timestamp (`exchange_timestamp_utc`), not local receipt time, and no clock-offset correction is applied. The project's own quality diagnostics observed a stable exchange-clock offset that is not corrected (`docs/limitations.md`, Phase 2D.1). A cross-venue clock offset or a difference in how each venue stamps messages of a few tens of milliseconds is comparable to the 100 ms grid and could shift or create an apparent lead. This also departs from `docs/timestamp_policy.md`, which names local receipt time as the primary research clock.
* **Asymmetric quote feeds.** Coinbase top of book comes from the `ticker` channel, which updates on trades (and batches cascading matches, `docs/data_sources.md`), while Kraken's `ticker` is subscribed with `event_trigger=bbo` and updates on best bid or offer changes. The two midquote series are therefore refreshed by different events, which can affect measured lead-lag.
* **Granger is predictive, not causal.** A Granger rejection means past Coinbase returns improve the forecast of Kraken returns at 100 ms to 600 ms lags in that sample. It does not show that Coinbase trading causes Kraken prices to move, and both may respond to a third venue or to common news with different delays.
* **Regime.** One week of summer 2026 BTC/USD; no claim is made about other volatility or liquidity regimes, other times of year, or later market structure. Long-run (VECM) measures are available for only 4 sessions and point in different directions (Coinbase-dominant Hasbrouck bounds in two, Kraken-dominant in one, bounds straddling one half in one).
* **How "frozen" the analysis is.** The methodology file `configs/research/phase_04c_econometric_analysis.toml` was committed together with the analysis code (2026-08-07), after most sessions had been collected, not as a separate pre-registration. A first FINAL run was then invalidated for 15 implementation errors and re-run after repair (`docs/research/phase_04_finalization_repair.md`). The repair kept every threshold and specification unchanged, but the re-run was not blind to the first result.
* **Single specification for the headline count.** The Granger tests use one frozen specification (100 ms grid, BIC lag selection up to 10 lags). They were not re-estimated under the alternative grids in the robustness design.

The findings should not be generalized automatically to:

* other assets or venues
* perpetual futures or derivatives
* all volatility or liquidity regimes
* future market structure
* executable trading profitability

Granger causality is used in its econometric sense of incremental temporal predictability. It does not establish structural, physical, or economic causation.

Observed lead-lag relationships are not assumed to remain profitable after fees, spreads, latency, queue position, market impact, fill uncertainty, and adverse selection.

## No live trading

This repository does not submit real orders, cancel real orders, transfer funds, manage live positions, or require private trading credentials.

The live components are limited to bounded **public market-data collection**. Execution research, if added, must remain simulated.

## Documentation

Core documentation includes:

* [`docs/research_protocol.md`](docs/research_protocol.md)
* [`docs/timestamp_policy.md`](docs/timestamp_policy.md)
* [`docs/data_dictionary.md`](docs/data_dictionary.md)
* [`docs/limitations.md`](docs/limitations.md)
* [`docs/architecture.md`](docs/architecture.md)
* [`docs/research/phase_04_finalization_repair.md`](docs/research/phase_04_finalization_repair.md)
* [`docs/audits/`](docs/audits/)

## License

MIT License. See [`LICENSE`](LICENSE).

---

Built as a reproducible quantitative research project focused on market microstructure, cross-venue information transmission, and disciplined empirical inference.
