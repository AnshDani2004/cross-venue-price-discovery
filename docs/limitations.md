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

## Phase 2D.1

- Calibration is based on a small number of short sessions.
- Sequential pilots do not establish time-of-day or market-regime diversity.
- No clock synchronization correction is applied.
- Stable exchange-clock offset is observed, not corrected.
- Raw duplicate frames are preserved.
- No normalization or deduplication has been performed.
- Accepted data does not imply predictive usefulness.
- No lead-lag conclusion has been tested.

## Phase 3A

- The first normalized input dataset is one short accepted paired session.
- Normalization correctness does not imply representative research data.
- No deduplication is performed.
- No clock correction is performed.
- No lead-lag analysis is performed.
- No predictive or trading conclusion is supported.
- Physical Parquet checksums may depend on library versions outside the supported local
  environment; semantic hashes are the cross-run logical guarantee.

## Phase 3B

- The campaign is planned across specific collection windows; missed windows may require
  reserve slots.
- Three time buckets do not represent all market regimes.
- Five accepted hours remains a limited research sample.
- Sequential collection days do not establish long-horizon stability.
- Accepted campaign data does not imply a predictive relationship.
- Phase 3B performs no lead-lag analysis, modeling, backtesting, PnL, strategy logic,
  execution simulation, authenticated API use, or trading.

## Phase 3B.1

- The generic campaign engine separates campaign identities but does not itself create
  research conclusions.
- Intraday exploratory campaigns are not cross-day validation evidence.
- Runtime migration is permitted only before the first collection attempt and only with
  unchanged campaign config and quality policy hashes.
- Accepted sessions remain governed by quality rules and cannot be manually cherry-picked
  out of an otherwise accepted campaign.

## Phase 3B.2

- Long-duration campaign support raises the finite paired-collection safety bound to
  3,600 seconds, but it does not guarantee that a long public collection will be accepted.
- I01 remains a failed zero-data preflight attempt and must be replaced by a later
  intraday slot or reserve slot.
- Runtime migration after zero-data failure is limited to attempts with no collected
  market-data evidence.

## Phase 3B.3

- Phase 3B.3 fixes campaign message-limit propagation but does not retroactively accept
  I02 or any historical excluded attempt.
- I02 remains rejected because accepted quality reports alone do not satisfy the campaign
  overlap requirement.
- Runtime migration after excluded attempts is allowed only for terminal failed or
  rejected attempts with no accepted dataset membership and unchanged config/policy
  hashes.
- A 100,000-message cap reduces premature stopping risk for 31-minute public slots, but
  it is still a finite safety cap and can be hit in unusually high message-rate regimes.

## Phase 3B.4

- Phase 3B.4 removes the archival campaign path's in-memory diagnostic sink cap, but it
  does not retroactively change I02 or I04.
- Future attempts expose effective per-venue duration/message limits and typed stop
  reasons; historical attempts do not contain those diagnostics.
- Smoke and dry-run collectors still use bounded in-memory sinks and are not substitutes
  for archival campaign validation.

## Known Research Risks

- Exchange timestamps may have different semantics across venues.
- Local receipt timestamps depend on host clock accuracy and network path.
- WebSocket feeds can drop messages or disconnect.
- Book-derived signals are unreliable without sequence and checksum validation.
- Apparent lead-lag relationships can disappear after fees, spread, latency, and adverse
  selection.
- Multiple-testing risk remains high until registered hypotheses, horizons, and final
  holdout handling are enforced on real data.
