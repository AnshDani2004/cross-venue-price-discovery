# Contributing

This project is phase-gated. Each phase should have a clear objective, tests, updated
documentation, and an honest limitations section before review.

## Ground Rules

- Do not add live trading integrations.
- Do not commit credentials or restricted raw market data.
- Do not fabricate results or mark unrun checks as passing.
- Preserve point-in-time semantics in features, labels, and simulated trading decisions.
- Log failed, negative, and inconclusive experiments in `docs/experiment_log.md`.

## Local Checks

```bash
make check
```

If a command cannot be run locally, report it as `Not run` with the reason.

