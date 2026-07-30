# Market Foundations

Review date: 2026-07-30.

## Phase Objective

Phase 01 fixes the first research universe and the market microstructure vocabulary that
later collectors, feature builders, and simulated trading reports must use.

This phase does not collect market data, connect to exchanges, estimate lead-lag
relationships, train models, backtest strategies, or simulate orders.

## Fixed Initial Universe

| Venue | Canonical Instrument | Venue Symbol | Market Type | Data Channels |
| --- | --- | --- | --- | --- |
| Coinbase | `BTC-USD` | `BTC-USD` | Spot | `matches` trades and `ticker` top of book |
| Kraken | `BTC-USD` | `BTC/USD` | Spot | `trade` trades and `ticker` top of book with `event_trigger=bbo` |

The initial scope is deliberately narrow: BTC spot only, exactly Coinbase and Kraken,
and only trades plus top-of-book observations. Full-depth book reconstruction is
deferred because it requires venue-specific sequence and checksum handling before
derived depth features can be trusted.

Perpetual futures, additional venues, additional assets, portfolio construction, and
live execution remain out of scope until the two-venue spot pipeline passes collection
and quality gates.

## Core Microstructure Terms

### Limit Order

A limit order states a maximum buy price or minimum sell price. It can rest in the book
if it is not immediately executable. Resting limit orders provide displayed liquidity but
can be cancelled before another participant trades against them.

### Market Order

A market order, or a marketable order, executes against available resting liquidity. It
usually pays taker fees and can incur slippage if the visible size at the best price is
not enough.

### Trade

A trade is an executed transaction. Public trade feeds can reveal price, size, timestamp,
and sometimes aggressor side. They do not reveal hidden liquidity, all cancelled orders,
or every trader's intent.

Signed trade flow uses aggressor side:

```text
signed_trade_size = trade_size       if aggressor_side = buy
signed_trade_size = -trade_size      if aggressor_side = sell
signed_trade_size = 0                if aggressor_side is unknown
```

### Best Bid, Best Ask, And Top Of Book

The best bid is the highest visible buy price. The best ask is the lowest visible sell
price. The pair is the top of book.

```text
spread = best_ask - best_bid
midpoint = (best_bid + best_ask) / 2
relative_spread = (best_ask - best_bid) / midpoint
```

Edge cases:

- `best_bid >= best_ask` is crossed or locked and must be flagged before research use.
- Zero or negative bid, ask, or displayed size is invalid for normalized observations.
- Missing top-of-book fields make midpoint, spread, and imbalance unavailable.
- A narrow spread does not guarantee executable size at the best price.

### Tick Size

Tick size is the minimum price increment accepted by a venue for a market. One tick of
price movement is:

```text
price_move_ticks = (new_price - old_price) / tick_size
```

The Phase 01 initiating event threshold is one venue-specific tick, configured in
`configs/research.toml` and interpreted through `configs/market_rules.toml`.

### Displayed Depth

Displayed depth is visible size resting at one or more book levels. Phase 01 uses only
best bid size and best ask size because full-depth reconstruction is deferred.

```text
top_of_book_depth = best_bid_size + best_ask_size
```

### Queue Imbalance

Queue imbalance measures relative displayed size at the best prices.

```text
queue_imbalance = (best_bid_size - best_ask_size) / (best_bid_size + best_ask_size)
```

It is undefined when both displayed sizes are zero or missing. It should be treated as a
state variable, not as a causal claim.

### Microprice

Microprice shifts the midpoint toward the side with less displayed liquidity.

```text
microprice =
  (best_ask * best_bid_size + best_bid * best_ask_size)
  / (best_bid_size + best_ask_size)
```

It is undefined when top-of-book sizes are unavailable. A microprice signal can decay
before it is actionable because receipt latency and queue priority matter.

### Order Flow Imbalance

Order flow imbalance is a signed measure of how top-of-book supply and demand change
between observations. A basic top-of-book approximation is:

```text
OFI =
  bid_size_change_when_bid_not_worse
  - ask_size_change_when_ask_not_better
```

The exact formula must be versioned before feature generation because venues can update
prices and sizes with different message semantics.

### Liquidity

Liquidity is the ability to trade size with limited price impact and execution delay.
Displayed top-of-book liquidity is only a partial proxy because hidden orders, queue
position, cancellations, and outages are not visible from public top-of-book feeds.

### Slippage

Slippage is the difference between the decision price and the simulated execution price.

```text
slippage = simulated_fill_price - decision_reference_price
```

For buys, positive slippage is worse. For sells, negative slippage is worse.

### Maker And Taker Fees

Maker fees apply when an order adds resting liquidity. Taker fees apply when an order
removes liquidity. Trading relevance must account for both because a statistically
detectable lead-lag effect can be uneconomic after fees and spread.

```text
round_trip_cost_rate >= entry_fee_rate + exit_fee_rate + relative_spread + slippage_rate
```

Fee values are dated assumptions in `configs/market_rules.toml`, not permanent facts.

### Queue Priority

Queue priority determines when a resting order would fill relative to other orders at
the same price. Public feeds do not fully reveal queue position, so later execution
simulation must use conservative assumptions.

### Adverse Selection

Adverse selection occurs when a fill is more likely after the market has moved against
the order. It is a key reason apparent edge can vanish in realistic simulation.

### Price Discovery

Price discovery is the process by which new information becomes reflected in prices. A
venue leads only if point-in-time observations on that venue systematically precede
related observations on another venue after accounting for timestamp semantics, data
quality failures, and multiple testing.

### Lead-Lag

Lead-lag measures whether movement at an initiating venue is followed by movement at a
response venue over a declared horizon.

```text
response_return(v, h) =
  midpoint_v(first_valid_event_at_or_after t + h) / midpoint_v(t) - 1
```

Lead-lag is descriptive until converted into a decision rule and tested against costs,
latency, fills, and risk.

### Fair Value

Fair value is a model estimate of where the price should be at a future decision horizon.
In this project it must be separated from strategy logic: first estimate value, then
decide whether an action is worth taking after costs and risk.

### Signal Decay

Signal decay is the loss of predictive or economic value as time passes after an event.
For latency-aware trading, a signal observed at exchange time may be unavailable by the
time the local process receives and validates the message.

### Stale Quote

A quote is stale when it remains visible but no longer reflects the current market state.
Stale quotes can be caused by exchange issues, connection gaps, venue-specific update
rules, or local packet delay.

## Timestamp Vocabulary

| Timestamp | Meaning |
| --- | --- |
| `exchange_ts` | Timestamp supplied by the venue message. |
| `local_receipt_ts` | Timestamp captured when the collector receives the message. |
| `processing_ts` | Timestamp captured after parsing and validation. |
| `decision_ts` | Simulation-only timestamp when a decision is made. |
| `simulated_order_submission_ts` | Simulation-only timestamp when an order would be sent. |
| `simulated_order_arrival_ts` | Simulation-only timestamp when an order would reach the venue. |
| `simulated_fill_ts` | Simulation-only timestamp when a fill would be recorded. |

All normalized timestamps must be timezone-aware UTC. Equal timestamps are ordered by
the deterministic tie breaker in `configs/timestamp_policy.toml`.

## Phase 01 Completion Criteria

Phase 01 is complete when:

- The BTC spot scope is fixed to Coinbase and Kraken.
- Trade and top-of-book channels are selected from official documentation.
- Microstructure terms, formulas, and edge cases are documented.
- Instrument, venue, research, timestamp, and market-rule configs validate.
- Research questions and hypotheses are measurable and falsifiable.
- Phase 2 remains limited to public data collection, not trading.
