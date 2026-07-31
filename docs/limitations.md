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

## Phase 2A

- Offline parsers are validated only against deterministic fixtures, not live exchange
  traffic.
- No WebSocket connection loop, reconnect policy, heartbeat monitor, ping/pong handling,
  or rate-limit behavior has been implemented.
- `SessionManifest` is a typed contract only; no manifest file writer or checksum
  pipeline exists yet.
- No raw, normalized, feature, label, or report dataset has been produced.
- Parser schemas may need revision if Coinbase or Kraken public payloads change after
  the 2026-07-30 documentation review.
- Local receipt timestamps are supplied by parser callers in tests; no host-clock audit
  or latency measurement exists yet.

## Phase 2B

- Live observations are bounded smoke tests only, not long-duration stability evidence.
- No raw, normalized, manifest, feature, label, or report data is persisted.
- Internet routing, DNS, TLS, exchange load, and local runtime scheduling are not
  deterministic.
- Local receipt time includes operating-system scheduling and Python runtime effects.
- Bounded reconnection is tested offline, but live reconnection behavior depends on
  external network and exchange failure modes.
- Exchange schemas may change after the 2026-07-30 documentation review.

## Phase 2C

- Raw archival has been validated with bounded 20-second public smoke tests only; it is
  not long-duration stability evidence.
- Archives preserve exact frames, but normalized dataset promotion and cross-session
  quality gates are not implemented yet.
- Host clock offset and jitter are not yet measured in manifests.
- Sequence gap and duplicate detection counters are placeholders for later data-quality
  validation.
- Raw shards are uncompressed JSONL in Phase 2C, so longer controlled collection needs
  disk monitoring before use.
- Recovery handles valid JSONL prefixes in partial shards, but has not been exercised
  against process-kill crash drills.

## Phase 2D

- The live paired pilot is a short quality validation run, not long-term stability
  evidence or regime-diversity evidence.
- Quality thresholds are policy choices and can affect ACCEPTED, QUARANTINED, or
  REJECTED outcomes.
- No exchange-clock synchronization correction is applied.
- Phase 2D does not repair gaps, deduplicate records, interpolate quotes, or clean raw
  archives.
- No normalized feature dataset, predictive analysis, lead-lag research, backtest,
  strategy, execution simulation, PnL, or trading functionality exists.
- A quarantined live paired run can demonstrate the quality system working without
  proving research readiness.

## Known Research Risks

- Exchange timestamps may have different semantics across venues.
- Local receipt timestamps depend on host clock accuracy and network path.
- WebSocket feeds can drop messages or disconnect.
- Book-derived signals are unreliable without sequence and checksum validation.
- Apparent lead-lag relationships can disappear after fees, spread, latency, and adverse
  selection.
- Multiple-testing risk remains high until registered hypotheses, horizons, and final
  holdout handling are enforced on real data.
