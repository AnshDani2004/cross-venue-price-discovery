# Limitations

## Phase 00

- No market data has been collected.
- No exchange adapters have been implemented.
- No latency measurements have been observed.
- No order-book reconstruction logic exists yet.
- No lead-lag analysis, model training, backtest, or simulated execution has been run.
- Local development currently depends on a Python 3.12+ environment for the project target.

## Phase 01

- Market-foundation hypotheses are pre-analysis assumptions, not empirical findings.
- Coinbase and Kraken symbol conventions, channels, endpoint choices, and timestamp fields
  are documented but no live message parsing has been implemented.
- Fee, tick-size, and minimum-order values are dated assumptions and must be revalidated
  before any PnL or execution simulation.
- Kraken full-depth book checksum handling and Coinbase `level2` reconstruction are
  intentionally deferred.
- Public feed timestamps may not be unique, synchronized, or directly comparable across
  venues.
- No conclusion can yet be drawn about venue leadership, latency, liquidity, or tradable
  edge.

## Known Research Risks

- Exchange timestamps may have different semantics across venues.
- Local receipt timestamps depend on host clock accuracy and network path.
- WebSocket feeds can drop messages or disconnect.
- Book-derived signals are unreliable without sequence and checksum validation.
- Apparent lead-lag relationships can disappear after fees, spread, latency, and adverse
  selection.
- Multiple-testing risk remains high until registered hypotheses, horizons, and final
  holdout handling are enforced on real data.
