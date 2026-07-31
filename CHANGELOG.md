# Changelog

## Unreleased

- Initialize Phase 00 project foundation.
- Add Phase 01 market-foundation assumptions and hypothesis register.
- Remediate Phase 0 foundation gaps with CLI, project settings, structured logging,
  formatting gates, risk register, experiment template, and updated contributor guidance.
- Remediate Phase 1 readiness with validated venue, research, timestamp, and market-rule
  configs; official channel documentation; collection/storage plans; and measurable
  hypothesis definitions.
- Add Phase 2A offline collector contracts, deterministic Coinbase/Kraken parsers,
  lifecycle and manifest models, fixture coverage, and an explicit no-live-networking
  boundary.
- Add Phase 2B bounded public WebSocket collectors with injectable transport, immediate
  receipt timestamps, heartbeat supervision, bounded retry, in-memory dry-run sink,
  CLI smoke runs, and opt-in live smoke tests.
- Add Phase 2C exact raw archival with bounded writer queues, rotating JSONL shards,
  SHA-256 sidecars, persistent manifests, quality summaries, validation/recovery CLI
  commands, offline tests, and opt-in live persistence smokes.
- Add Phase 2D data-quality validation with policy-driven session diagnostics, paired
  overlap analysis, explicit dispositions, dry-run validated manifest promotion,
  aggregation, controlled paired collection, and opt-in live quality tests.
- Add Phase 2D.1 quality calibration with policy 2d.2, read-only host-clock
  observation, negative-delta pattern diagnostics, Coinbase partial-subscription
  continuity semantics, typed Kraken duplicates, quote-freshness semantics, and
  calibrated paired reanalysis outputs.
