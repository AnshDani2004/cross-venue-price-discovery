# Cross Venue Price Discovery and Latency Aware Trading Engine

This repository is a phase-gated research project for studying how information moves
between cryptocurrency venues, beginning with BTC spot markets on Coinbase and Kraken.

The project connects the full workflow:

1. Market observation
2. Hypothesis formation
3. Data collection
4. Data validation
5. Statistical analysis
6. Fair value estimation
7. Trading decision
8. Execution simulation
9. Risk management
10. Performance evaluation

No live trading is implemented or permitted. All eventual trading logic must remain
simulation-only unless the repository objectives are explicitly changed and reviewed.

## Current Phase

Phase 00: Project foundation.

This phase creates the repository scaffold, baseline documentation, and validated event
schemas needed before exchange collectors are implemented. It does not collect data,
run backtests, estimate signals, or report performance.

## Development

The project targets Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
make check
```

## Research Discipline

The project treats timestamp integrity as a first-class constraint. Future phases must
distinguish exchange timestamps, local receipt timestamps, processing timestamps,
decision timestamps, simulated order submission timestamps, and simulated fill
timestamps.

Negative and inconclusive experiments belong in `docs/experiment_log.md`; they should
not be hidden or optimized away.

