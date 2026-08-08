# Phase 3B.5 Intraday Continuation Plan

Review date: 2026-08-02.

## Scope

This phase adds a separately registered supplemental exploratory intraday campaign. It
does not mutate, reopen, extend, or complete the original exploratory intraday campaign:

- `btc-usd-coinbase-kraken-2026-07-31-intraday-v1`

The intended analytical framing is:

> Eight-session intraday pilot plus a separately registered supplemental exploratory
> campaign.

This supplemental evidence is hypothesis-generating only. It is not a substitute for the
multi-day validation campaign and does not imply production trading readiness,
profitable arbitrage, predictive edge, cross-day validation, or causal venue leadership.

## Supplemental Campaign

Campaign ID:

- `btc-usd-coinbase-kraken-2026-08-intraday-continuation-v1`

Configuration:

- Role: `EXPLORATORY_INTRADAY`
- Instrument: `BTC-USD`
- Venues: Coinbase and Kraken
- Requested duration: `1860` seconds
- Maximum messages per venue: `100000`
- Minimum accepted sessions: `2`
- Minimum accepted paired overlap: `3600` seconds
- Minimum calendar dates: `2`
- Minimum time buckets: `2`
- Slots: `3` primary and `2` reserve

## Proposed Schedule

The schedule avoids the active multi-day validation slots through Aug 4, 2026, and uses
the existing execution window of five minutes early through fifteen minutes late.

| Slot | Type | Bucket | New York | Chicago | UTC | Allowed window UTC |
|---|---|---|---|---|---|---|
| S01 | PRIMARY | MORNING | Aug 5 10:00 AM ET | Aug 5 9:00 AM CT | 2026-08-05 14:00Z | 13:55Z-14:15Z |
| S02 | PRIMARY | EVENING | Aug 6 10:00 PM ET | Aug 6 9:00 PM CT | 2026-08-07 02:00Z | 01:55Z-02:15Z |
| S03 | PRIMARY | MORNING | Aug 7 10:00 AM ET | Aug 7 9:00 AM CT | 2026-08-07 14:00Z | 13:55Z-14:15Z |
| R01 | RESERVE | EVENING | Aug 7 10:00 PM ET | Aug 7 9:00 PM CT | 2026-08-08 02:00Z | 01:55Z-02:15Z |
| R02 | RESERVE | MORNING | Aug 8 10:00 AM ET | Aug 8 9:00 AM CT | 2026-08-08 14:00Z | 13:55Z-14:15Z |

Live collection still requires explicit user approval before running any slot.

## Composite Exploratory Dataset Handoff

The original and supplemental campaigns remain separate at the registry and ledger
level. The composite handoff is a separate manifest labeled
`SUPPLEMENTAL_INTRADAY_EXPLORATORY_DATASET`.

The manifest references accepted attempts from both campaigns and preserves:

- Source campaign IDs and roles
- Accepted attempt IDs
- Per-attempt runtime commits
- Validated pair manifest IDs and hashes
- Paired and session quality report hashes
- Source manifest hashes
- Raw shard checksum references
- Inclusion decisions
- Aggregate accepted-session count
- Aggregate paired-overlap seconds

The composite builder reads and validates source campaign registries but does not append
to or rewrite source campaign ledgers.
