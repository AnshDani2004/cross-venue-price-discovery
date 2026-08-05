# Cross Venue Price Discovery and Latency Aware Trading Engine

This repository is a phase-gated research project for studying how information moves
between cryptocurrency venues, beginning with BTC spot markets on Coinbase and Kraken.
The goal is to connect credible quantitative research to realistic simulated trading
without skipping data integrity, timestamp discipline, or risk controls.

## Current Status

- Phase 0: Complete after remediation.
- Phase 1: Complete after remediation.
- Phase 2A: Offline collector contracts, deterministic parsers, lifecycle state
  machine, session manifest model, and fixture tests implemented.
- Phase 2B: Bounded live public Coinbase and Kraken WebSocket collectors implemented
  with in-memory dry-run sinks and opt-in smoke tests.
- Phase 2C: Exact raw WebSocket archival, rotating JSONL shards, SHA-256 sidecars,
  persistent manifests, quality summaries, validation, recovery, and opt-in persistence
  smoke tests implemented.
- Phase 2D: Data-quality validation implemented with session quality reports,
  duplicate/continuity/timestamp/quote diagnostics, paired overlap reports,
  explicit dispositions, aggregation, dry-run promotion, and opt-in live quality tests.
- Phase 2D.1: Quality calibration complete with policy 2d.2; at least one paired
  dataset was accepted and manifested. Phase 3 normalization may begin on the validated
  manifest only.
- Phase 3A: Deterministic normalization implemented; accepted raw data can be replayed
  into validated Parquet and DuckDB datasets. Exploratory research has not started.
- Phase 3B: Campaign infrastructure implemented for a fixed multi-session Coinbase and
  Kraken BTC-USD collection campaign. The multi-day collection campaign is in progress.
  No exploratory price-discovery conclusions have been produced.

No predictive models, fair-value models, backtests, trading policies, or execution
simulators have been implemented.

## Fixed Initial Scope

- Asset: BTC
- Market type: Spot
- Venue 1: Coinbase
- Venue 2: Kraken
- Initial data focus: trades and top of book
- Coinbase channels: `matches`, `ticker`, and `heartbeat`
- Kraken channels: `trade` and `ticker` with `event_trigger=bbo`

Perpetual futures, additional assets, additional venues, neural networks, reinforcement
learning, and live trading are out of scope for the initial phases.

## Learning Goals

Quantitative research goals:

- Form falsifiable market microstructure hypotheses.
- Preserve point-in-time data integrity.
- Define features, labels, baselines, metrics, and validation before modeling.
- Report negative, null, and inconclusive results honestly.

Quantitative trading goals:

- Separate fair-value estimation from trading decisions.
- Account for spread, fees, latency, fills, and risk before discussing tradability.
- Keep all execution work simulated.
- Avoid tuning research to produce attractive PnL.

## No Live Trading

This repository must not submit real orders, cancel real orders, transfer funds, manage
live positions, or require private trading credentials. Public market-data planning is
allowed; live execution is not.

## Installation

The project targets Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## CLI Usage

```bash
python -m cross_venue --help
python -m cross_venue --version
python -m cross_venue smoke-collect --venue coinbase --duration-seconds 30 --max-messages 500 --public-only --no-write
python -m cross_venue smoke-collect --venue kraken --duration-seconds 30 --max-messages 500 --public-only --no-write
python -m cross_venue smoke-archive --venue coinbase --duration-seconds 20 --max-messages 2000
python -m cross_venue validate-archive --session-path data/raw/venue=coinbase/instrument=BTC-USD/date=<YYYY-MM-DD>/session=<session_id>
python -m cross_venue recover-session --session-path data/raw/venue=coinbase/instrument=BTC-USD/date=<YYYY-MM-DD>/session=<session_id>
python -m cross_venue analyze-session-quality --session-path data/raw/venue=coinbase/instrument=BTC-USD/date=<YYYY-MM-DD>/session=<session_id>
python -m cross_venue collect-paired-quality --duration-seconds 120 --max-messages-per-venue 20000
python -m cross_venue reanalyze-calibrated-pair --paired-report data/quality/paired/<paired_collection_id>/paired_quality_report.json
python -m cross_venue promote-dataset --paired-report data/quality/paired/<paired_collection_id>/paired_quality_report.json
python -m cross_venue normalize-dataset --validated-manifest data/validated/manifests/<validated_manifest>.json
python -m cross_venue validate-normalized-dataset --normalization-manifest data/normalized/dataset=<normalized_dataset_id>/manifest/normalization_manifest.json
python -m cross_venue build-normalized-catalog --normalization-manifest data/normalized/dataset=<normalized_dataset_id>/manifest/normalization_manifest.json
python -m cross_venue init-collection-campaign --campaign-config configs/campaigns/phase_3b_btc_usd.toml
python -m cross_venue campaign-status --campaign-id btc-usd-coinbase-kraken-2026-07-31-v1
python -m cross_venue run-campaign-slot --campaign-id btc-usd-coinbase-kraken-2026-07-31-v1 --slot-id P01
```

The smoke collector is bounded, public-only, and no-write. It prints an in-memory
summary and does not persist raw frames or normalized events. The `smoke-archive`
command is the explicit opt-in persistence path; it writes exact raw frames, manifests,
quality summaries, and checksums under ignored `data/raw`.

## Common Commands

```bash
make lint
make format
make format-check
make typecheck
make test
make check
python -m pip check
```

`make check` runs Ruff linting, Ruff format verification, mypy, and pytest.

## Repository Structure

```text
configs/        Validated local configuration examples
data/           Ignored raw, normalized, feature, manifest, and sample areas
docs/           Architecture, research protocol, data, risk, and audit documents
notebooks/      Exploratory and report notebooks that call production modules
reports/        Ignored generated research and trading outputs
scripts/        Future command wrappers
src/            Reusable Python package code
tests/          Unit, integration, property, regression, and fixture tests
```

## Reproduction

From a clean checkout with Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
make check
python -m cross_venue --help
python -m cross_venue --version
python -m pip check
```

## Documentation

- `docs/architecture.md`
- `docs/collection_plan.md`
- `docs/data_sources.md`
- `docs/data_dictionary.md`
- `docs/experiment_log.md`
- `docs/limitations.md`
- `docs/market_foundations.md`
- `docs/research_protocol.md`
- `docs/risk_register.md`
- `docs/storage_plan.md`
- `docs/timestamp_policy.md`

## Next Phase

Phase 3 may begin only from accepted sessions referenced by a validated dataset manifest.
Research modeling, backtesting, fair-value estimation, and live trading have not started.

Local learning notes may exist at `docs/learning_log.md` and
`docs/interview_guide.md`; they are intentionally ignored and not pushed to GitHub.
