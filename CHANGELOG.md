# Changelog

## Unreleased

No unreleased changes.

## 1.0.0 - 2026-08-08

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
- Add Phase 3A deterministic normalization with validated-manifest replay, exact-decimal
  trade and top-of-book Parquet outputs, raw-record outcome tables, semantic hashes,
  reconciliation, validation, DuckDB views, and determinism checks.
- Add Phase 3B campaign infrastructure with a fixed multi-day Coinbase/Kraken BTC-USD
  schedule, hash-chained attempt ledger, derived registry, slot-time enforcement,
  campaign locking, missed-slot recording, validated campaign manifests, multi-session
  normalization lineage, and opt-in smoke markers.
- Generalize the Phase 3B campaign engine for typed campaign IDs, campaign roles,
  flexible slot counts, cross-campaign isolation, controlled pre-collection runtime
  migration, and a separate exploratory intraday campaign path.
- Support bounded long-duration campaign collection by aligning Phase 2D runtime
  preflight with 31-minute campaign sessions, classifying preflight failures explicitly,
  preserving failed zero-data attempts, and allowing controlled corrective runtime
  migration.
- Fix Phase 3B campaign message-limit propagation, record future attempt runtime and
  message-limit diagnostics, distinguish insufficient-overlap rejections, and add a
  controlled runtime migration path after excluded failed/rejected attempts.
- Remove the remaining collector-internal archival sink cap, add typed collector stop
  reasons and effective per-venue run-limit diagnostics, and cover campaign limits
  through real collector stop predicates.
- Add Phase 3C.1 immutable source-catalog and seven-session analysis snapshot
  tooling with read-only collection roots, deterministic IDs, Decimal overlap
  aggregation, write-once artifacts, validation/status CLI commands, and fixture
  coverage for inclusion, exclusion, lineage, and immutability behavior.
- Add Phase 3C.2 analysis-snapshot normalization with snapshot-membership replay,
  expanded canonical trade/BBO lineage, derived BBO metrics, session and attempt
  metadata tables, per-session normalization manifests, no-op reuse, module CLI
  execution, and real seven-session validation/determinism outputs.
- Added extended normalized-dataset validation with source catalog, source
  snapshot, normalized output, lineage, and financial-integrity verification.
- Preserved the legacy one-argument normalization validation API.
- Added deterministic and idempotent normalized validation reports.
- Added Phase 4A preliminary-readiness diagnostics over manifest-defined
  partitioned Parquet outputs.
- Classified the immutable seven-attempt dataset as `PRELIMINARY_READY` for
  exploratory analysis while retaining
  `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`.
- Distinguished trade-observation overlap, approximately 12,972.85 seconds,
  from official validated campaign paired overlap, 13,005.314148 seconds.
- Recorded that accepted follow-up attempt F01 is not part of the immutable
  seven-attempt snapshot. Current collection progress is provisionally
  8 accepted attempts, leaving 2 additional accepted attempts required.
- Add a separate supplemental exploratory intraday campaign plan plus a lineage-only
  composite manifest handoff for combining accepted exploratory sessions without
  rewriting source campaign ledgers.
