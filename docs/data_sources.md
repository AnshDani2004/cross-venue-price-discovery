# Data Sources

Documentation review date: 2026-07-30.

No exchange adapter is implemented in Phase 00. The notes below record the official
documentation consulted before future collector implementation.

## Coinbase

- Official documentation: Coinbase Exchange WebSocket Overview
- URL: https://docs.cdp.coinbase.com/exchange/websocket-feed/overview
- Official documentation: Coinbase Exchange WebSocket Channels
- URL: https://docs.cdp.coinbase.com/exchange/websocket-feed/channels
- Official documentation: Coinbase Exchange WebSocket Rate Limits
- URL: https://docs.cdp.coinbase.com/exchange/websocket-feed/rate-limits

Planning notes:

- Public market data is available through Coinbase Exchange WebSocket market-data feeds.
- Future collectors must confirm the exact channel selection for BTC-USD trades and book
  updates before implementation.
- Subscription and inbound-message limits must be respected.
- Raw payloads, sequence numbers, exchange timestamps, and local receipt timestamps must
  be preserved for validation.

## Kraken

- Official documentation: Kraken Spot WebSocket Introduction
- URL: https://docs.kraken.com/exchange/guides/websockets/introduction
- Official documentation: Kraken WebSocket v2 Book Checksum
- URL: https://docs.kraken.com/exchange/guides/websockets/book-checksum-v2
- Official documentation root: Kraken API Documentation
- URL: https://docs.kraken.com/

Planning notes:

- Future work should prefer Spot WebSocket v2 for public BTC/USD market data unless a
  specific limitation is discovered.
- Book checksum validation should be included before order-book-derived research is trusted.
- Kraken uses venue-specific instrument naming; normalization must not assume Coinbase
  symbol formats.

## Responsible Collection Policy

- Use only documented public endpoints for market data.
- Respect exchange rate limits and reconnect guidance.
- Store credentials only in local ignored files if later authenticated data is needed.
- Do not distribute restricted raw data.
- Preserve raw data manifests so every research table is traceable to source files and
  collection intervals.

