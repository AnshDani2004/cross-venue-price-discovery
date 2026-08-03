# Phase 3B.6 Multi-Day Supplement Plan

Review date: 2026-08-03.

## Original Campaign Status

Original campaign:

- `btc-usd-coinbase-kraken-2026-07-31-v1`

Final status inspected before implementation:

- Role: `MULTI_DAY_VALIDATION`
- Status: `IN_PROGRESS`
- Completion: `UNSATISFIED`
- Runtime: `98e28b2e026124434fc1bec1d442d7b9bcbc8530`
- Accepted sessions: `4`
- Accepted overlap seconds: `7430.1424609999995`
- Accepted calendar dates: `2026-07-31`, `2026-08-02`, `2026-08-03`
- Accepted time buckets: `AFTERNOON`, `EVENING`, `MORNING`

Shortfall calculation:

```text
sessions_needed = max(0, 10 - 4) = 6
overlap_needed = max(0, 18000 - 7430.1424609999995) = 10569.857539
minimum_supplemental_sessions = max(6, ceil(10569.857539 / 1800)) = 6
```

The original campaign remains immutable. This phase does not add slots, reopen attempts,
alter completion requirements, edit the original ledger, or change historical
dispositions.

## Supplemental Campaign

Campaign ID:

- `btc-usd-coinbase-kraken-2026-08-multiday-supplement-v1`

Configuration:

- Role: `MULTI_DAY_VALIDATION`
- Instrument: `BTC-USD`
- Venues: Coinbase and Kraken
- Requested duration: `1860` seconds
- Maximum messages per venue: `100000`
- Minimum accepted sessions: `6`
- Minimum total accepted overlap seconds: `10570`
- Minimum accepted calendar dates: `3`
- Minimum accepted time buckets: `3`
- Slots: `6` primary and `2` reserve

## Proposed Schedule

The schedule avoids the remaining original multi-day campaign reserve slots and the
separately planned exploratory intraday continuation slots. It uses the existing five
minutes early through fifteen minutes late execution window.

| Slot | Type | Bucket | New York | Chicago | UTC | Allowed window UTC |
|---|---|---|---|---|---|---|
| P01 | PRIMARY | AFTERNOON | Aug 5 4:00 PM ET | Aug 5 3:00 PM CT | 2026-08-05 20:00Z | 19:55Z-20:15Z |
| P02 | PRIMARY | EVENING | Aug 5 10:00 PM ET | Aug 5 9:00 PM CT | 2026-08-06 02:00Z | 01:55Z-02:15Z |
| P03 | PRIMARY | MORNING | Aug 6 10:00 AM ET | Aug 6 9:00 AM CT | 2026-08-06 14:00Z | 13:55Z-14:15Z |
| P04 | PRIMARY | AFTERNOON | Aug 6 4:00 PM ET | Aug 6 3:00 PM CT | 2026-08-06 20:00Z | 19:55Z-20:15Z |
| P05 | PRIMARY | AFTERNOON | Aug 7 4:00 PM ET | Aug 7 3:00 PM CT | 2026-08-07 20:00Z | 19:55Z-20:15Z |
| P06 | PRIMARY | AFTERNOON | Aug 8 4:00 PM ET | Aug 8 3:00 PM CT | 2026-08-08 20:00Z | 19:55Z-20:15Z |
| R01 | RESERVE | EVENING | Aug 8 10:00 PM ET | Aug 8 9:00 PM CT | 2026-08-09 02:00Z | 01:55Z-02:15Z |
| R02 | RESERVE | MORNING | Aug 9 10:00 AM ET | Aug 9 9:00 AM CT | 2026-08-09 14:00Z | 13:55Z-14:15Z |

Live collection still requires explicit approval before running any slot.

## Composite Validation Manifest

The composite validation manifest references:

1. `btc-usd-coinbase-kraken-2026-07-31-v1`
2. `btc-usd-coinbase-kraken-2026-08-multiday-supplement-v1`

It validates the source registries and ledgers, requires aggregate coverage of at least
ten accepted sessions, eighteen thousand accepted overlap seconds, three accepted
calendar dates, and three accepted time buckets, and preserves per-attempt runtime,
quality-report, source-manifest, and raw-shard checksum lineage. It does not merge or
rewrite either campaign ledger.
