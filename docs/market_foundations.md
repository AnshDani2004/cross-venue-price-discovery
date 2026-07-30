# Market Foundations

## Phase Objective

Phase 01 defines the initial market universe, research assumptions, and microstructure
concepts that future data collectors and analyses must respect.

This phase does not collect market data, connect to exchanges, estimate lead-lag
relationships, or simulate trading.

## Initial Universe

| Venue | Instrument | Market Type | Role In Phase 01 |
| --- | --- | --- | --- |
| Coinbase | `BTC-USD` | Spot | Candidate price-discovery venue |
| Kraken | `BTC/USD` | Spot | Candidate price-discovery venue |

The initial universe deliberately excludes perpetual futures. A derivatives venue may be
added only after spot collection, normalization, quality checks, and descriptive
lead-lag analysis are reliable.

## Market Microstructure Concepts

### Trade

A trade is an executed transaction. Public trade feeds can reveal where aggressive buying
or selling occurred, but they do not reveal all hidden liquidity or every trader's intent.

### Best Bid And Best Ask

The best bid is the highest visible buy order. The best ask is the lowest visible sell
order. Their difference is the quoted spread.

```text
spread = best_ask - best_bid
```

### Midpoint

The midpoint is a simple estimate of the visible top-of-book fair price.

```text
midpoint = (best_bid + best_ask) / 2
```

The midpoint is useful for descriptive work, but it can be misleading during crossed
books, stale books, fragmented liquidity, or rapid dislocations.

### Price Discovery

Price discovery means the process by which new information is incorporated into prices.
In this project, a venue is said to lead only if its point-in-time updates systematically
precede related price changes on another venue after accounting for timestamp semantics
and data-quality failures.

### Latency

Latency is not one number. Future phases must distinguish:

- Exchange event time
- Local message receipt time
- Parser and validation time
- Simulated decision time
- Simulated order submission time
- Simulated fill time

A signal observed at exchange time may not be tradable if it arrives locally too late.

## Initial Hypotheses

These hypotheses are intentionally modest and testable:

1. BTC spot midpoint returns on Coinbase and Kraken are highly correlated over short
   horizons.
2. Apparent venue leadership may change across time and market regimes.
3. Local receipt timestamps can materially change measured lead-lag results relative to
   exchange timestamps alone.
4. Trade direction and top-of-book imbalance may help explain very short-horizon returns,
   but any predictive value may disappear after spread, fees, latency, and fill
   uncertainty.

These are not conclusions. They are research questions to be tested after data collection
and validation exist.

## Required Measurement Discipline

Future analyses must report:

- Venue universe
- Instrument mapping
- Data interval
- Timestamp basis used for ordering
- Missing-data and sequence-gap handling
- Sampling or event-time alignment method
- Fees, spread assumptions, and latency assumptions when trading relevance is discussed

## Acceptance Criteria For Future Data

Before any Phase 06 lead-lag result is trusted, the dataset must have:

- Raw message retention or reproducible raw-message manifests
- Separate exchange and local receipt timestamps
- Explicit venue and instrument identifiers
- Sequence or checksum validation where the venue supports it
- Duplicate detection
- Gap, reconnect, and outage reporting
- A clear rule for excluding unusable intervals

## Phase 01 Completion Criteria

Phase 01 is complete when:

- The initial spot universe is documented.
- Microstructure terms used by later phases are defined.
- Hypotheses are stated as testable claims, not results.
- The universe configuration can be parsed into validated instrument identifiers.
- Tests prove the initial universe contains exactly Coinbase and Kraken BTC spot markets.
