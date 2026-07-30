# Data Dictionary

## Core Identifiers

| Field | Meaning | Example |
| --- | --- | --- |
| `exchange` | Normalized venue identifier | `coinbase`, `kraken` |
| `venue_symbol` | Venue-native market symbol | `BTC-USD`, `BTC/USD` |
| `base_asset` | Asset being traded | `BTC` |
| `quote_asset` | Pricing asset | `USD` |
| `normalized_symbol` | Venue-independent research symbol | `BTC-USD` |

## Timestamp Fields

| Field | Meaning | Availability |
| --- | --- | --- |
| `exchange_ts` | Timestamp supplied by the venue message | Raw observation |
| `local_receipt_ts` | Timestamp captured when our process receives the message | Raw observation |
| `processing_ts` | Timestamp after parsing and validation | Raw observation |
| `decision_ts` | Timestamp when simulated trading logic makes a decision | Simulation |
| `simulated_order_submission_ts` | Timestamp when a simulated order would be sent | Simulation |
| `simulated_fill_ts` | Timestamp when a simulated order is filled | Simulation |

## Market Data Schemas

### TradeEvent

| Field | Meaning |
| --- | --- |
| `instrument` | Venue and instrument identifiers |
| `clock` | Point-in-time timestamp bundle |
| `trade_id` | Venue trade identifier normalized to string |
| `price` | Positive execution price |
| `size` | Positive executed quantity |
| `side` | Aggressor side if known; otherwise `unknown` |
| `raw_sequence` | Venue sequence number when supplied |

### OrderBookSnapshot

| Field | Meaning |
| --- | --- |
| `instrument` | Venue and instrument identifiers |
| `clock` | Point-in-time timestamp bundle |
| `bids` | Positive price and quantity levels |
| `asks` | Positive price and quantity levels |
| `raw_sequence` | Venue sequence number when supplied |
| `midpoint` | `(best_bid + best_ask) / 2` |

Crossed books are rejected at the schema layer.

## Market Foundation Terms

| Term | Definition |
| --- | --- |
| Best bid | Highest visible buy price in a venue order book |
| Best ask | Lowest visible sell price in a venue order book |
| Spread | `best_ask - best_bid` |
| Midpoint | `(best_bid + best_ask) / 2` |
| Price discovery | Process by which new information is incorporated into prices |
| Venue leadership | Point-in-time evidence that one venue's updates precede related updates elsewhere |
