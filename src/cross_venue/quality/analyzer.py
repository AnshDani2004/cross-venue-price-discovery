"""Session-level Phase 2D data-quality analysis."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from statistics import median

from cross_venue.collectors.base import ParseResult
from cross_venue.collectors.coinbase.parser import parse_coinbase_message
from cross_venue.collectors.kraken.parser import parse_kraken_message
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.io import current_git_commit, portable_relative_path, sha256_text, utc_now
from cross_venue.quality.models import (
    ContinuityMetrics,
    CoverageMetrics,
    DuplicateMetrics,
    QualityDisposition,
    QualityFinding,
    QualitySeverity,
    QuoteMetrics,
    SessionQualityMetrics,
    SessionQualityReport,
    TimestampMetrics,
)
from cross_venue.schemas import Exchange, MarketEventType, NormalizedTopOfBook, NormalizedTrade
from cross_venue.schemas.raw import JsonValue
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import load_manifest
from cross_venue.storage.paths import resolve_under_root
from cross_venue.storage.quality_store import load_quality_summary
from cross_venue.storage.validation import validate_archive


@dataclass(slots=True)
class _RunningState:
    records_seen: int = 0
    market_events: int = 0
    parse_failures: int = 0
    raw_duplicate_count: int = 0
    consecutive_duplicate_count: int = 0
    maximum_duplicate_run: int = 0
    first_duplicate_record_indices: list[int] = field(default_factory=list)
    raw_hash_counts: Counter[str] = field(default_factory=Counter)
    previous_raw_hash: str | None = None
    current_duplicate_run: int = 1
    trade_id_counts: Counter[str] = field(default_factory=Counter)
    trade_content_by_id: dict[str, str] = field(default_factory=dict)
    duplicate_trade_id_count: int = 0
    conflicting_duplicate_trade_count: int = 0
    exact_duplicate_trade_count: int = 0
    coinbase_sequences: list[int] = field(default_factory=list)
    coinbase_missing_sequence_count: int = 0
    kraken_trade_ids: list[int] = field(default_factory=list)
    local_receipts: list[datetime] = field(default_factory=list)
    exchange_timestamps: list[datetime] = field(default_factory=list)
    observed_deltas_ms: list[float] = field(default_factory=list)
    negative_delta_count: int = 0
    missing_exchange_timestamps: int = 0
    equal_receipts: int = 0
    nonmonotonic_receipts: int = 0
    equal_exchange_timestamps: int = 0
    nonmonotonic_exchange_timestamps: int = 0
    quote_states: list[tuple[Decimal, Decimal, Decimal, Decimal, datetime]] = field(
        default_factory=list
    )
    repeated_quote_state_count: int = 0
    bid_only_change_count: int = 0
    ask_only_change_count: int = 0
    both_side_change_count: int = 0
    zero_bid_size_count: int = 0
    zero_ask_size_count: int = 0
    quote_timestamp_reversal_count: int = 0
    locked_market_count: int = 0
    crossed_market_count: int = 0
    missing_bid_count: int = 0
    missing_ask_count: int = 0
    nonpositive_price_count: int = 0
    negative_size_count: int = 0
    first_market_event_ts: datetime | None = None
    last_market_event_ts: datetime | None = None
    first_top_of_book_ts: datetime | None = None
    last_top_of_book_ts: datetime | None = None


def analyze_session_quality(
    session_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    report_path: Path | None = None,
) -> SessionQualityReport:
    """Analyze one finalized Phase 2C raw archive session."""

    session_root = resolve_under_root(storage_config.archive_root, session_path)
    archive_validation = validate_archive(session_root)
    manifest = load_manifest(session_root / "manifest" / "session_manifest.json")
    quality_summary = load_quality_summary(session_root / "quality" / "quality_summary.json")
    state = _RunningState()

    previous_receipt: datetime | None = None
    previous_exchange_ts: datetime | None = None
    input_shard_checksums: dict[str, str] = {}
    for shard in manifest.shards:
        shard_path = session_root / shard.relative_path
        if shard_path.exists():
            input_shard_checksums[shard.relative_path] = sha256_file(shard_path)
        for record in _iter_raw_records(shard_path):
            _observe_raw_record(state, record)
            if previous_receipt is not None:
                if record.local_receipt_ts == previous_receipt:
                    state.equal_receipts += 1
                if record.local_receipt_ts < previous_receipt:
                    state.nonmonotonic_receipts += 1
            previous_receipt = record.local_receipt_ts
            payload = _decode_payload(record)
            if payload is None:
                state.parse_failures += 1
                continue
            _observe_raw_quote_shape(state, manifest.venue, payload)
            result = _parse_payload(manifest.venue, payload, record)
            if result is None:
                state.parse_failures += 1
                continue
            _observe_parse_result(state, result, previous_exchange_ts)
            if result.events:
                previous_exchange_ts = result.events[-1].exchange_ts

    duplicate_metrics = _duplicate_metrics(state)
    continuity_metrics = _continuity_metrics(state, manifest.reconnect_attempts)
    timestamp_metrics = _timestamp_metrics(state)
    quote_metrics = _quote_metrics(
        state,
        stale_threshold_seconds=quality_config.quality.timestamps.stale_quote_threshold_ms / 1000,
        session_duration_seconds=quality_summary.session_duration_seconds,
    )
    coverage_metrics = CoverageMetrics(
        session_duration_seconds=quality_summary.session_duration_seconds,
        frames_received=manifest.frames_received,
        raw_records=state.records_seen,
        trades=manifest.trade_events,
        top_of_book_events=manifest.top_of_book_events,
        control_messages=manifest.control_messages,
        unsupported_messages=manifest.unsupported_messages,
        parse_errors=manifest.parse_errors + state.parse_failures,
        exchange_errors=manifest.exchange_errors,
        reconnects=manifest.reconnect_attempts,
        connections_opened=manifest.connections_opened,
        subscription_acknowledgements=manifest.subscription_acknowledgements,
        frames_per_second=_ratio(
            manifest.frames_received, quality_summary.session_duration_seconds
        ),
        trades_per_second=_ratio(manifest.trade_events, quality_summary.session_duration_seconds),
        top_of_book_events_per_second=_ratio(
            manifest.top_of_book_events,
            quality_summary.session_duration_seconds,
        ),
        archive_bytes=manifest.total_archive_bytes,
        shard_count=len(manifest.shards),
        first_market_event_ts=state.first_market_event_ts,
        last_market_event_ts=state.last_market_event_ts,
        first_top_of_book_ts=state.first_top_of_book_ts,
        last_top_of_book_ts=state.last_top_of_book_ts,
    )
    metrics = SessionQualityMetrics(
        duplicates=duplicate_metrics,
        continuity=continuity_metrics,
        timestamps=timestamp_metrics,
        quotes=quote_metrics,
        coverage=coverage_metrics,
    )
    findings = _build_findings(
        venue=manifest.venue,
        archive_valid=archive_validation.valid,
        archive_errors=archive_validation.errors,
        manifest_records=manifest.records_written,
        quality_summary_writer_failures=quality_summary.writer_failures,
        metrics=metrics,
        quality_config=quality_config,
    )
    disposition, reasons = decide_session_disposition(findings)
    manifest_hash = sha256_file(session_root / "manifest" / "session_manifest.json")
    relative_session = portable_relative_path(storage_config.archive_root, session_root)
    report = SessionQualityReport(
        report_id=f"session-quality-{manifest.session_id}",
        session_id=manifest.session_id,
        venue=manifest.venue,
        canonical_instrument=manifest.canonical_instrument,
        source_session_relative_path=relative_session,
        source_manifest_sha256=manifest_hash,
        quality_policy_version=quality_config.policy_version,
        quality_code_git_commit=current_git_commit(),
        analysis_timestamp=utc_now(),
        input_shard_checksums=input_shard_checksums,
        archive_validation_passed=archive_validation.valid,
        archive_validation_errors=archive_validation.errors,
        metrics=metrics,
        findings=tuple(findings),
        disposition=disposition,
        disposition_reasons=tuple(reasons),
        report_relative_path=(
            portable_relative_path(quality_config.report_root, report_path)
            if report_path is not None and report_path.exists()
            else None
        ),
    )
    return report


def decide_session_disposition(
    findings: list[QualityFinding],
) -> tuple[QualityDisposition, list[str]]:
    """Apply deterministic session disposition ordering."""

    critical_or_error = [
        finding
        for finding in findings
        if finding.severity in {QualitySeverity.CRITICAL, QualitySeverity.ERROR}
    ]
    if critical_or_error:
        return (
            QualityDisposition.REJECTED,
            [f"{finding.finding_id}: {finding.message}" for finding in critical_or_error],
        )
    warnings = [finding for finding in findings if finding.severity == QualitySeverity.WARNING]
    if warnings:
        return (
            QualityDisposition.QUARANTINED,
            [f"{finding.finding_id}: {finding.message}" for finding in warnings],
        )
    return QualityDisposition.ACCEPTED, []


def _iter_raw_records(shard_path: Path) -> Iterable[RawArchiveRecord]:
    with shard_path.open("r", encoding="utf-8") as file_handle:
        for line in file_handle:
            if not line.strip():
                continue
            try:
                yield RawArchiveRecord.from_json_line(line)
            except Exception:
                continue


def _observe_raw_record(state: _RunningState, record: RawArchiveRecord) -> None:
    state.records_seen += 1
    state.local_receipts.append(record.local_receipt_ts)
    raw_hash = sha256_text(f"{record.venue.value}|{record.frame_type}|".encode().hex())[:16]
    raw_hash = sha256_text(f"{raw_hash}|{record.frame_bytes().hex()}")
    state.raw_hash_counts[raw_hash] += 1
    if state.raw_hash_counts[raw_hash] == 2:
        state.raw_duplicate_count += 1
        state.first_duplicate_record_indices.append(record.record_index)
    elif state.raw_hash_counts[raw_hash] > 2:
        state.raw_duplicate_count += 1
    if raw_hash == state.previous_raw_hash:
        state.consecutive_duplicate_count += 1
        state.current_duplicate_run += 1
    else:
        state.current_duplicate_run = 1
    state.maximum_duplicate_run = max(state.maximum_duplicate_run, state.current_duplicate_run)
    state.previous_raw_hash = raw_hash


def _decode_payload(record: RawArchiveRecord) -> dict[str, JsonValue] | None:
    try:
        decoded = json.loads(record.frame_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def _parse_payload(
    venue: Exchange,
    payload: dict[str, JsonValue],
    record: RawArchiveRecord,
) -> ParseResult | None:
    try:
        if venue == Exchange.COINBASE:
            return parse_coinbase_message(
                payload,
                local_receipt_ts=record.local_receipt_ts,
                collector_session_id=record.collector_session_id,
            )
        return parse_kraken_message(
            payload,
            local_receipt_ts=record.local_receipt_ts,
            collector_session_id=record.collector_session_id,
        )
    except Exception:
        return None


def _observe_parse_result(
    state: _RunningState,
    result: ParseResult,
    previous_exchange_ts: datetime | None,
) -> None:
    for event in result.events:
        state.market_events += 1
        state.exchange_timestamps.append(event.exchange_ts)
        delta_ms = (event.local_receipt_ts - event.exchange_ts).total_seconds() * 1000
        state.observed_deltas_ms.append(delta_ms)
        if delta_ms < 0:
            state.negative_delta_count += 1
        if previous_exchange_ts is not None:
            if event.exchange_ts == previous_exchange_ts:
                state.equal_exchange_timestamps += 1
            if event.exchange_ts < previous_exchange_ts:
                state.nonmonotonic_exchange_timestamps += 1
        if state.first_market_event_ts is None:
            state.first_market_event_ts = event.local_receipt_ts
        state.last_market_event_ts = event.local_receipt_ts
        if event.event_type == MarketEventType.TRADE and isinstance(event, NormalizedTrade):
            _observe_trade(state, event)
        if event.event_type == MarketEventType.TOP_OF_BOOK and isinstance(
            event,
            NormalizedTopOfBook,
        ):
            _observe_quote_event(state, event)


def _observe_trade(state: _RunningState, event: NormalizedTrade) -> None:
    trade_key = f"{event.venue.value}:{event.trade_id}"
    trade_content = "|".join(
        [
            str(event.price),
            str(event.quantity),
            event.aggressor_side.value,
            event.exchange_ts.isoformat(),
        ]
    )
    state.trade_id_counts[trade_key] += 1
    if state.trade_id_counts[trade_key] > 1:
        state.duplicate_trade_id_count += 1
        if state.trade_content_by_id[trade_key] == trade_content:
            state.exact_duplicate_trade_count += 1
        else:
            state.conflicting_duplicate_trade_count += 1
    else:
        state.trade_content_by_id[trade_key] = trade_content
    if event.venue == Exchange.COINBASE:
        if isinstance(event.raw_sequence_value, int):
            state.coinbase_sequences.append(event.raw_sequence_value)
        else:
            state.coinbase_missing_sequence_count += 1
    if event.venue == Exchange.KRAKEN and isinstance(event.raw_sequence_value, int):
        state.kraken_trade_ids.append(event.raw_sequence_value)


def _observe_quote_event(state: _RunningState, event: NormalizedTopOfBook) -> None:
    state.zero_bid_size_count += int(event.best_bid_size == 0)
    state.zero_ask_size_count += int(event.best_ask_size == 0)
    quote = (
        event.best_bid_price,
        event.best_bid_size,
        event.best_ask_price,
        event.best_ask_size,
        event.local_receipt_ts,
    )
    if state.first_top_of_book_ts is None:
        state.first_top_of_book_ts = event.local_receipt_ts
    if state.last_top_of_book_ts is not None and event.local_receipt_ts < state.last_top_of_book_ts:
        state.quote_timestamp_reversal_count += 1
    state.last_top_of_book_ts = event.local_receipt_ts
    if state.quote_states:
        previous = state.quote_states[-1]
        same_bid = quote[0] == previous[0] and quote[1] == previous[1]
        same_ask = quote[2] == previous[2] and quote[3] == previous[3]
        if same_bid and same_ask:
            state.repeated_quote_state_count += 1
        elif not same_bid and same_ask:
            state.bid_only_change_count += 1
        elif same_bid and not same_ask:
            state.ask_only_change_count += 1
        else:
            state.both_side_change_count += 1
    state.quote_states.append(quote)


def _observe_raw_quote_shape(
    state: _RunningState,
    venue: Exchange,
    payload: dict[str, JsonValue],
) -> None:
    quote_records: list[dict[str, JsonValue]] = []
    if venue == Exchange.COINBASE and payload.get("type") == "ticker":
        quote_records.append(payload)
    if venue == Exchange.KRAKEN and payload.get("channel") == "ticker":
        data = payload.get("data")
        if isinstance(data, list):
            quote_records.extend(record for record in data if isinstance(record, dict))
    for quote in quote_records:
        bid = _decimal_or_none(quote.get("best_bid" if venue == Exchange.COINBASE else "bid"))
        ask = _decimal_or_none(quote.get("best_ask" if venue == Exchange.COINBASE else "ask"))
        bid_size = _decimal_or_none(
            quote.get("best_bid_size" if venue == Exchange.COINBASE else "bid_qty")
        )
        ask_size = _decimal_or_none(
            quote.get("best_ask_size" if venue == Exchange.COINBASE else "ask_qty")
        )
        state.missing_bid_count += int(bid is None)
        state.missing_ask_count += int(ask is None)
        state.nonpositive_price_count += int(
            (bid is not None and bid <= 0) or (ask is not None and ask <= 0)
        )
        state.negative_size_count += int(
            (bid_size is not None and bid_size < 0) or (ask_size is not None and ask_size < 0)
        )
        if bid is not None and ask is not None:
            if bid == ask:
                state.locked_market_count += 1
            if bid > ask:
                state.crossed_market_count += 1


def _decimal_or_none(value: JsonValue | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _duplicate_metrics(state: _RunningState) -> DuplicateMetrics:
    return DuplicateMetrics(
        exact_raw_duplicate_count=state.raw_duplicate_count,
        exact_raw_duplicate_rate=_proportion(state.raw_duplicate_count, state.records_seen),
        consecutive_duplicate_count=state.consecutive_duplicate_count,
        maximum_duplicate_run=state.maximum_duplicate_run,
        first_duplicate_record_indices=tuple(state.first_duplicate_record_indices[:10]),
        duplicate_trade_id_count=state.duplicate_trade_id_count,
        duplicate_trade_id_rate=_proportion(
            state.duplicate_trade_id_count,
            max(1, sum(state.trade_id_counts.values())),
        ),
        conflicting_duplicate_trade_count=state.conflicting_duplicate_trade_count,
        exact_duplicate_trade_count=state.exact_duplicate_trade_count,
        repeated_quote_state_count=state.repeated_quote_state_count,
    )


def _continuity_metrics(state: _RunningState, reconnects: int) -> ContinuityMetrics:
    coinbase_duplicate = _duplicate_identifier_count(state.coinbase_sequences)
    kraken_duplicate = _duplicate_identifier_count(state.kraken_trade_ids)
    return ContinuityMetrics(
        coinbase_sequence_observations=len(state.coinbase_sequences),
        coinbase_missing_sequence_count=state.coinbase_missing_sequence_count,
        coinbase_duplicate_sequence_count=coinbase_duplicate,
        coinbase_nonmonotonic_sequence_count=_nonmonotonic_count(state.coinbase_sequences),
        coinbase_sequence_discontinuity_count=_positive_jump_count(state.coinbase_sequences),
        kraken_trade_id_observations=len(state.kraken_trade_ids),
        kraken_duplicate_trade_id_count=kraken_duplicate,
        kraken_nonmonotonic_trade_id_count=_nonmonotonic_count(state.kraken_trade_ids),
        kraken_ticker_sequence_checks_skipped=True,
        reconnect_boundaries=reconnects,
    )


def _timestamp_metrics(state: _RunningState) -> TimestampMetrics:
    interarrival_ms = [
        (current - previous).total_seconds() * 1000
        for previous, current in zip(state.local_receipts, state.local_receipts[1:], strict=False)
        if current >= previous
    ]
    return TimestampMetrics(
        missing_receipt_timestamps=0,
        nonmonotonic_receipt_timestamps=state.nonmonotonic_receipts,
        equal_receipt_timestamps=state.equal_receipts,
        min_interarrival_ms=min(interarrival_ms) if interarrival_ms else None,
        median_interarrival_ms=median(interarrival_ms) if interarrival_ms else None,
        p95_interarrival_ms=_percentile(interarrival_ms, 0.95),
        p99_interarrival_ms=_percentile(interarrival_ms, 0.99),
        max_interarrival_ms=max(interarrival_ms) if interarrival_ms else None,
        missing_exchange_timestamps=state.missing_exchange_timestamps,
        missing_exchange_timestamp_rate=_proportion(
            state.missing_exchange_timestamps,
            state.market_events,
        ),
        nonmonotonic_exchange_timestamps=state.nonmonotonic_exchange_timestamps,
        equal_exchange_timestamps=state.equal_exchange_timestamps,
        observed_exchange_receipt_delta_count=len(state.observed_deltas_ms),
        observed_exchange_receipt_delta_min_ms=(
            min(state.observed_deltas_ms) if state.observed_deltas_ms else None
        ),
        observed_exchange_receipt_delta_median_ms=(
            median(state.observed_deltas_ms) if state.observed_deltas_ms else None
        ),
        observed_exchange_receipt_delta_p95_ms=_percentile(state.observed_deltas_ms, 0.95),
        observed_exchange_receipt_delta_p99_ms=_percentile(state.observed_deltas_ms, 0.99),
        observed_exchange_receipt_delta_max_ms=(
            max(state.observed_deltas_ms) if state.observed_deltas_ms else None
        ),
        negative_observed_exchange_receipt_delta_count=state.negative_delta_count,
    )


def _quote_metrics(
    state: _RunningState,
    *,
    stale_threshold_seconds: float,
    session_duration_seconds: float,
) -> QuoteMetrics:
    stale_durations = [
        (current[4] - previous[4]).total_seconds() - stale_threshold_seconds
        for previous, current in zip(state.quote_states, state.quote_states[1:], strict=False)
        if (current[4] - previous[4]).total_seconds() > stale_threshold_seconds
    ]
    total_stale = sum(stale_durations)
    return QuoteMetrics(
        valid_quote_count=len(state.quote_states),
        locked_market_count=state.locked_market_count,
        crossed_market_count=state.crossed_market_count,
        missing_bid_count=state.missing_bid_count,
        missing_ask_count=state.missing_ask_count,
        nonpositive_price_count=state.nonpositive_price_count,
        negative_size_count=state.negative_size_count,
        zero_bid_size_count=state.zero_bid_size_count,
        zero_ask_size_count=state.zero_ask_size_count,
        repeated_quote_state_count=state.repeated_quote_state_count,
        bid_only_change_count=state.bid_only_change_count,
        ask_only_change_count=state.ask_only_change_count,
        both_side_change_count=state.both_side_change_count,
        timestamp_reversal_count=state.quote_timestamp_reversal_count,
        stale_interval_count=len(stale_durations),
        stale_total_duration_seconds=total_stale,
        stale_max_duration_seconds=max(stale_durations) if stale_durations else 0.0,
        stale_percentage_of_session=_proportion(total_stale, session_duration_seconds),
    )


def _build_findings(
    *,
    venue: Exchange,
    archive_valid: bool,
    archive_errors: tuple[str, ...],
    manifest_records: int,
    quality_summary_writer_failures: int,
    metrics: SessionQualityMetrics,
    quality_config: DataQualityConfig,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if not archive_valid:
        findings.append(
            _finding(
                "INTEGRITY_ARCHIVE_VALIDATION_FAILED",
                "integrity",
                QualitySeverity.CRITICAL,
                "archive_validation_passed",
                False,
                True,
                "archive validation failed",
                {"errors": "; ".join(archive_errors[:5])},
            )
        )
    if quality_summary_writer_failures > 0:
        findings.append(
            _finding(
                "INTEGRITY_WRITER_FAILURES",
                "integrity",
                QualitySeverity.CRITICAL,
                "writer_failures",
                quality_summary_writer_failures,
                0,
                "archive writer reported failed records",
                {"writer_failures": quality_summary_writer_failures},
            )
        )
    if metrics.coverage.raw_records < manifest_records:
        findings.append(
            _finding(
                "INTEGRITY_RAW_RECORD_SHORTFALL",
                "integrity",
                QualitySeverity.CRITICAL,
                "raw_records",
                metrics.coverage.raw_records,
                manifest_records,
                "readable raw records are below manifest records_written",
                {"raw_records": metrics.coverage.raw_records},
            )
        )
    parsing = quality_config.quality.parsing
    coverage = quality_config.quality.coverage
    timestamps = quality_config.quality.timestamps
    duplicates = quality_config.quality.duplicates
    calibrated = quality_config.policy_version == "2d.2"
    parse_rate = _proportion(
        metrics.coverage.parse_errors, max(1, metrics.coverage.frames_received)
    )
    if parse_rate > parsing.max_parse_error_rate:
        findings.append(
            _finding(
                "PARSING_ERROR_RATE",
                "parsing",
                QualitySeverity.ERROR,
                "parse_error_rate",
                parse_rate,
                parsing.max_parse_error_rate,
                "parse-error rate exceeds policy",
                {"parse_errors": metrics.coverage.parse_errors},
            )
        )
    unsupported_rate = _proportion(
        metrics.coverage.unsupported_messages,
        max(1, metrics.coverage.frames_received),
    )
    if unsupported_rate > parsing.max_unsupported_message_rate:
        findings.append(
            _finding(
                "PARSING_UNSUPPORTED_RATE",
                "parsing",
                QualitySeverity.WARNING,
                "unsupported_message_rate",
                unsupported_rate,
                parsing.max_unsupported_message_rate,
                "unsupported-message rate exceeds policy",
                {"unsupported_messages": metrics.coverage.unsupported_messages},
            )
        )
    if metrics.coverage.session_duration_seconds < coverage.minimum_session_duration_seconds:
        findings.append(
            _finding(
                "COVERAGE_SESSION_TOO_SHORT",
                "coverage",
                QualitySeverity.ERROR,
                "session_duration_seconds",
                metrics.coverage.session_duration_seconds,
                coverage.minimum_session_duration_seconds,
                "session duration is below policy",
                {"frames_received": metrics.coverage.frames_received},
            )
        )
    if metrics.coverage.frames_received < coverage.minimum_frames_per_venue:
        findings.append(
            _finding(
                "COVERAGE_FRAMES_TOO_LOW",
                "coverage",
                QualitySeverity.ERROR,
                "frames_received",
                metrics.coverage.frames_received,
                coverage.minimum_frames_per_venue,
                "frame count is below policy",
                {"raw_records": metrics.coverage.raw_records},
            )
        )
    if metrics.coverage.trades < coverage.minimum_trades_per_venue:
        findings.append(
            _finding(
                "COVERAGE_TRADES_TOO_LOW",
                "coverage",
                QualitySeverity.ERROR,
                "trades",
                metrics.coverage.trades,
                coverage.minimum_trades_per_venue,
                "trade count is below policy",
                {"trades": metrics.coverage.trades},
            )
        )
    if metrics.coverage.top_of_book_events < coverage.minimum_top_of_book_events_per_venue:
        findings.append(
            _finding(
                "COVERAGE_TOP_OF_BOOK_TOO_LOW",
                "coverage",
                QualitySeverity.ERROR,
                "top_of_book_events",
                metrics.coverage.top_of_book_events,
                coverage.minimum_top_of_book_events_per_venue,
                "top-of-book count is below policy",
                {"top_of_book_events": metrics.coverage.top_of_book_events},
            )
        )
    if (
        metrics.timestamps.nonmonotonic_receipt_timestamps
        > timestamps.max_nonmonotonic_receipt_events
    ):
        findings.append(
            _finding(
                "TIMESTAMP_RECEIPT_NONMONOTONIC",
                "timestamps",
                QualitySeverity.ERROR,
                "nonmonotonic_receipt_timestamps",
                metrics.timestamps.nonmonotonic_receipt_timestamps,
                timestamps.max_nonmonotonic_receipt_events,
                "receipt timestamps are nonmonotonic in archive order",
                {"ordering": "record_index"},
            )
        )
    if (
        metrics.timestamps.missing_exchange_timestamp_rate
        > timestamps.max_missing_exchange_timestamp_rate
    ):
        findings.append(
            _finding(
                "TIMESTAMP_EXCHANGE_MISSING_RATE",
                "timestamps",
                QualitySeverity.WARNING,
                "missing_exchange_timestamp_rate",
                metrics.timestamps.missing_exchange_timestamp_rate,
                timestamps.max_missing_exchange_timestamp_rate,
                "exchange timestamp missing rate exceeds policy",
                {"market_events": metrics.coverage.trades + metrics.coverage.top_of_book_events},
            )
        )
    if metrics.timestamps.negative_observed_exchange_receipt_delta_count > 0:
        if calibrated:
            delta_class = _delta_pattern_classification(metrics, quality_config)
            findings.append(
                _finding(
                    "TIMESTAMP_OBSERVED_EXCHANGE_RECEIPT_DELTA_PATTERN",
                    "timestamps",
                    _configured_severity(
                        _delta_classification_severity(delta_class, quality_config)
                    ),
                    "observed_exchange_receipt_delta_pattern",
                    delta_class,
                    None,
                    (
                        "observed exchange-receipt delta pattern is preserved as a "
                        "clock/feed diagnostic, not one-way latency"
                    ),
                    {
                        "delta_name": "observed_exchange_receipt_delta",
                        "negative_count": (
                            metrics.timestamps.negative_observed_exchange_receipt_delta_count
                        ),
                        "eligible_events": (
                            metrics.timestamps.observed_exchange_receipt_delta_count
                        ),
                        "median_ms": (metrics.timestamps.observed_exchange_receipt_delta_median_ms),
                        "p95_ms": metrics.timestamps.observed_exchange_receipt_delta_p95_ms,
                        "p99_ms": metrics.timestamps.observed_exchange_receipt_delta_p99_ms,
                    },
                )
            )
        else:
            findings.append(
                _finding(
                    "TIMESTAMP_NEGATIVE_OBSERVED_EXCHANGE_RECEIPT_DELTA",
                    "timestamps",
                    QualitySeverity.WARNING,
                    "negative_observed_exchange_receipt_delta_count",
                    metrics.timestamps.negative_observed_exchange_receipt_delta_count,
                    0,
                    "observed exchange-receipt delta has negative values; this is not latency",
                    {"delta_name": "observed_exchange_receipt_delta"},
                )
            )
    if metrics.duplicates.exact_raw_duplicate_rate > duplicates.max_exact_raw_duplicate_rate:
        duplicate_severity = QualitySeverity.WARNING
        duplicate_id = "DUPLICATES_RAW_FRAME_RATE"
        duplicate_message = "exact raw-frame duplicate rate exceeds policy"
        if calibrated and venue == Exchange.KRAKEN:
            duplicate_id = "DUPLICATES_KRAKEN_TYPED_RAW_FRAME"
            duplicate_message = (
                "Kraken exact raw-frame duplicates are typed by control, ticker, and trade "
                "semantics; aggregate rate is diagnostic only"
            )
            duplicate_severity = (
                QualitySeverity.WARNING
                if metrics.duplicates.duplicate_trade_id_count > 0
                else _configured_severity(
                    quality_config.quality.kraken_duplicates.heartbeat_duplicate_severity
                )
            )
        findings.append(
            _finding(
                duplicate_id,
                "duplicates",
                duplicate_severity,
                "exact_raw_duplicate_rate",
                metrics.duplicates.exact_raw_duplicate_rate,
                duplicates.max_exact_raw_duplicate_rate,
                duplicate_message,
                {
                    "duplicate_count": metrics.duplicates.exact_raw_duplicate_count,
                    "raw_duplicate_rate_preserved": metrics.duplicates.exact_raw_duplicate_rate,
                },
            )
        )
    if metrics.duplicates.duplicate_trade_id_rate > duplicates.max_duplicate_trade_id_rate:
        findings.append(
            _finding(
                "DUPLICATES_TRADE_ID_RATE",
                "duplicates",
                QualitySeverity.WARNING,
                "duplicate_trade_id_rate",
                metrics.duplicates.duplicate_trade_id_rate,
                duplicates.max_duplicate_trade_id_rate,
                "duplicate trade identifier rate exceeds policy",
                {"duplicate_trade_id_count": metrics.duplicates.duplicate_trade_id_count},
            )
        )
    if metrics.duplicates.conflicting_duplicate_trade_count > 0:
        findings.append(
            _finding(
                "DUPLICATES_CONFLICTING_TRADE",
                "duplicates",
                QualitySeverity.ERROR,
                "conflicting_duplicate_trade_count",
                metrics.duplicates.conflicting_duplicate_trade_count,
                0,
                "duplicate trade identifiers have conflicting contents",
                {"conflicts": metrics.duplicates.conflicting_duplicate_trade_count},
            )
        )
    if calibrated:
        _extend_calibrated_continuity_findings(findings, metrics, quality_config, venue)
    else:
        sequence_anomalies = (
            metrics.continuity.coinbase_duplicate_sequence_count
            + metrics.continuity.coinbase_nonmonotonic_sequence_count
            + metrics.continuity.coinbase_sequence_discontinuity_count
            + metrics.continuity.kraken_duplicate_trade_id_count
            + metrics.continuity.kraken_nonmonotonic_trade_id_count
        )
        if sequence_anomalies > 0:
            findings.append(
                _finding(
                    "CONTINUITY_IDENTIFIER_ANOMALY",
                    "continuity",
                    QualitySeverity.WARNING,
                    "identifier_anomaly_count",
                    sequence_anomalies,
                    0,
                    "identifier continuity diagnostics require review",
                    {"kraken_ticker_sequence_checks_skipped": True},
                )
            )
    quote_failures = metrics.quotes.locked_market_count + metrics.quotes.crossed_market_count
    if quote_failures > 0:
        findings.append(
            _finding(
                "QUOTES_LOCKED_OR_CROSSED",
                "quotes",
                QualitySeverity.ERROR,
                "locked_crossed_quote_count",
                quote_failures,
                0,
                "locked or crossed quotes were observed in raw evidence",
                {
                    "locked": metrics.quotes.locked_market_count,
                    "crossed": metrics.quotes.crossed_market_count,
                },
                affected_channel="ticker",
            )
        )
    if metrics.quotes.stale_interval_count > 0:
        quote_severity = QualitySeverity.WARNING
        quote_finding_id = "QUOTES_STALE_INTERVALS"
        quote_message = "stale quote intervals require review"
        if calibrated:
            quote_severity = _configured_severity(
                quality_config.quality.quote_freshness.quote_age_severity
            )
            quote_finding_id = "QUOTES_AGE_DIAGNOSTIC"
            quote_message = (
                "quote age exceeded threshold; freshness interpretation is separated from "
                "connection inactivity and documented feed semantics"
            )
        findings.append(
            _finding(
                quote_finding_id,
                "quotes",
                quote_severity,
                "stale_interval_count",
                metrics.quotes.stale_interval_count,
                0,
                quote_message,
                {"stale_threshold_ms": timestamps.stale_quote_threshold_ms},
                affected_channel="ticker",
            )
        )
    return findings


def _finding(
    finding_id: str,
    category: str,
    severity: QualitySeverity,
    metric: str,
    observed_value: str | int | float | bool | None,
    threshold: str | int | float | bool | None,
    message: str,
    evidence: dict[str, str | int | float | bool | None],
    *,
    affected_channel: str | None = None,
) -> QualityFinding:
    return QualityFinding(
        finding_id=finding_id,
        category=category,
        severity=severity,
        metric=metric,
        observed_value=observed_value,
        threshold=threshold,
        message=message,
        evidence=evidence,
        affected_channel=affected_channel,
    )


def _configured_severity(value: str) -> QualitySeverity:
    return {
        "info": QualitySeverity.INFO,
        "warning": QualitySeverity.WARNING,
        "error": QualitySeverity.ERROR,
        "critical": QualitySeverity.CRITICAL,
    }[value]


def _delta_pattern_classification(
    metrics: SessionQualityMetrics,
    quality_config: DataQualityConfig,
) -> str:
    policy = quality_config.quality.exchange_receipt_delta
    count = metrics.timestamps.observed_exchange_receipt_delta_count
    if count < policy.minimum_events_for_classification:
        return "INSUFFICIENT_EVIDENCE"
    negative_rate = _proportion(
        metrics.timestamps.negative_observed_exchange_receipt_delta_count,
        count,
    )
    minimum = metrics.timestamps.observed_exchange_receipt_delta_min_ms
    maximum = metrics.timestamps.observed_exchange_receipt_delta_max_ms
    p95 = metrics.timestamps.observed_exchange_receipt_delta_p95_ms
    median_value = metrics.timestamps.observed_exchange_receipt_delta_median_ms
    if minimum is None or maximum is None or p95 is None or median_value is None:
        return "INSUFFICIENT_EVIDENCE"
    spread = maximum - minimum
    upper_spread = abs(p95 - median_value)
    if negative_rate >= policy.stable_negative_rate and spread <= policy.stable_max_iqr_ms:
        return "STABLE_OFFSET"
    if (
        negative_rate >= policy.stable_negative_rate
        and upper_spread <= policy.low_variance_max_iqr_ms
    ):
        return "LOW_VARIANCE_OFFSET"
    if negative_rate <= policy.sporadic_negative_rate:
        return "SPORADIC_OUTLIERS"
    if spread >= policy.unstable_min_iqr_ms:
        return "UNSTABLE_OFFSET"
    return "MIXED_DISTRIBUTION"


def _delta_classification_severity(
    classification: str,
    quality_config: DataQualityConfig,
) -> str:
    policy = quality_config.quality.exchange_receipt_delta
    severities = {
        "STABLE_OFFSET": policy.stable_offset_severity,
        "LOW_VARIANCE_OFFSET": policy.low_variance_offset_severity,
        "MIXED_DISTRIBUTION": policy.mixed_distribution_severity,
        "SPORADIC_OUTLIERS": policy.sporadic_outlier_severity,
        "UNSTABLE_OFFSET": policy.unstable_offset_severity,
        "INSUFFICIENT_EVIDENCE": policy.insufficient_evidence_severity,
    }
    return severities[classification]


def _extend_calibrated_continuity_findings(
    findings: list[QualityFinding],
    metrics: SessionQualityMetrics,
    quality_config: DataQualityConfig,
    venue: Exchange,
) -> None:
    if venue == Exchange.COINBASE:
        coinbase = quality_config.quality.coinbase_continuity
        if metrics.continuity.coinbase_sequence_discontinuity_count > 0:
            findings.append(
                _finding(
                    "CONTINUITY_COINBASE_PRODUCT_SEQUENCE_DIAGNOSTIC",
                    "continuity",
                    _configured_severity(coinbase.product_sequence_jump_severity),
                    "coinbase_sequence_discontinuity_count",
                    metrics.continuity.coinbase_sequence_discontinuity_count,
                    None,
                    (
                        "Coinbase product-level sequence jumps are diagnostic under the "
                        "current partial subscription unless trade identifiers show loss"
                    ),
                    {
                        "partial_subscription": True,
                        "duplicate_sequences": (
                            metrics.continuity.coinbase_duplicate_sequence_count
                        ),
                        "nonmonotonic_sequences": (
                            metrics.continuity.coinbase_nonmonotonic_sequence_count
                        ),
                    },
                )
            )
        if metrics.continuity.coinbase_nonmonotonic_sequence_count > 0:
            findings.append(
                _finding(
                    "CONTINUITY_COINBASE_NONMONOTONIC_SEQUENCE",
                    "continuity",
                    _configured_severity(coinbase.nonmonotonic_sequence_severity),
                    "coinbase_nonmonotonic_sequence_count",
                    metrics.continuity.coinbase_nonmonotonic_sequence_count,
                    0,
                    "Coinbase subscribed sequence observations are nonmonotonic",
                    {"partial_subscription": True},
                )
            )
        return

    kraken_trade_anomalies = (
        metrics.continuity.kraken_duplicate_trade_id_count
        + metrics.continuity.kraken_nonmonotonic_trade_id_count
    )
    if kraken_trade_anomalies > 0:
        findings.append(
            _finding(
                "CONTINUITY_KRAKEN_TRADE_ID_DIAGNOSTIC",
                "continuity",
                QualitySeverity.WARNING,
                "kraken_trade_identifier_anomaly_count",
                kraken_trade_anomalies,
                0,
                "Kraken trade identifier anomalies require review; ticker sequence is not analyzed",
                {"kraken_ticker_sequence_checks_skipped": True},
            )
        )


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _proportion(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def _duplicate_identifier_count(values: list[int]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _nonmonotonic_count(values: list[int]) -> int:
    return sum(1 for previous, current in pairwise(values) if current < previous)


def _positive_jump_count(values: list[int]) -> int:
    return sum(1 for previous, current in pairwise(values) if current > previous + 1)
