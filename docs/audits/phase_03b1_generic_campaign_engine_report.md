# Phase 3B.1 Generic Campaign Engine Report

Review date: 2026-07-31.

## Original Blockers

The Phase 3B campaign engine was bound to one campaign ID, one 15-slot shape, and one
missed-reason vocabulary. CLI commands loaded the default Phase 3B TOML unless an
explicit config was supplied, so a second campaign could not be safely initialized and
later resolved by ID.

## Frozen Baseline

- Original Phase 3B commit: `06de679ba44e3793ca6b892448c5441020cf5461`
- Generic branch: `phase/03b1-generic-campaign-engine`
- Branch starting commit: `06de679ba44e3793ca6b892448c5441020cf5461`
- Existing campaign ID: `btc-usd-coinbase-kraken-2026-07-31-v1`
- Existing registry hash before code changes:
  `c4740743a207a907f9044bc25fd50ba88b8e81871850e8b36d4df6e41535e76b`
- Existing ledger hash before code changes:
  `1907547f1b998c09ca1cab2d8f387f0a82eb11334db0096c650f0e1f57f7cc5f`
- Existing campaign config hash:
  `6e0418d42fcddbdf7981853b626ef702309fec916252c2a00654fd4eaa12e8ba`
- Quality policy hash:
  `375eb5655d0d9212814502663a6284a316c1d6913585acece35ded2137332024`

## Generic Engine

Campaign IDs are validated lowercase path-safe strings and are not normalized or silently
rewritten. Campaign configs support roles: `MULTI_DAY_VALIDATION`,
`EXPLORATORY_INTRADAY`, and `DEVELOPMENT_SMOKE`. Legacy `3b.1` records that omit a role
load as `MULTI_DAY_VALIDATION`.

Slot invariants are campaign-specific. The engine requires at least one slot, unique slot
IDs, unique planned timestamps, deterministic ordering, at least one primary slot,
`minimum_accepted_sessions <= maximum_attempts`, and `maximum_attempts` equal to total
planned slots under the current one-attempt-per-slot runner model. It no longer requires
exactly ten primary and five reserve slots.

Campaign registries, ledgers, locks, reports, attempts, and manifests are isolated below
`data/campaigns/campaign=<campaign-id>/`. CLI commands resolve a campaign by its ID and
stored registry config path after initialization.

## Runtime Migration

The `migrate-campaign-runtime` command appends a `CAMPAIGN_RUNTIME_MIGRATED` ledger event
only before the first collection attempt. It requires a valid registry and ledger, clean
working tree, unchanged campaign config hash, unchanged quality policy hash, zero
attempts, zero accepted overlap, and no existing migration. Missed slots do not block the
migration.

Runtime migration result: to be recorded after validation.

## Intraday Campaign

- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-intraday-v1`
- Role: `EXPLORATORY_INTRADAY`
- Config path: `data/campaigns/configs/intraday_btc_usd_2026_07_31.toml`
- Schedule: to be frozen after the generic runtime commit is clean.

The intraday campaign is exploratory, hypothesis-generating, and not cross-day
validated. It does not satisfy the existing campaign's three-date requirement.

## Validation

Final implementation commit, full check output, intraday initialization status, and
operational next commands are recorded in the final task report after the validation
suite and local initialization complete.
