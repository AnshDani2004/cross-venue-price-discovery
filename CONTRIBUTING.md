# Contributing

This project is phase-gated. Each change should make the repository more reproducible,
safer, or more explicit. Do not begin a later phase before the current phase passes its
acceptance checks.

## Environment Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Branch Naming

Use descriptive branches:

```text
phase/00-project-foundation
phase/01-market-foundations
remediation/phase-00-01-readiness
docs/research-protocol-update
test/config-validation
```

## Commit Conventions

Use conventional commit messages:

```text
feat: add validated project settings
fix: enforce formatting in CI
test: cover invalid research horizons
docs: define timestamp policy
```

Avoid vague messages such as `updates`, `changes`, or `final`.

## Required Checks

Run these before review:

```bash
make lint
make format-check
make typecheck
make test
make check
python -m pip check
pre-commit run --all-files
```

If a command is not run, record `NOT RUN` and the reason.

## Pull Requests

Every pull request should include:

- Objective and phase
- Files changed
- Tests added or updated
- Commands run
- Actual results
- Documentation updates
- Remaining limitations
- Data or security implications

## Data Handling

- Do not commit raw market data.
- Do not commit generated Parquet, DuckDB, model, or report artifacts unless explicitly
  designated as tiny fixtures.
- Store data manifests separately from raw payloads.
- Keep restricted data out of public artifacts.

## Safety Rules

- No live trading integrations.
- No authenticated order submission, cancellation, deposits, withdrawals, or position
  management.
- No credentials in committed files.
- No fabricated test results, backtest results, latency measurements, or performance
  claims.
- No tuning research merely to produce attractive PnL.

## Documentation Expectations

Update docs when behavior, assumptions, configuration, data fields, risks, or phase
status change. Negative and inconclusive experiments belong in `docs/experiment_log.md`.
