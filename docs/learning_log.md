# Learning Log

## Phase 00: Project Foundation

### Concepts Introduced

- Point-in-time data integrity
- Separation of research, fair-value estimation, trading decisions, execution simulation,
  and risk management
- Venue-specific identifiers versus normalized research identifiers
- Schema validation as a first line of defense against invalid research data
- Crossed order books and midpoint prices

### Important Formulas

Simple midpoint:

```text
midpoint = (best_bid + best_ask) / 2
```

Required timestamp ordering:

```text
exchange_ts
  <= local_receipt_ts
  <= processing_ts
  <= decision_ts
  <= simulated_order_submission_ts
  <= simulated_fill_ts
```

### Design Decisions

- Start with BTC spot on Coinbase and Kraken only.
- Keep live trading out of scope.
- Use Pydantic schemas for event contracts.
- Store venue-native symbols alongside normalized symbols.
- Make timestamp fields explicit before any feature or label code exists.

### Common Mistakes

- Treating exchange timestamps and local receipt timestamps as interchangeable.
- Building features from a dataframe that already contains future labels.
- Ignoring dropped messages, sequence gaps, or book checksum failures.
- Comparing venues without accounting for clock semantics and local receipt latency.
- Reporting a clean equity curve before validating data quality.

### Questions I Should Be Able To Answer

1. Why is local receipt time different from exchange time?
2. Why can a crossed book invalidate midpoint-based features?
3. Why should research modules be separate from trading policy modules?
4. What information is available at raw collection time versus simulation time?
5. Why is a venue-native symbol stored separately from a normalized research symbol?
6. What would create look-ahead bias in a lead-lag study?
7. Why do negative experiments belong in the experiment log?

### Connections To Quant Research

Research credibility begins with data contracts. A lead-lag estimate is only meaningful
if each observation has known timing semantics and survives basic validity checks.

### Connections To Quant Trading

Trading decisions must be made from information available at the decision timestamp. A
profitable result that relies on fill timestamps, future returns, or post-processed data
at decision time is not tradable.

### Connections To Real Trading Systems

Production systems separate raw ingestion, validation, strategy decisions, execution,
and risk. That separation makes failures easier to diagnose and prevents research code
from silently becoming execution code.

