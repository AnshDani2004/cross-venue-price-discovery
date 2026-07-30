# Data Sources

Documentation review date: 2026-07-30.

Only official Coinbase and Kraken documentation or exchange-published endpoints are used
for Phase 01 source planning. No authenticated data source, private endpoint, or trading
API is required.

## Fixed Phase 2 Collection Scope

| Venue | Public Endpoint | Symbol | Trades | Top Of Book | Deferred |
| --- | --- | --- | --- | --- | --- |
| Coinbase | `wss://ws-feed.exchange.coinbase.com` | `BTC-USD` | `matches` | `ticker` best bid/ask fields | `level2` depth reconstruction |
| Kraken | `wss://ws.kraken.com/v2` | `BTC/USD` | `trade` | `ticker` with `event_trigger=bbo` | `book` depth and checksum features |

The initial collector should subscribe only to trades and top of book. Depth channels are
documented for later implementation but are not required for the first public-data
collector.

## Coinbase Exchange

| Topic | Phase 01 Decision | Source |
| --- | --- | --- |
| Public WebSocket endpoint | Use `wss://ws-feed.exchange.coinbase.com` for public market data. | https://docs.cdp.coinbase.com/exchange/websocket-feed/overview |
| Sandbox endpoint | Sandbox public endpoint is available for connection tests, but production public market data is the research target. | https://docs.cdp.coinbase.com/exchange/websocket-feed/overview |
| Product ID | Use `BTC-USD`. | https://docs.cdp.coinbase.com/exchange/websocket-feed/channels |
| Subscription shape | Send a JSON `subscribe` message with `product_ids` and `channels`; collector must send it promptly after connecting. | https://docs.cdp.coinbase.com/exchange/websocket-feed/channels |
| Trade channel | Use `matches`; record initial `last_match` behavior and later `match` updates. | https://docs.cdp.coinbase.com/exchange/websocket-feed/channels |
| Top-of-book channel | Use `ticker`; preserve `best_bid`, `best_bid_size`, `best_ask`, and `best_ask_size`. | https://docs.cdp.coinbase.com/exchange/websocket-feed/channels |
| Heartbeat | Subscribe to `heartbeat` so gaps can be detected with sequence and last trade identifiers. | https://docs.cdp.coinbase.com/exchange/websocket-feed/channels |
| Sequence handling | Preserve per-product sequence numbers; gaps or out-of-order messages must flag intervals as unusable until repaired. | https://docs.cdp.coinbase.com/exchange/websocket-feed/overview |
| Rate limits | Respect documented request, burst, inbound message, and subscription limits; collector settings must remain below them. | https://docs.cdp.coinbase.com/exchange/websocket-feed/rate-limits |
| Market rules | `BTC-USD` product endpoint currently reports `quote_increment=0.01`, `base_increment=0.00000001`, and online spot status. | https://api.exchange.coinbase.com/products/BTC-USD |
| Fee assumption | Public low-volume Coinbase Exchange fee tier is captured as a dated assumption in `configs/market_rules.toml`. | https://help.coinbase.com/en/exchange/trading-and-funding/exchange-fees |

Minimal Phase 2 subscription example:

```json
{
  "type": "subscribe",
  "product_ids": ["BTC-USD"],
  "channels": ["matches", "ticker", "heartbeat"]
}
```

Coinbase ambiguity to preserve in later code reviews: `ticker` is easier for top of
book, while `level2` is better for reconstructed depth. Phase 2 chooses `ticker` to
avoid pretending a full order book exists before sequence-gap handling is implemented.

## Kraken Spot WebSocket V2

| Topic | Phase 01 Decision | Source |
| --- | --- | --- |
| Public WebSocket endpoint | Use `wss://ws.kraken.com/v2`. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Symbol | Use `BTC/USD` for WebSocket v2. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Trade channel | Use `trade`; preserve side, quantity, price, trade ID, and timestamp fields. | https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade |
| Top-of-book channel | Use `ticker` with `event_trigger=bbo`; preserve bid, bid quantity, ask, ask quantity, symbol, and timestamp fields. | https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker |
| Book channel | Defer `book` until checksum validation and full-depth reconstruction are implemented. | https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book |
| Timestamp semantics | Treat RFC3339 timestamps as exchange timestamps, not unique identifiers. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Connection policy | Avoid rapid reconnect loops; maintain heartbeat/ping behavior for idle connections and observe documented reconnection guidance. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Market rules | Kraken REST `AssetPairs` endpoint currently reports `tick_size=0.1`, `ordermin=0.00005`, maker fee tier starting at 0.25%, and taker fee tier starting at 0.40% for `BTC/USD`. | https://api.kraken.com/0/public/AssetPairs?pair=BTCUSD |

Minimal Phase 2 subscription examples:

```json
{
  "method": "subscribe",
  "params": {
    "channel": "trade",
    "symbol": ["BTC/USD"]
  }
}
```

```json
{
  "method": "subscribe",
  "params": {
    "channel": "ticker",
    "symbol": ["BTC/USD"],
    "event_trigger": "bbo"
  }
}
```

Kraken ambiguity to preserve in later code reviews: the `ticker` channel is appropriate
for top-of-book research, while the `book` channel is required for depth and checksum
work. Do not compute depth features from ticker-only data.

## Responsible Collection Policy

- Use only documented public endpoints.
- Capture raw payloads before normalization.
- Record exchange timestamp, local receipt timestamp, processing timestamp, venue,
  symbol, channel, message type, collector session ID, and schema version.
- Respect exchange rate limits and reconnect guidance.
- Store credentials only in ignored local files if a future authenticated data need is
  approved.
- Do not distribute restricted raw data.
- Preserve manifests so every analytical table is traceable to source files and
  collection intervals.
