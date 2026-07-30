# Data Dictionary

Review date: 2026-07-30.

This dictionary defines the Phase 2A offline public market-data contracts. The models
validate already-received payloads and normalized parser outputs only; no live collector
or storage writer is implemented yet.

## Raw Message Envelope

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `venue` | enum | none | Yes | Generated from config | `coinbase`, `kraken` | Reject envelope |
| `canonical_instrument` | string | none | Yes | Generated from config | `BTC-USD` in Phase 2A | Reject envelope |
| `venue_symbol` | string | none | Yes | Venue/config | `BTC-USD`, `BTC/USD` | Reject envelope |
| `channel` | string | none | Yes | Venue/config | Configured public channel | Reject envelope |
| `message_type` | string | none | Yes | Venue | Venue-native type or update marker | Reject envelope |
| `payload` | JSON object | none | Yes | Venue | JSON-compatible object with no credential-like keys | Reject envelope |
| `local_receipt_ts` | timestamp | UTC | Yes | Collector caller | Timezone-aware; captured before parsing | Reject envelope |
| `collector_session_id` | string | none | Yes | Generated | Non-empty stable ID per collector run | Reject envelope |
| `schema_version` | string | none | Yes | Generated | Starts at `0.1.0` | Reject envelope |
| `exchange_ts` | timestamp/null | UTC | Optional | Venue | Timezone-aware when present | Preserve null |
| `raw_sequence_value` | integer/string/null | sequence/id | Optional | Venue | Preserve venue value when supplied | Preserve null |

## Universal Event Metadata

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `schema_version` | string | none | Yes | Generated | Semantic version, starting at `0.1.0` | Reject normalized event |
| `collector_session_id` | string | none | Yes | Generated | Non-empty stable ID per collector run | Reject normalized event |
| `venue` | enum | none | Yes | Generated from config | `coinbase`, `kraken` | Reject normalized event |
| `canonical_instrument` | string | none | Yes | Generated from config | `BTC-USD` in Phase 2A | Reject normalized event |
| `venue_symbol` | string | none | Yes | Venue/config | `BTC-USD`, `BTC/USD` | Reject normalized event |
| `source_channel` | string | none | Yes | Venue/config | Configured trade or top-of-book channel | Reject normalized event |
| `raw_message_type` | string | none | Yes | Venue | Venue-native message or update type | Reject normalized event |
| `event_type` | enum | none | Yes | Generated | `trade`, `top_of_book` | Reject normalized event |
| `raw_sequence_value` | integer/string/null | sequence/id | Optional | Venue | Coinbase sequence or Kraken trade ID when applicable | Preserve null |
| `raw_checksum_value` | string/null | checksum | Optional | Venue | Non-empty when supplied | Preserve null |

## Timestamp Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `exchange_ts` | timestamp | UTC | Yes when venue supplies it | Venue | Timezone-aware; never coerced from naive datetime | Flag and exclude if absent |
| `local_receipt_ts` | timestamp | UTC | Yes | Generated | Timezone-aware; captured before parsing | Reject normalized event |
| `processing_ts` | timestamp/null | UTC | Future storage | Generated | `processing_ts >= local_receipt_ts` | Not populated in Phase 2A parser outputs |
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
| `price` | decimal | quote/base | Yes | Venue | `> 0` | Reject trade |
| `quantity` | decimal | base | Yes | Venue | `> 0` | Reject trade |
| `aggressor_side` | enum | none | Yes | Venue/derived | `buy`, `sell`, `unknown` | Use `unknown`; exclude signed-flow features |
| `signed_trade_size` | decimal/null | base | Future derived | Generated | Positive buy, negative sell, zero unknown | Not populated in Phase 2A parser outputs |

## Top-Of-Book Fields

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `best_bid_price` | decimal | quote/base | Yes | Venue | `> 0` and `< best_ask_price` | Reject top-of-book event |
| `best_bid_size` | decimal | base | Yes | Venue | `>= 0`; primary features require `> 0` | Flag if zero |
| `best_ask_price` | decimal | quote/base | Yes | Venue | `> 0` and `> best_bid_price` | Reject top-of-book event |
| `best_ask_size` | decimal | base | Yes | Venue | `>= 0`; primary features require `> 0` | Flag if zero |
| `midpoint` | decimal/null | quote/base | Future derived | Generated | `(best_bid_price + best_ask_price) / 2` | Not populated in Phase 2A parser outputs |
| `spread` | decimal/null | quote/base | Future derived | Generated | `best_ask_price - best_bid_price` | Not populated in Phase 2A parser outputs |
| `relative_spread` | decimal/null | rate | Future derived | Generated | `spread / midpoint` | Not populated in Phase 2A parser outputs |
| `queue_imbalance` | decimal/null | ratio | Future derived | Generated | `[-1, 1]` when sizes are positive | Not populated in Phase 2A parser outputs |
| `microprice` | decimal/null | quote/base | Future derived | Generated | Weighted top-of-book price | Not populated in Phase 2A parser outputs |

## Parser Non-Event Results

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `ParsedControlMessage` | object | none | Optional | Venue parser | Heartbeats and subscription acknowledgements | Parser returns another result kind |
| `UnsupportedPublicMessage` | object | none | Optional | Venue parser | Valid public payload outside configured Phase 2A scope | Parser returns another result kind |
| `ExchangeErrorMessage` | object | none | Optional | Venue parser | Public exchange error/control payload | Parser returns another result kind |
| `ParseResult.events` | tuple | events | Optional | Venue parser | One or more normalized events in source order | Exactly one result kind must be present |

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
