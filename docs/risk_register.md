# Risk Register

The register is reviewed at each phase gate. Likelihood and impact are qualitative:
Low, Medium, or High.

| Risk ID | Category | Description | Likelihood | Impact | Mitigation | Current status | Phase | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-DATA-001 | Data | Venue clocks differ or drift. | High | High | Store exchange and receipt timestamps; audit clock offset and jitter before lead-lag analysis. | Open | 1+ | Research |
| R-DATA-002 | Data | Messages are missing after disconnects or feed gaps. | High | High | Preserve sequence/checksum fields; record gaps and exclude invalid intervals. | Open | 2+ | Data |
| R-DATA-003 | Data | Duplicate messages distort event counts. | Medium | Medium | Deduplicate by venue, instrument, message type, sequence/trade ID, and timestamp where available. | Open | 2+ | Data |
| R-DATA-004 | Data | Messages arrive out of order locally. | High | High | Preserve receipt order and venue sequence; define deterministic reconstruction rules. | Open | 2+ | Data |
| R-DATA-005 | Data | Stale quotes are treated as current fair value. | Medium | High | Track quote age; exclude stale intervals from research and simulation. | Open | 3+ | Research |
| R-DATA-006 | Data | Exchange API schemas or channel semantics change. | Medium | High | Record documentation review dates; validate payloads with strict schemas; monitor unknown fields. | Open | 2+ | Engineering |
| R-DATA-007 | Data | Venue symbol mapping is wrong. | Medium | High | Centralize instrument mapping with official sources and tests. | Open | 1+ | Data |
| R-DATA-008 | Data | Sequence gaps invalidate book state. | High | High | Use Coinbase sequences and Kraken checksums where available; mark affected intervals invalid. | Open | 2+ | Data |
| R-DATA-009 | Data | Timestamp precision differs across venues or channels. | Medium | High | Record precision by venue/channel; avoid overinterpreting sub-precision ordering. | Open | 1+ | Research |
| R-DATA-010 | Data | Exchange downtime creates biased samples. | Medium | Medium | Record session status, reconnects, and outage intervals in manifests. | Open | 2+ | Data |
| R-RES-001 | Research | Look-ahead bias enters features or labels. | Medium | High | Enforce point-in-time feature generation and separate label construction. | Open | 5+ | Research |
| R-RES-002 | Research | Temporal leakage from random row splits. | Medium | High | Use chronological splits and untouched final holdout. | Open | 6+ | Research |
| R-RES-003 | Research | Overlapping labels create overstated confidence. | High | Medium | Use block/day bootstrap or Newey-West style corrections. | Open | 6+ | Research |
| R-RES-004 | Research | Overfitting from repeated model or threshold changes. | Medium | High | Maintain experiment log and separate exploratory from confirmatory analysis. | Open | 6+ | Research |
| R-RES-005 | Research | Multiple testing creates false discoveries. | High | High | Predeclare primary horizons and apply Benjamini-Hochberg FDR control at 5% for the primary test family. | Open | 1+ | Research |
| R-RES-006 | Research | Short sample periods fail across regimes. | High | Medium | Collect across time-of-day, weekday/weekend, and volatility regimes before conclusions. | Open | 2+ | Research |
| R-RES-007 | Research | Regime dependence hides unstable effects. | Medium | High | Report performance by volatility/liquidity regime. | Open | 6+ | Research |
| R-RES-008 | Research | PnL-driven model selection creates misleading research. | Medium | High | Freeze research models before trading-rule optimization. | Open | 7+ | Research |
| R-RES-009 | Research | Latency creates false lead-lag conclusions. | High | High | Compare exchange-time and receipt-time ordering; simulate decision timing separately. | Open | 6+ | Research |
| R-RES-010 | Research | Predictive causality is confused with structural causality. | Medium | Medium | Phrase conclusions as conditional predictive evidence unless causal identification is justified. | Open | 6+ | Research |
| R-SIM-001 | Simulation | Fill assumptions are unrealistic. | Medium | High | Build conservative execution simulation with spread, latency, and queue assumptions documented. | Open | 9+ | Trading |
| R-SIM-002 | Simulation | Fees are ignored or stale. | Medium | High | Store dated fee assumptions with sources and never treat them as permanent. | Open | 1+ | Trading |
| R-SIM-003 | Simulation | Latency is ignored in trading decisions. | Medium | High | Use receipt, decision, submission, arrival, and fill timestamps in simulation. | Open | 9+ | Trading |
| R-SIM-004 | Simulation | Queue-position assumptions are too optimistic. | Medium | High | Start with conservative passive-fill assumptions and sensitivity tests. | Open | 10+ | Trading |
| R-SIM-005 | Simulation | PnL accounting is incorrect. | Medium | High | Test cash, position, fees, and realized/unrealized PnL accounting separately. | Open | 9+ | Trading |
| R-SIM-006 | Simulation | Risk assumptions are excessive. | Medium | High | Define position, drawdown, and per-trade risk limits before strategy evaluation. | Open | 8+ | Risk |
| R-ENG-001 | Security | Credentials leak into Git. | Low | High | Keep credentials out of committed config; use pre-commit private-key detection and `.gitignore`. | Open | 0+ | Engineering |
| R-ENG-002 | Engineering | Dependency vulnerability affects tooling. | Medium | Medium | Pin minimum versions, use `pip check`, and review dependency updates. | Open | 0+ | Engineering |
| R-ENG-003 | Engineering | Disk growth from raw data is unbounded. | Medium | Medium | Define file rotation, manifests, compression, and disk monitoring. | Open | 2+ | Engineering |
| R-ENG-004 | Engineering | Logs grow without bounds. | Medium | Medium | Keep log directories ignored and add rotation when long-running collectors are implemented. | Open | 2+ | Engineering |
| R-ENG-005 | Engineering | Data corruption is undetected. | Medium | High | Store checksums and validate manifests. | Open | 2+ | Data |
| R-ENG-006 | Engineering | Invalid configuration silently changes research scope. | Medium | High | Use strict typed configuration with unknown fields rejected. | Open | 0+ | Engineering |
| R-ENG-007 | Engineering | Parser failures are silently ignored. | Medium | High | Validate schemas and log parser failures with data-quality flags. | Open | 3+ | Engineering |
| R-ENG-008 | Engineering | Generated files are committed to Git. | Low | Medium | Ignore raw data, generated reports, models, logs, caches, and database files. | Open | 0+ | Engineering |
| R-ENG-009 | Engineering | Connection instability interrupts smoke collection. | High | Medium | Use bounded reconnect attempts, visible failure reasons, and per-run counters. | Open | 2B+ | Engineering |
| R-ENG-010 | Engineering | Reconnection storms hit exchange or CDN limits. | Medium | High | Bound retry attempts, cap backoff, and follow venue reconnect guidance. | Open | 2B+ | Engineering |
| R-ENG-011 | Engineering | Heartbeat false positives hide stale market data. | Medium | Medium | Track last frame, last control, and last market-event monotonic times separately. | Open | 2B+ | Data |
| R-ENG-012 | Engineering | Sink backpressure causes event loss. | Medium | High | Use bounded in-memory sink with explicit backpressure errors and no silent drops. | Open | 2B+ | Engineering |
| R-ENG-013 | Engineering | Events are lost before persistence exists. | High | Medium | Treat Phase 2B as smoke-only and add raw archival in Phase 2C before research collection. | Mitigated by Phase 2C raw archival; monitor in longer runs. | 2C | Data |
| R-ENG-014 | Engineering | Duplicate frames after reconnect distort counts. | Medium | Medium | Preserve raw sequence/trade IDs and add deduplication during persistent promotion. | Open | 2C+ | Data |
| R-ENG-015 | Engineering | DNS, TLS, or local clock quality degrades collection. | Medium | High | Record connection failures, add host clock audit in manifests, and keep receipt-time ordering primary. | Open | 2C+ | Engineering |
| R-ENG-016 | Engineering | Raw archive writer backpressure or disk failure causes silent loss. | Medium | High | Use bounded writer queues, visible storage errors, failed session state, and archive validation. | Mitigated in Phase 2C; needs longer stress evidence. | 2C+ | Engineering |
| R-ENG-017 | Engineering | Interrupted sessions leave partial raw shards. | Medium | Medium | Keep `.partial` shards visible, preserve originals, recover valid prefixes, and validate finalized sessions. | Mitigated in Phase 2C; needs crash-drill evidence. | 2C+ | Data |
