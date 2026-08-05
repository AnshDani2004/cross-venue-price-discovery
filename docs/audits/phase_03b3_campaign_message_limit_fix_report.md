# Phase 3B.3 Campaign Message-Limit Fix Report

Review date: 2026-07-31.

## Scope

Phase 3B.3 fixes campaign message-limit propagation for long-duration paired
collections. It does not begin Phase 3C and does not reinterpret existing intraday
attempts as accepted research evidence.

## Root Cause

The campaign runner already passed `maximum_messages_per_venue` from campaign config
into the paired quality collection path. The production paired collection function then
used a truthiness fallback:

```python
message_limit = max_messages_per_venue or quality_config.max_messages_per_venue
```

That made the explicit campaign value depend on fallback semantics rather than an
explicit optional-argument contract. The corrected contract is:

- Use the explicit campaign argument whenever it is not `None`.
- Fall back to `quality_config.max_messages_per_venue` only when the argument is `None`.
- Reject `0` and values above `100,000` before network access.
- Do not clamp duration or message limits.

## Runtime Contract

- Shared maximum paired collection duration: `3,600` seconds.
- Shared maximum paired collection messages per venue: `100,000`.
- Campaign configs may request any positive message limit up to `100,000`.
- Duration and message limits are independent.
- Campaign attempt diagnostics now record both `requested_duration_seconds` and
  `maximum_messages_per_venue` for future attempts.
- Campaign status reports print both configured limits.

The collector loop checks `frames_received >= max_messages` before receiving the next
frame. The convention is therefore no more than the configured maximum frames per venue.
At `100,000`, the message limit should not stop a 31-minute run around the old
approximately six-minute boundary unless the venue actually delivers 100,000 frames.

## Historical I01 And I02

Historical intraday attempts are preserved as-is:

| Attempt | Status | Inclusion | Frames | Overlap | Note |
| --- | --- | --- | --- | --- | --- |
| `btc-usd-coinbase-kraken-2026-07-31-intraday-v1-I01-001` | `FAILED` | `EXCLUDED` | `0 / 0` | `0` | Zero-data failure. |
| `btc-usd-coinbase-kraken-2026-07-31-intraday-v1-I02-001` | `REJECTED` | `EXCLUDED` | `5001 / 4879` | `289.97174` | Quality reports were accepted, but paired overlap was below the campaign requirement of `1,800` seconds. |

I02 keeps its historical exclusion reason, `quality disposition was not accepted`, for
audit immutability. Future attempts with accepted quality and insufficient campaign
overlap use `INSUFFICIENT_PAIRED_OVERLAP` with observed and required overlap values.

## Migration Semantics

Phase 3B.3 adds `CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX` and the ledger event
`CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS`.

This event is allowed only when:

- Campaign config and quality-policy hashes still match.
- Registry and ledger validation pass.
- The working tree is clean at migration time.
- Accepted attempt count and accepted overlap are zero.
- No attempt has accepted dataset membership.
- All existing attempts are terminal `FAILED` or `REJECTED` and `EXCLUDED`.

The event payload records old and new runtime commits, reason, timestamp, config and
policy hashes, excluded attempt IDs, attempt statuses, attempt source hashes, and
`no_accepted_dataset_membership`.

Future attempts record `attempt_runtime_git_commit`; campaign validation reconstructs
runtime lineage from ledger ordering and checks each future `ATTEMPT_STARTED` event
against the runtime active at that point. Historical attempts without this field remain
schema-compatible legacy evidence.

## Regression Coverage

Focused tests cover:

- Campaign config to registry to runner to paired collection to `RunLimits`.
- A `1,860` second campaign duration with `100,000` max messages per venue.
- Explicit message limits `100,000`, `50,000`, and `5,000`.
- `None` fallback to the quality policy message limit.
- Rejection of `0` and `100,001` before collector/network use.
- Distinct `INSUFFICIENT_PAIRED_OVERLAP` and quality-rejection exclusion reasons.
- Runtime migration after excluded attempts and blockers for wrong reasons or dataset
  membership.
- Collector stop semantics of no more than configured max frames.

Focused validation:

```bash
.venv/bin/python -m pytest tests/unit/test_campaign_duration.py tests/unit/test_campaigns.py tests/unit/test_collector_runtime.py -q
```

Result before campaign-state migration: `59 passed, 2 skipped`.
