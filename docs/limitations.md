# Limitations

## Phase 00

- No market data has been collected.
- No exchange adapters have been implemented.
- No latency measurements have been observed.
- No order-book reconstruction logic exists yet.
- No lead-lag analysis, model training, backtest, or simulated execution has been run.
- Local development currently depends on a Python 3.12+ environment for the project target.

## Known Research Risks

- Exchange timestamps may have different semantics across venues.
- Local receipt timestamps depend on host clock accuracy and network path.
- WebSocket feeds can drop messages or disconnect.
- Book-derived signals are unreliable without sequence and checksum validation.
- Apparent lead-lag relationships can disappear after fees, spread, latency, and adverse
  selection.

