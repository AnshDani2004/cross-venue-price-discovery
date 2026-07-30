# Cross Venue Price Discovery and Latency Aware Trading Engine

This repository is a phase-gated research project for studying how information moves
between cryptocurrency venues, beginning with BTC spot markets on Coinbase and Kraken.
The goal is to connect credible quantitative research to realistic simulated trading
without skipping data integrity, timestamp discipline, or risk controls.

## Current Status

- Phase 0: In remediation.
- Phase 1: In remediation.
- Phase 2: Not started.

No collectors, datasets, predictive models, fair-value models, backtests, trading
policies, or execution simulators have been implemented.

## Fixed Initial Scope

- Asset: BTC
- Market type: Spot
- Venue 1: Coinbase
- Venue 2: Kraken
- Initial data focus: trades and top of book

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
```

The CLI intentionally exposes no data collection, model training, backtest, or trading
commands during Phase 0 and Phase 1.

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
- `docs/data_sources.md`
- `docs/data_dictionary.md`
- `docs/experiment_log.md`
- `docs/limitations.md`
- `docs/market_foundations.md`
- `docs/research_protocol.md`
- `docs/risk_register.md`

Local learning notes may exist at `docs/learning_log.md` and
`docs/interview_guide.md`; they are intentionally ignored and not pushed to GitHub.
