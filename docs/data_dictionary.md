# Data Dictionary

Review date: 2026-07-30.

This dictionary defines normalized fields expected from future public market-data
collectors. It describes contracts only; no collector is implemented in Phase 01.

## Universal Event Metadata

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | string | none | Yes | Generated | Semantic version, starting at `0.1.0` | Reject normalized event |
| `collector_session_id` | string | none | Yes | Generated | Non-empty stable ID per collector run | Reject normalized event |
| `venue` | enum | none | Yes | Generated from config | `coinbase`, `kraken` | Reject normalized event |
| `canonical_instrument` | string | none | Yes | Generated from config | `BTC-USD` in Phase 01 | Reject normalized event |
| `venue_symbol` | string | none | Yes | Venue/config | `BTC-USD`, `BTC/USD` | Reject normalized event |
| `channel` | string | none | Yes | Venue | Configured trade or top-of-book channel | Reject normalized event |
| `message_type` | string | none | Yes | Venue | Venue-native message or update type | Reject normalized event |
| `event_type` | enum | none | Yes | Generated | `trade`, `top_of_book`, `heartbeat`, `control` | Reject normalized event |
| `raw_sequence` | integer/null | sequence | Optional | Venue | Non-negative when supplied | Flag if expected but missing |
| `raw_trade_id` | string/null | none | Optional | Venue | Non-empty when supplied | Required for normalized trades if venue supplies it |
| `data_quality_flag` | enum/list | none | Yes | Generated | `ok` or declared exclusion reason | Preserve row but exclude from primary research when not `ok` |
| `raw_payload_ref` | string | URI/path | Yes | Generated | Points to raw archived payload | Reject analytical promotion |

## Timestamp Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `exchange_ts` | timestamp | UTC | Yes when venue supplies it | Venue | Timezone-aware; never coerced from naive datetime | Flag and exclude if absent |
| `local_receipt_ts` | timestamp | UTC | Yes | Generated | Timezone-aware; captured before parsing | Reject normalized event |
| `processing_ts` | timestamp | UTC | Yes | Generated | `processing_ts >= local_receipt_ts` | Reject normalized event |
| `decision_ts` | timestamp/null | UTC | Simulation only | Generated | `decision_ts >= processing_ts` | Must be null before simulation |
| `simulated_order_submission_ts` | timestamp/null | UTC | Simulation only | Generated | `>= decision_ts` | Must be null before simulation |
| `simulated_order_arrival_ts` | timestamp/null | UTC | Simulation only | Generated | `>= simulated_order_submission_ts` | Must be null before simulation |
| `simulated_fill_ts` | timestamp/null | UTC | Simulation only | Generated | `>= simulated_order_arrival_ts` | Must be null before simulation |

Equal timestamps are ordered by `local_receipt_ts`, then `venue`, then
`sequence_number`, then `message_type`.

## Instrument Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `base_asset` | string | none | Yes | Config | `BTC` | Reject normalized event |
| `quote_asset` | string | none | Yes | Config | `USD` | Reject normalized event |
| `market_type` | enum | none | Yes | Config | `spot` | Reject normalized event |
| `tick_size` | decimal | quote currency | Yes for features | Market rules config | `> 0` | Cannot compute tick-based events |
| `minimum_order_size` | decimal | base currency | Yes for simulation | Market rules config | `> 0` | Cannot simulate order |

## Trade Event Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_id` | string | none | Yes | Venue | Non-empty | Reject trade |
| `trade_price` | decimal | quote/base | Yes | Venue | `> 0` | Reject trade |
| `trade_size` | decimal | base | Yes | Venue | `> 0` | Reject trade |
| `aggressor_side` | enum | none | Yes | Venue/derived | `buy`, `sell`, `unknown` | Use `unknown`; exclude signed-flow features |
| `signed_trade_size` | decimal | base | Derived | Generated | Positive buy, negative sell, zero unknown | Null if side unknown |

## Top-Of-Book Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `best_bid` | decimal | quote/base | Yes | Venue | `> 0` and `< best_ask` | Reject top-of-book event |
| `best_bid_size` | decimal | base | Yes | Venue | `>= 0`; primary features require `> 0` | Flag if zero |
| `best_ask` | decimal | quote/base | Yes | Venue | `> 0` and `> best_bid` | Reject top-of-book event |
| `best_ask_size` | decimal | base | Yes | Venue | `>= 0`; primary features require `> 0` | Flag if zero |
| `midpoint` | decimal | quote/base | Derived | Generated | `(best_bid + best_ask) / 2` | Null if book invalid |
| `spread` | decimal | quote/base | Derived | Generated | `best_ask - best_bid` | Null if book invalid |
| `relative_spread` | decimal | rate | Derived | Generated | `spread / midpoint` | Null if midpoint invalid |
| `queue_imbalance` | decimal/null | ratio | Derived | Generated | `[-1, 1]` when sizes are positive | Null if sizes unavailable |
| `microprice` | decimal/null | quote/base | Derived | Generated | Weighted top-of-book price | Null if sizes unavailable |

## Research Label Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `initiating_venue` | enum | none | Yes | Generated | `coinbase`, `kraken` | Reject label row |
| `response_venue` | enum | none | Yes | Generated | Opposite venue | Reject label row |
| `event_ts` | timestamp | UTC | Yes | Generated | Ordered by receipt time in primary analysis | Reject label row |
| `horizon_ms` | integer | milliseconds | Yes | Config | `100`, `250`, `500` in Phase 01 | Reject label row |
| `initiating_move_ticks` | decimal | ticks | Yes | Generated | Absolute value `>= 1` for events | Reject label row |
| `response_midpoint_return` | decimal/null | rate | Yes | Generated | Finite when future midpoint exists | Exclude if unavailable |
| `direction_target` | enum/null | none | Yes | Generated | `up`, `down`, `unchanged` | Exclude if future midpoint unavailable |

## Storage Metadata

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `raw_file_sha256` | string | none | Yes | Generated | 64 hex characters | Reject manifest |
| `normalized_file_sha256` | string | none | Yes for promoted files | Generated | 64 hex characters | Reject manifest |
| `row_count` | integer | rows | Yes | Generated | `>= 0` | Reject manifest |
| `collection_started_at` | timestamp | UTC | Yes | Generated | Timezone-aware | Reject manifest |
| `collection_ended_at` | timestamp | UTC | Yes | Generated | `>= collection_started_at` | Reject manifest |
| `collector_version` | string | none | Yes | Generated | Git commit or package version | Reject manifest |
