# Phase 03B Multi-Session Campaign Report

Status: CAMPAIGN IN PROGRESS

Review date: 2026-07-31

## Phase 3A Closure

PR #7, "Implement Phase 3A deterministic normalization", was merged before Phase 3B
branching.

- PR: https://github.com/AnshDani2004/cross-venue-price-discovery/pull/7
- Merge commit: `81944e21a252bde47b3e8bef2ee9b5857d910f60`
- CI result: passed

## Phase 3B Start

- Branch: `phase/03b-collection-campaign`
- Starting commit: `81944e21a252bde47b3e8bef2ee9b5857d910f60`
- Campaign ID: `btc-usd-coinbase-kraken-2026-07-31-v1`
- Frozen runtime commit: recorded in the ignored campaign registry at initialization
  after the final infrastructure commit.

## Campaign Configuration

The fixed campaign config is `configs/campaigns/phase_3b_btc_usd.toml`.

- Instrument: `BTC-USD`
- Venues: Coinbase and Kraken
- Quality policy: `2d.2`
- Requested duration per slot: 1,860 seconds
- Minimum accepted overlap per slot: 1,800 seconds
- Minimum accepted sessions: 10
- Minimum accepted overlap: 18,000 seconds
- Minimum local dates: 3
- Minimum time buckets: 3
- Maximum attempts: 15
- Timezone: `America/New_York`

Primary slots are P01 through P10 across 2026-07-31 through 2026-08-03. Reserve slots
are R01 through R05 across 2026-08-03 through 2026-08-04. Slot timestamps are stored in
UTC and documented with local America/New_York labels.

## Registry And Ledger

Generated campaign state is ignored under:

```text
data/campaigns/campaign=btc-usd-coinbase-kraken-2026-07-31-v1/
```

The campaign ledger is append-only JSONL with canonical SHA-256 event hashes chained by
`previous_event_hash`. The campaign registry is derived current state and is validated
against ledger reconstruction. Every accepted, quarantined, rejected, failed, aborted,
and missed attempt remains visible.

## Locking And Recovery

Campaign slot execution uses a lock file containing campaign ID, slot ID, attempt ID,
process ID, start timestamp, and runtime commit. Concurrent lock acquisition is rejected.
Corrupt or wrong-campaign locks are treated as operational failures rather than silently
overwritten.

## Acceptance Rules

An attempt is accepted only when archive validation passes for both venues, both venue
quality reports are `ACCEPTED`, the paired report is `ACCEPTED`, paired overlap is at
least 1,800 seconds, promotion dry-run is allowed, and an individual validated pair
manifest is created. Accepted attempts are included automatically and cannot be manually
excluded.

## Completion Rules

Campaign completion requires at least 10 accepted attempts, at least 18,000 seconds of
accepted overlap, at least three local dates, at least three time buckets, consistent
policy, frozen runtime consistency, registered attempts, and valid registry/ledger
state. Incomplete campaigns cannot finalize a validated campaign manifest.

## Multi-Session Manifest And Normalization

Validated campaign manifests include accepted pair manifest references and excluded
attempt summaries. Phase 3B extends normalization so `normalize-dataset` accepts either
an individual `ValidatedDatasetManifest` or a `ValidatedCampaignManifest`. Campaign
normalization replays accepted pair manifests in deterministic planned-slot order and
adds campaign lineage plus stable `source_event_id` values.

## Smoke Validation

Development-only synthetic multi-session validation passed in unit tests:

- Two accepted synthetic pair manifests
- Campaign manifest labeled as nonresearch smoke evidence
- Multi-session normalization
- Normalized validation
- DuckDB catalog build
- Determinism replay

Opt-in markers were added:

- `local_campaign_data`
- `campaign_smoke`

Live nonresearch campaign smoke collection is opt-in and must not be used as research
evidence.

## Offline Tests

Focused infrastructure checks covered campaign config validation, slot-window
boundaries, ledger hash-chain mutation detection, registry initialization, missed-slot
transitions, lock rejection, incomplete finalization blocking, and synthetic
multi-session normalization.

Full validation results are recorded in the pull request once the branch validation
commands are run.

## Security Review

Phase 3B uses existing public collectors only. It adds no API keys, authenticated APIs,
account APIs, order APIs, live trading, models, backtests, strategies, PnL, or raw
payload logging. Generated campaign registry, ledger, campaign manifests, normalized
campaign outputs, and DuckDB catalogs remain ignored by Git.

## Current Campaign Status

The real campaign is `IN_PROGRESS` after initialization. No future slots are reported
as completed in this infrastructure-stage report.

As of the infrastructure implementation run, the first actionable scheduled slot is:

```bash
python -m cross_venue run-campaign-slot \
  --campaign-id btc-usd-coinbase-kraken-2026-07-31-v1 \
  --slot-id P01
```

The runner itself enforces the slot-time window.

## Remaining Limitations

- The multi-day campaign is not complete.
- No Phase 3C exploratory microstructure analysis has started.
- Reserve slots may be required if primary slots are missed or fail quality acceptance.
- Five accepted hours will remain a limited sample even after completion.

## Verdict

PHASE 3B CAMPAIGN INFRASTRUCTURE READY; COLLECTION CAMPAIGN IN PROGRESS
