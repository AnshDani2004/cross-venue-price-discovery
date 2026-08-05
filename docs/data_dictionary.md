# Data Dictionary

Review date: 2026-07-30.

This dictionary defines the public market-data contracts through Phase 2C. The raw
archive stores exact received WebSocket frames plus collection metadata; parser envelopes
and normalized events remain typed and validated separately.

## Raw Archive Record

| Field | Type | Unit | Required | Source | Valid Range / Values | Missing Behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `archive_schema_version` | string | none | Yes | Generated | Starts at `0.1.0` | Reject record |
| `record_index` | integer | ordinal | Yes | Writer | Monotonic from 0 within session | Reject or fail validation |
| `collector_session_id` | string | none | Yes | Generated | Non-empty stable ID per collector run | Reject record |
| `venue` | enum | none | Yes | Generated from config | `coinbase`, `kraken` | Reject record |
| `canonical_instrument` | string | none | Yes | Generated from config | `BTC-USD` | Reject record |
| `venue_symbol` | string | none | Yes | Venue/config | `BTC-USD`, `BTC/USD` | Reject record |
| `local_receipt_ts` | timestamp | UTC | Yes | Collector runtime | Captured immediately after `recv()` before JSON decode | Reject record |
| `frame_type` | enum | none | Yes | Transport | `text`, `binary` | Reject record |
| `frame_encoding` | enum | none | Yes | Writer | `utf-8` for text, `base64` for binary | Reject record |
| `raw_frame` | string | bytes/text | Yes | Transport | Exact text frame or reversible Base64 binary bytes | Reject record |
| `raw_frame_byte_length` | integer | bytes | Yes | Writer | Original frame byte length | Reject record |
| `message_type` | string/null | none | Optional | Future classifier | Non-empty when known | Preserve null |
| `source_channel` | string/null | none | Optional | Future classifier | Non-empty when known | Preserve null |
| `exchange_ts` | timestamp/null | UTC | Optional | Future classifier | Timezone-aware when known | Preserve null |

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

## Quality Dispositions

| Value | Meaning |
| --- | --- |
| `ACCEPTED` | Session or pair satisfies mandatory quality policy checks. |
| `QUARANTINED` | Data is readable and preserved but requires review before research use. |
| `REJECTED` | Critical integrity or policy failure blocks research use. |

## Quality Finding

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `finding_id` | string | Yes | Stable finding code. |
| `category` | string | Yes | Integrity, duplicates, continuity, timestamps, quotes, coverage, or overlap. |
| `severity` | enum | Yes | `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `metric` | string | Yes | Metric being evaluated. |
| `observed_value` | scalar/null | Yes | Observed value without repair or deletion. |
| `threshold` | scalar/null | No | Policy threshold when applicable. |
| `message` | string | Yes | Human-readable explanation. |
| `evidence` | object | Yes | Portable evidence values; raw payloads are not printed by default. |
| `affected_channel` | string/null | No | Channel scope when applicable. |
| `affected_record_range` | tuple/null | No | Raw archive record range when applicable. |

Session quality reports include lineage hashes, input shard checksums, archive validation
result, all diagnostic metrics, findings, policy version, Git commit, and disposition.
Paired reports include the two session reports, local-receipt-time overlap, start skew,
paired findings, and paired disposition. Aggregate reports summarize counts and metric
distributions across session reports. Validated dataset manifests reference accepted raw
sessions and quality reports without copying or transforming raw data.

## Phase 2D.1 Calibrated Quality Fields

| Field | Values | Notes |
| --- | --- | --- |
| `observed_exchange_receipt_delta_pattern` | `STABLE_OFFSET`, `LOW_VARIANCE_OFFSET`, `MIXED_DISTRIBUTION`, `SPORADIC_OUTLIERS`, `UNSTABLE_OFFSET`, `INSUFFICIENT_EVIDENCE` | Diagnostic classification; not one-way latency. |
| `coinbase_sequence_diagnostic` | `DIAGNOSTIC`, `NONMONOTONIC_SEQUENCE`, `HEARTBEAT_MISSING_MATCH_EVIDENCE`, `CONFLICTING_TRADE_ID` | Product sequence jumps are diagnostic under partial subscription unless stronger evidence appears. |
| `coinbase_match_ticker_correspondence` | matched, absent-from-ticker, absent-from-match, lag, price/size/timestamp agreement | Used to distinguish ticker batching from missing subscribed messages. |
| `kraken_duplicate_category` | `HEARTBEAT_DUPLICATE`, `STATUS_DUPLICATE`, `SUBSCRIPTION_ACK_DUPLICATE`, `TICKER_RAW_DUPLICATE`, `TICKER_SEMANTIC_DUPLICATE`, `TRADE_RAW_DUPLICATE`, `TRADE_ID_DUPLICATE_IDENTICAL`, `TRADE_ID_DUPLICATE_CONFLICTING`, `UNSUPPORTED_DUPLICATE`, `OTHER_DUPLICATE` | Typed duplicate category. Kraken ticker sequence analysis remains false. |
| `quote_freshness_category` | `QUOTE_AGE`, `CONNECTION_INACTIVITY`, `HEARTBEAT_HEALTHY_QUIET_INTERVAL`, `MARKET_ACTIVITY_WITHOUT_BBO_CHANGE`, `MISSING_EXPECTED_QUOTE_CORRESPONDENCE`, `PROBABLE_FEED_INACTIVITY`, `RECONNECT_RELATED_GAP`, `SESSION_BOUNDARY_ARTIFACT` | Separates quote age from feed-liveness evidence. |
| `before_after_comparison.findings[]` | old and new category, severity, observed value, threshold, evidence, disposition, semantic reason | Preserves original findings even when severity changes. |

## Phase 3A Normalized Tables

All Phase 3A Parquet tables include deterministic lineage from the validated manifest to
the raw archive record. Financial values use `decimal128(38,18)` and timestamps use UTC
Arrow timestamps.

### Common Lineage Fields

| Field | Meaning |
| --- | --- |
| `normalized_schema_version` | Phase 3A schema version, initially `3a.1`. |
| `validated_dataset_manifest_id` | Source validated dataset manifest ID. |
| `validated_dataset_manifest_sha256` | SHA-256 of the validated manifest used as input. |
| `paired_collection_id` | Source paired collection ID. |
| `venue`, `canonical_instrument`, `venue_symbol`, `session_id` | Source session identifiers. |
| `connection_epoch` | Connection epoch, currently `0` for Phase 2C archives. |
| `source_shard_relative_path`, `source_shard_sha256` | Source raw shard lineage. |
| `source_raw_record_index`, `source_raw_frame_sha256` | Exact raw-record lineage. |
| `normalized_child_index` | Parser-output child index for multi-event raw frames. |
| `normalized_event_id` | SHA-256 of canonical identity components; independent of output path and execution time. |
| `is_raw_frame_duplicate`, `raw_frame_duplicate_count`, `raw_frame_duplicate_occurrence_index` | Exact raw-frame duplicate metadata within a session. |

### Trade Rows

Trade Parquet rows add `trade_id`, `price`, `quantity`, `side`, `side_semantics`,
`source_trade_id`, nullable `source_sequence`, and nullable `source_checksum`. The stored
`side` is the existing parser's normalized aggressor-side field.

### Top-Of-Book Rows

Top-of-book Parquet rows add `bid_price`, `bid_size`, `ask_price`, `ask_size`, nullable
`source_sequence`, and nullable `source_checksum`. Phase 3A does not add midpoint,
spread, microprice, imbalance, or predictive fields.

### Raw Record Outcomes

`raw_record_outcomes` contains exactly one row per raw archive record. It records
`normalization_outcome`, trade/BBO row counts, parse status, bounded parse error text,
unsupported reason, frame type, source message type, source channel, and duplicate
metadata. It never embeds full raw payloads.

## Phase 3B Campaign Data

The campaign registry is an ignored JSON document under `data/campaigns` that summarizes
campaign role, campaign status, fixed slots, attempts, accepted overlap, calendar-date
coverage, time-bucket coverage, and completion requirements. The append-only ledger is a
JSONL hash chain with event index, event type, occurrence timestamp, optional slot ID,
optional campaign attempt ID, bounded payload, previous event hash, and event hash.

Slots include `slot_id`, `slot_type`, UTC and local planned start timestamps, a
predeclared `time_bucket`, and current slot status. Attempts include slot identity,
attempt number, actual start and completion timestamps, paired collection identity,
venue session IDs, archive validation status, quality dispositions, validated pair
manifest references, failure classification, bounded failure message, inclusion status,
and exclusion reason.

Validated campaign manifests include only accepted attempts and preserve excluded
attempt summaries. They also record `campaign_role` so exploratory intraday evidence is
not confused with multi-day validation evidence. Campaign-level normalized rows add
nullable `campaign_id`, `slot_id`, `campaign_attempt_id`, `time_bucket`,
`validated_campaign_manifest_id`, and `validated_campaign_manifest_sha256`. Normalized
trade and top-of-book rows also include `source_event_id`, a deterministic source-lineage
ID that is stable across individual pair and campaign normalization runs.

## Phase 3C.2 Analysis Snapshot Normalization

Analysis-snapshot trade and BBO rows also include `dataset_snapshot_id`,
`source_catalog_id`, source quality and raw-shard hashes, collection runtime commit,
quality code commit, quality policy version, parser version, and duplicate
classification. Trades include exact `notional`.

BBO rows include `midprice`, `spread`, `relative_spread`, `spread_basis_points`,
`quoted_depth`, `bid_ask_imbalance`, `locked_market_indicator`, and
`crossed_market_indicator`. Locked and crossed source quote states are preserved and
classified instead of being silently removed.

The analysis normalization pipeline writes `metadata/sessions.parquet` with one row per
venue session and `metadata/attempts.parquet` with one row per accepted paired attempt.
These metadata tables preserve snapshot, campaign, attempt, paired collection, session,
runtime, quality, and normalization disposition fields for auditable downstream research.
