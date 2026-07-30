# Data Sources

Documentation review date: 2026-07-30.

Only official Coinbase and Kraken documentation or exchange-published endpoints are used
for Phase 01 source planning. No authenticated data source, private endpoint, or trading
API is required.

## Fixed Phase 2 Collection Scope

| Venue | Public Endpoint | Symbol | Trades | Top Of Book | Deferred |
| --- | --- | --- | --- | --- | --- |
| Coinbase | `wss://ws-feed.exchange.coinbase.com` | `BTC-USD` | `matches`; timestamp field `time`; sequence field `sequence` | `ticker`; timestamp field `time`; sequence field `sequence` | `level2` depth reconstruction |
| Kraken | `wss://ws.kraken.com/v2` | `BTC/USD` | `trade`; timestamp field `timestamp`; trade identifier `trade_id` | `ticker`; timestamp field `timestamp`; `event_trigger=bbo`; no sequence or checksum field | `book` depth and checksum features |

The Phase 2A offline parser layer supports only trades, top of book, heartbeat/control,
subscription acknowledgement, venue error, and explicit unsupported-message handling for
the configured public scope. Depth channels are documented for later implementation but
are not parsed.

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
| Sequence handling | Preserve Coinbase per-product `sequence` values on configured channels; gaps or out-of-order messages must flag intervals as unusable until repaired. | https://docs.cdp.coinbase.com/exchange/websocket-feed/overview |
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

### Coinbase Phase 2A Parser Coverage

| Public message | Parser result | Fields consumed | Notes |
| --- | --- | --- | --- |
| `match`, `last_match` | `NormalizedTrade` | `trade_id`, `sequence`, `time`, `product_id`, `size`, `price`, `side` | Coinbase documents `side` as the maker side; parser maps maker `sell` to buyer aggressor and maker `buy` to seller aggressor. |
| `ticker` | `NormalizedTopOfBook` | `sequence`, `time`, `product_id`, `best_bid`, `best_bid_size`, `best_ask`, `best_ask_size` | Parser validates strict non-crossed top of book and does not derive midpoint or spread. |
| `heartbeat` | `ParsedControlMessage` | `type`, optional `product_id` | Preserved as control, not a market event. |
| `subscriptions` | `ParsedControlMessage` | `type` | Preserved as control, not a market event. |
| `error` | `ExchangeErrorMessage` | `message` | Preserved separately from parser failures. |

## Kraken Spot WebSocket V2

| Topic | Phase 01 Decision | Source |
| --- | --- | --- |
| Public WebSocket endpoint | Use `wss://ws.kraken.com/v2`. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Symbol | Use `BTC/USD` for WebSocket v2. | https://docs.kraken.com/exchange/guides/websockets/introduction |
| Trade channel | Use `trade`; preserve side, quantity, price, `trade_id`, and timestamp fields. `trade_id` is trade-message metadata, not a venue-wide sequence guarantee. | https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/trade |
| Top-of-book channel | Use `ticker` with `event_trigger=bbo`; preserve bid, bid quantity, ask, ask quantity, symbol, and timestamp fields. Do not assign a sequence field or checksum field to Kraken ticker messages. | https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker |
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
for top-of-book research, while the future `book` channel would have separate checksum
semantics. Do not compute depth features from ticker-only data, and do not treat
`trade_id` as ticker sequencing.

### Kraken Phase 2A Parser Coverage

| Public message | Parser result | Fields consumed | Notes |
| --- | --- | --- | --- |
| `channel=trade` snapshot/update | `NormalizedTrade` | `symbol`, `side`, `qty`, `price`, `trade_id`, `timestamp` | Multiple trades in one payload are emitted in source order; `trade_id` is preserved on trades only. |
| `channel=ticker` snapshot/update | `NormalizedTopOfBook` | `symbol`, `ask`, `ask_qty`, `bid`, `bid_qty`, `timestamp` | Parser expects the configured `event_trigger=bbo` subscription but does not synthesize sequence or checksum values. |
| `channel=heartbeat` | `ParsedControlMessage` | `channel`, optional `type` | Preserved as control, not a market event. |
| `method=subscribe` | `ParsedControlMessage` or `ExchangeErrorMessage` | `result.channel`, `result.symbol`, `success`, `error` | Failed subscription acknowledgements are exchange errors, not parse errors. |
| `method=error` | `ExchangeErrorMessage` | `error` | Preserved separately from parser failures. |

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
