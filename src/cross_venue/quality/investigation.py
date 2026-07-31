"""Investigation tooling for Phase 2D quarantine findings."""

from __future__ import annotations

import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.io import current_git_commit, sha256_text, utc_now
from cross_venue.quality.models import PairedQualityReport, SessionQualityReport
from cross_venue.schemas import Exchange
from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json
from cross_venue.storage.paths import resolve_under_root

MAX_EXAMPLES = 10
COINBASE_DOCS_URL = "https://docs.cdp.coinbase.com/exchange/websocket-feed/channels"


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """Paths and reports produced by a quarantine investigation."""

    report: dict[str, Any]
    recommendations: dict[str, Any]
    output_root: Path
    json_path: Path
    markdown_path: Path
    recommendations_path: Path

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Paired collection ID: {self.report['paired_collection_id']}",
                f"Output root: {self.output_root}",
                f"JSON report: {self.json_path}",
                f"Markdown report: {self.markdown_path}",
                f"Policy recommendations: {self.recommendations_path}",
            ]
        )


@dataclass(slots=True)
class _RawMessage:
    record_index: int
    venue: Exchange
    local_receipt_ts: datetime
    frame_hash: str
    payload: dict[str, Any]

    @property
    def message_type(self) -> str:
        if self.venue == Exchange.COINBASE:
            return str(self.payload.get("type", "unknown"))
        return str(self.payload.get("type", self.payload.get("method", "update")))

    @property
    def channel(self) -> str:
        if self.venue == Exchange.COINBASE:
            message_type = self.message_type
            if message_type in {"match", "last_match"}:
                return "matches"
            if message_type == "ticker":
                return "ticker"
            if message_type == "heartbeat":
                return "heartbeat"
            if message_type == "subscriptions":
                return "subscriptions"
            return message_type
        method = self.payload.get("method")
        if method == "subscribe":
            result = self.payload.get("result")
            if isinstance(result, dict):
                return str(result.get("channel", "subscribe"))
            return "subscribe"
        return str(self.payload.get("channel", "unknown"))


@dataclass(slots=True)
class _QuoteEvent:
    record_index: int
    venue: Exchange
    local_receipt_ts: datetime
    channel: str
    bid: str
    bid_size: str
    ask: str
    ask_size: str

    @property
    def state(self) -> tuple[str, str, str, str]:
        return (self.bid, self.bid_size, self.ask, self.ask_size)

    @property
    def prices(self) -> tuple[str, str]:
        return (self.bid, self.ask)


def investigate_quality_findings(
    paired_report_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
) -> InvestigationResult:
    """Investigate existing quarantined quality findings without mutating inputs."""

    paired_path = resolve_under_root(quality_config.report_root, paired_report_path)
    paired_report = PairedQualityReport.model_validate_json(paired_path.read_text(encoding="utf-8"))
    output_root = quality_config.report_root / "investigations" / paired_report.paired_collection_id
    sessions = {
        "coinbase": _session_payload(
            paired_report.coinbase_report,
            storage_config=storage_config,
            quality_config=quality_config,
        ),
        "kraken": _session_payload(
            paired_report.kraken_report,
            storage_config=storage_config,
            quality_config=quality_config,
        ),
    }
    report: dict[str, Any] = {
        "report_schema_version": "0.1.0",
        "paired_collection_id": paired_report.paired_collection_id,
        "created_at": utc_now().isoformat(),
        "quality_policy_version": quality_config.policy_version,
        "quality_code_git_commit": current_git_commit(),
        "source_paired_report": str(paired_report_path),
        "source_paired_report_sha256": sha256_file(paired_path),
        "host_clock": _host_clock_info(),
        "official_sources": {
            "coinbase_exchange_websocket_channels": COINBASE_DOCS_URL,
        },
        "sessions": sessions,
        "summary": _summary_classifications(sessions),
    }
    recommendations = _policy_recommendations(paired_report, report)
    json_path = output_root / "investigation_report.json"
    markdown_path = output_root / "investigation_report.md"
    recommendations_path = output_root / "policy_recommendations.json"
    atomic_write_json(json_path, report)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_markdown_report(report, recommendations), encoding="utf-8")
    atomic_write_json(recommendations_path, recommendations)
    return InvestigationResult(
        report=report,
        recommendations=recommendations,
        output_root=output_root,
        json_path=json_path,
        markdown_path=markdown_path,
        recommendations_path=recommendations_path,
    )


def _session_payload(
    report: SessionQualityReport,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
) -> dict[str, Any]:
    session_path = resolve_under_root(
        storage_config.archive_root,
        storage_config.archive_root / report.source_session_relative_path,
    )
    messages = list(_iter_messages(session_path))
    quote_events = _quote_events(messages)
    stale = _stale_investigation(
        messages,
        quote_events,
        threshold_seconds=quality_config.quality.timestamps.stale_quote_threshold_ms / 1000,
    )
    payload = {
        "session_id": report.session_id,
        "venue": report.venue.value,
        "source_session_relative_path": report.source_session_relative_path,
        "source_manifest_sha256": report.source_manifest_sha256,
        "input_shard_checksums": report.input_shard_checksums,
        "negative_delta": _negative_delta_investigation(messages),
        "quote_staleness": stale,
    }
    if report.venue == Exchange.COINBASE:
        payload["coinbase_continuity"] = _coinbase_continuity(messages)
    if report.venue == Exchange.KRAKEN:
        payload["kraken_duplicates"] = _kraken_duplicates(messages, quote_events)
    return payload


def _iter_messages(session_path: Path) -> Iterable[_RawMessage]:
    for shard_path in sorted((session_path / "raw").glob("*.jsonl")):
        with shard_path.open("r", encoding="utf-8") as file_handle:
            for line in file_handle:
                if not line.strip():
                    continue
                record = RawArchiveRecord.from_json_line(line)
                try:
                    payload = json.loads(record.frame_bytes().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                yield _RawMessage(
                    record_index=record.record_index,
                    venue=record.venue,
                    local_receipt_ts=record.local_receipt_ts,
                    frame_hash=sha256_text(
                        f"{record.venue.value}|{record.frame_type}|{record.frame_bytes().hex()}"
                    ),
                    payload=payload,
                )


def _negative_delta_investigation(messages: list[_RawMessage]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    all_events: list[dict[str, Any]] = []
    for message in messages:
        for exchange_ts in _exchange_timestamps(message):
            delta_ms = (message.local_receipt_ts - exchange_ts).total_seconds() * 1000
            event = {
                "record_index": message.record_index,
                "local_receipt_ts": message.local_receipt_ts.isoformat(),
                "exchange_ts": exchange_ts.isoformat(),
                "observed_exchange_receipt_delta_ms": delta_ms,
                "channel": message.channel,
                "message_type": message.message_type,
                "connection_epoch": 0,
            }
            grouped[(message.channel, message.message_type, "0")].append(event)
            all_events.append(event)
    groups = []
    for (channel, message_type, epoch), events in sorted(grouped.items()):
        groups.append(
            {
                "channel": channel,
                "message_type": message_type,
                "connection_epoch": int(epoch),
                **_delta_stats(events),
                "classification": _delta_classification(
                    [event["observed_exchange_receipt_delta_ms"] for event in events]
                ),
                "one_minute_windows": _minute_windows(events),
            }
        )
    return {
        "total_eligible_events": len(all_events),
        **_delta_stats(all_events),
        "classification": _delta_classification(
            [event["observed_exchange_receipt_delta_ms"] for event in all_events]
        ),
        "by_channel_message_type_epoch": groups,
    }


def _coinbase_continuity(messages: list[_RawMessage]) -> dict[str, Any]:
    sequenced = [
        message
        for message in messages
        if message.payload.get("product_id") == "BTC-USD"
        and isinstance(message.payload.get("sequence"), int)
    ]
    discontinuities = []
    duplicates = []
    nonmonotonic = []
    seen: set[int] = set()
    previous: _RawMessage | None = None
    for message in sequenced:
        sequence = int(message.payload["sequence"])
        if sequence in seen:
            duplicates.append(_sequence_example(previous, message, "duplicate sequence"))
        seen.add(sequence)
        if previous is not None:
            previous_sequence = int(previous.payload["sequence"])
            if sequence < previous_sequence:
                nonmonotonic.append(_sequence_example(previous, message, "out-of-order sequence"))
            if sequence > previous_sequence + 1:
                discontinuities.append(
                    _sequence_example(previous, message, "product-level sequence discontinuity")
                )
        previous = message
    by_type: dict[str, list[int]] = defaultdict(list)
    for message in sequenced:
        by_type[message.message_type].append(int(message.payload["sequence"]))
    message_type_view = {
        message_type: {
            "observations": len(values),
            "duplicate_sequences": _duplicate_count(values),
            "nonmonotonic_sequences": _nonmonotonic_count(values),
            "numeric_discontinuities": _jump_count(values),
            "classification": (
                "per-message-type diagnostic jump"
                if _jump_count(values) > 0
                else "insufficient evidence"
                if len(values) < 2
                else "no diagnostic jump"
            ),
        }
        for message_type, values in sorted(by_type.items())
    }
    trade_view = _coinbase_trade_continuity(messages)
    classification = (
        "confirmed missing-match evidence"
        if trade_view["suspicious_intervals"]
        else "product-level sequence discontinuity"
        if discontinuities
        else "duplicate sequence"
        if duplicates
        else "out-of-order sequence"
        if nonmonotonic
        else "insufficient evidence"
    )
    return {
        "official_feed_notes": {
            "heartbeat": (
                "Coinbase heartbeat messages include sequence numbers and last_trade_id values."
            ),
            "matches": (
                "Coinbase documents that matches-channel messages can be dropped; "
                "heartbeat can track last trade IDs."
            ),
            "ticker": "Coinbase ticker batches updates in cascading matches.",
            "source": COINBASE_DOCS_URL,
        },
        "product_wide_view": {
            "observations": len(sequenced),
            "duplicate_sequences": len(duplicates),
            "nonmonotonic_sequences": len(nonmonotonic),
            "numeric_discontinuities": len(discontinuities),
            "examples": _bounded(discontinuities + duplicates + nonmonotonic),
        },
        "message_type_diagnostic_view": message_type_view,
        "trade_continuity_view": trade_view,
        "classification": classification,
    }


def _coinbase_trade_continuity(messages: list[_RawMessage]) -> dict[str, Any]:
    observed_matches: list[_RawMessage] = [
        message for message in messages if message.message_type in {"match", "last_match"}
    ]
    match_trade_ids = [
        int(message.payload["trade_id"])
        for message in observed_matches
        if isinstance(message.payload.get("trade_id"), int)
    ]
    heartbeat_last_trade_ids = [
        (message, int(message.payload["last_trade_id"]))
        for message in messages
        if message.message_type == "heartbeat"
        and isinstance(message.payload.get("last_trade_id"), int)
    ]
    ticker_trade_ids = [
        int(message.payload["trade_id"])
        for message in messages
        if message.message_type == "ticker" and isinstance(message.payload.get("trade_id"), int)
    ]
    suspicious = []
    observed_set = set(match_trade_ids)
    for heartbeat, last_trade_id in heartbeat_last_trade_ids:
        missing = [
            trade_id
            for trade_id in range(min(match_trade_ids or [last_trade_id]), last_trade_id + 1)
            if trade_id not in observed_set
        ]
        if missing:
            previous_observed = max(
                (tid for tid in match_trade_ids if tid < last_trade_id), default=None
            )
            next_observed = min(
                (tid for tid in match_trade_ids if tid > last_trade_id), default=None
            )
            suspicious.append(
                {
                    "previous_observed_trade_id": previous_observed,
                    "next_observed_trade_id": next_observed,
                    "heartbeat_last_trade_id": last_trade_id,
                    "missing_trade_id_sample": missing[:MAX_EXAMPLES],
                    "heartbeat_record_index": heartbeat.record_index,
                    "connection_epoch": 0,
                    "nearby_message_types": _nearby_message_types(messages, heartbeat.record_index),
                    "reconnect_occurred": False,
                    "classification": "confirmed missing-match evidence",
                }
            )
    return {
        "observed_match_trade_id_count": len(match_trade_ids),
        "heartbeat_last_trade_id_count": len(heartbeat_last_trade_ids),
        "ticker_trade_id_count": len(ticker_trade_ids),
        "suspicious_intervals": _bounded(suspicious),
    }


def _kraken_duplicates(
    messages: list[_RawMessage],
    quote_events: list[_QuoteEvent],
) -> dict[str, Any]:
    by_hash: dict[str, list[_RawMessage]] = defaultdict(list)
    for message in messages:
        by_hash[message.frame_hash].append(message)
    duplicate_groups = [items for items in by_hash.values() if len(items) > 1]
    classified = []
    for group in duplicate_groups:
        first = group[0]
        classified.append(
            {
                "exact_raw_hash": first.frame_hash,
                "classification": _kraken_message_classification(first),
                "duplicate_count": len(group) - 1,
                "affected_record_indices": [
                    message.record_index for message in group[:MAX_EXAMPLES]
                ],
                "connection_epoch": 0,
                "whether_normalized_events_were_duplicated": _kraken_has_market_event(first),
                "suggested_severity": _kraken_duplicate_severity(first),
            }
        )
    trade_groups = _kraken_trade_duplicates(messages)
    ticker_groups = _kraken_ticker_duplicates(quote_events)
    return {
        "duplicate_count": sum(len(group) - 1 for group in duplicate_groups),
        "duplicate_rate": _ratio(sum(len(group) - 1 for group in duplicate_groups), len(messages)),
        "consecutive_duplicate_count": _consecutive_duplicate_count(messages),
        "maximum_consecutive_run": _maximum_duplicate_run(messages),
        "groups_by_raw_hash": _bounded(classified),
        "trade_duplicate_view": trade_groups,
        "ticker_duplicate_view": ticker_groups,
        "ticker_sequence_analysis_performed": False,
    }


def _stale_investigation(
    messages: list[_RawMessage],
    quote_events: list[_QuoteEvent],
    *,
    threshold_seconds: float,
) -> dict[str, Any]:
    intervals = []
    for before, after in pairwise(quote_events):
        duration = (after.local_receipt_ts - before.local_receipt_ts).total_seconds()
        if duration <= threshold_seconds:
            continue
        interval_messages = [
            message
            for message in messages
            if before.local_receipt_ts < message.local_receipt_ts < after.local_receipt_ts
        ]
        trades = [message for message in interval_messages if _is_trade_message(message)]
        controls = [message for message in interval_messages if _is_control_message(message)]
        heartbeats = [message for message in interval_messages if message.channel == "heartbeat"]
        classification = _stale_classification(before, after, interval_messages, trades, heartbeats)
        intervals.append(
            {
                "venue": before.venue.value,
                "start_receipt_ts": before.local_receipt_ts.isoformat(),
                "end_receipt_ts": after.local_receipt_ts.isoformat(),
                "duration_seconds": duration,
                "connection_epoch": 0,
                "frames_received_during_interval": len(interval_messages),
                "heartbeats_received": len(heartbeats),
                "control_messages_received": len(controls),
                "trades_received": len(trades),
                "other_market_events_received": sum(
                    1 for message in interval_messages if message.channel == "ticker"
                ),
                "other_venue_active_status": "not evaluated in session-level investigation",
                "reconnect_occurrence": False,
                "last_bbo_before_interval": {
                    "bid": before.bid,
                    "bid_size": before.bid_size,
                    "ask": before.ask,
                    "ask_size": before.ask_size,
                },
                "first_bbo_after_interval": {
                    "bid": after.bid,
                    "bid_size": after.bid_size,
                    "ask": after.ask,
                    "ask_size": after.ask_size,
                },
                "stale_concepts": {
                    "quote_age": duration,
                    "connection_inactivity": len(interval_messages) == 0,
                    "market_activity_without_quote_refresh": len(trades) > 0,
                },
                "classification": classification,
            }
        )
    return {
        "threshold_seconds": threshold_seconds,
        "interval_count": len(intervals),
        "classifications": dict(Counter(item["classification"] for item in intervals)),
        "interval_examples": _bounded(intervals),
    }


def _quote_events(messages: list[_RawMessage]) -> list[_QuoteEvent]:
    events: list[_QuoteEvent] = []
    for message in messages:
        if message.venue == Exchange.COINBASE and message.message_type == "ticker":
            events.append(
                _QuoteEvent(
                    record_index=message.record_index,
                    venue=message.venue,
                    local_receipt_ts=message.local_receipt_ts,
                    channel="ticker",
                    bid=str(message.payload.get("best_bid")),
                    bid_size=str(message.payload.get("best_bid_size")),
                    ask=str(message.payload.get("best_ask")),
                    ask_size=str(message.payload.get("best_ask_size")),
                )
            )
        if message.venue == Exchange.KRAKEN and message.channel == "ticker":
            data = message.payload.get("data")
            if isinstance(data, list):
                for record in data:
                    if isinstance(record, dict):
                        events.append(
                            _QuoteEvent(
                                record_index=message.record_index,
                                venue=message.venue,
                                local_receipt_ts=message.local_receipt_ts,
                                channel="ticker",
                                bid=str(record.get("bid")),
                                bid_size=str(record.get("bid_qty")),
                                ask=str(record.get("ask")),
                                ask_size=str(record.get("ask_qty")),
                            )
                        )
    return events


def _exchange_timestamps(message: _RawMessage) -> list[datetime]:
    values: list[str] = []
    if message.venue == Exchange.COINBASE and isinstance(message.payload.get("time"), str):
        values.append(str(message.payload["time"]))
    if message.venue == Exchange.KRAKEN:
        data = message.payload.get("data")
        if isinstance(data, list):
            for record in data:
                if isinstance(record, dict) and isinstance(record.get("timestamp"), str):
                    values.append(str(record["timestamp"]))
    parsed = []
    for value in values:
        try:
            parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC))
        except ValueError:
            continue
    return parsed


def _delta_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(event["observed_exchange_receipt_delta_ms"]) for event in events]
    negatives = [
        event for event in events if float(event["observed_exchange_receipt_delta_ms"]) < 0
    ]
    return {
        "total_eligible_events": len(values),
        "negative_count": len(negatives),
        "negative_percentage": _ratio(len(negatives), len(values)),
        "minimum_ms": min(values) if values else None,
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "maximum_ms": max(values) if values else None,
        "iqr_ms": _iqr(values),
        "standard_deviation_ms": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "first_negative_occurrence": negatives[0] if negatives else None,
        "last_negative_occurrence": negatives[-1] if negatives else None,
    }


def _minute_windows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        timestamp = datetime.fromisoformat(str(event["local_receipt_ts"]).replace("Z", "+00:00"))
        window = timestamp.replace(second=0, microsecond=0).isoformat()
        buckets[window].append(event)
    return [{"window_start": key, **_delta_stats(value)} for key, value in sorted(buckets.items())]


def _delta_classification(values: list[float]) -> str:
    if len(values) < 10:
        return "insufficient evidence"
    negative_rate = _ratio(sum(value < 0 for value in values), len(values))
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    if negative_rate > 0.8 and stdev < 1000:
        return "stable offset"
    if stdev < 250:
        return "low-variance offset"
    if negative_rate < 0.05:
        return "sporadic outliers"
    if stdev > 1000:
        return "highly unstable"
    return "mixed distribution"


def _host_clock_info() -> dict[str, Any]:
    commands = [
        ["systemsetup", "-getusingnetworktime"],
        ["systemsetup", "-getnetworktimeserver"],
        ["sntp", "-sS", "time.apple.com"],
    ]
    observations = []
    for command in commands:
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            observations.append(
                {"command": " ".join(command), "available": False, "error": str(exc)}
            )
            continue
        observations.append(
            {
                "command": " ".join(command),
                "available": result.returncode == 0,
                "stdout": result.stdout.strip()[:500],
                "stderr": result.stderr.strip()[:500],
                "returncode": result.returncode,
                "observed_at": utc_now().isoformat(),
            }
        )
    return {"observations": observations}


def _policy_recommendations(
    paired_report: PairedQualityReport,
    investigation_report: dict[str, Any],
) -> dict[str, Any]:
    sessions = investigation_report["sessions"]
    recommendations = []
    cb_class = sessions["coinbase"]["coinbase_continuity"]["classification"]
    if cb_class == "confirmed missing-match evidence":
        recommendations.append(
            _recommendation(
                current_rule=(
                    "Any Coinbase match sequence discontinuity contributes to continuity warning."
                ),
                current_threshold_or_severity="WARNING",
                observed_evidence=(
                    "Heartbeat last_trade_id indicates match trade IDs were not observed."
                ),
                why_false_positive="Not a false positive; evidence supports quarantine review.",
                official_feed_justification=(
                    "Coinbase documents that matches-channel messages can be dropped and "
                    "heartbeat last_trade_id can identify missed trades."
                ),
                proposed_rule="Keep quarantine for confirmed missing-match evidence.",
                before=paired_report.coinbase_report.disposition.value,
                after="QUARANTINED",
                regression="heartbeat evidence of unseen trade IDs",
                confidence="medium",
            )
        )
    kraken_duplicates = sessions["kraken"]["kraken_duplicates"]
    if kraken_duplicates["groups_by_raw_hash"]:
        recommendations.append(
            _recommendation(
                current_rule="Exact raw-frame duplicate rate above threshold creates a warning.",
                current_threshold_or_severity="WARNING at > 0.01",
                observed_evidence=(
                    "Kraken duplicate groups are classified by message type in report."
                ),
                why_false_positive=(
                    "Repeated ticker/control frames may reflect unchanged state or feed behavior, "
                    "not necessarily duplicated market events."
                ),
                official_feed_justification=(
                    "Kraken ticker duplicate investigation performs no ticker sequence analysis."
                ),
                proposed_rule=(
                    "Keep exact trade duplicates as warning/error, but downgrade repeated "
                    "identical ticker state and heartbeat/status duplicates to informational "
                    "when normalized trade identities do not duplicate."
                ),
                before=paired_report.kraken_report.disposition.value,
                after="needs review after regression tests",
                regression=(
                    "Kraken duplicate heartbeat, repeated ticker state, exact duplicate trade"
                ),
                confidence="medium",
            )
        )
    for venue, session in sessions.items():
        stale_classes = session["quote_staleness"]["classifications"]
        if stale_classes:
            recommendations.append(
                _recommendation(
                    current_rule="Any stale quote interval creates a warning.",
                    current_threshold_or_severity="WARNING",
                    observed_evidence=f"{venue} stale classifications: {stale_classes}",
                    why_false_positive=(
                        "Healthy unchanged quote and quiet connection intervals should not be "
                        "treated the same as active trading without quote refresh."
                    ),
                    official_feed_justification=(
                        "Coinbase ticker batches cascading matches; Kraken ticker uses bbo trigger."
                    ),
                    proposed_rule=(
                        "Classify stale intervals first; quarantine active trading without quote "
                        "refresh or probable feed inactivity, not healthy unchanged quote "
                        "intervals."
                    ),
                    before=session.get("disposition", "QUARANTINED"),
                    after="needs review after regression tests",
                    regression=(
                        "healthy unchanged quote, connection inactivity, trades without quote "
                        "refresh"
                    ),
                    confidence="medium",
                )
            )
    return {
        "paired_collection_id": paired_report.paired_collection_id,
        "created_at": utc_now().isoformat(),
        "quality_code_git_commit": current_git_commit(),
        "recommendations": recommendations,
    }


def _summary_classifications(sessions: dict[str, Any]) -> dict[str, Any]:
    return {
        "coinbase_negative_delta": sessions["coinbase"]["negative_delta"]["classification"],
        "coinbase_continuity": sessions["coinbase"]["coinbase_continuity"]["classification"],
        "coinbase_staleness": sessions["coinbase"]["quote_staleness"]["classifications"],
        "kraken_negative_delta": sessions["kraken"]["negative_delta"]["classification"],
        "kraken_duplicates": (
            "classified duplicate groups present"
            if sessions["kraken"]["kraken_duplicates"]["groups_by_raw_hash"]
            else "no duplicate groups"
        ),
        "kraken_staleness": sessions["kraken"]["quote_staleness"]["classifications"],
    }


def _markdown_report(report: dict[str, Any], recommendations: dict[str, Any]) -> str:
    lines = [
        "# Quality Finding Investigation",
        "",
        f"Paired collection ID: `{report['paired_collection_id']}`",
        f"Policy version: `{report['quality_policy_version']}`",
        f"Git commit: `{report['quality_code_git_commit']}`",
        "",
        "## Summary",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    lines.append("## Recommendations")
    for rec in recommendations["recommendations"]:
        lines.append(f"- {rec['proposed_rule']} Confidence: `{rec['confidence']}`.")
    lines.append("")
    lines.append("Raw archives and original quality reports were not modified.")
    return "\n".join(lines) + "\n"


def _recommendation(
    *,
    current_rule: str,
    current_threshold_or_severity: str,
    observed_evidence: str,
    why_false_positive: str,
    official_feed_justification: str,
    proposed_rule: str,
    before: str,
    after: str,
    regression: str,
    confidence: str,
) -> dict[str, str]:
    return {
        "current_rule": current_rule,
        "current_threshold_or_severity": current_threshold_or_severity,
        "observed_evidence": observed_evidence,
        "why_current_behavior_may_be_false_positive": why_false_positive,
        "official_feed_justification": official_feed_justification,
        "proposed_rule": proposed_rule,
        "before_disposition": before,
        "expected_after_disposition": after,
        "regression_test_required": regression,
        "confidence": confidence,
    }


def _sequence_example(
    previous: _RawMessage | None, current: _RawMessage, classification: str
) -> dict[str, Any]:
    return {
        "classification": classification,
        "previous_record_index": previous.record_index if previous else None,
        "current_record_index": current.record_index,
        "previous_sequence": previous.payload.get("sequence") if previous else None,
        "current_sequence": current.payload.get("sequence"),
        "previous_message_type": previous.message_type if previous else None,
        "current_message_type": current.message_type,
        "current_receipt_ts": current.local_receipt_ts.isoformat(),
        "reconnect_proximity": False,
    }


def _kraken_message_classification(message: _RawMessage) -> str:
    if message.channel == "heartbeat":
        return "heartbeat"
    if message.channel == "status":
        return "status"
    if message.payload.get("method") == "subscribe":
        return "subscription acknowledgement"
    if message.channel == "trade":
        return "trade snapshot" if message.message_type == "snapshot" else "trade update"
    if message.channel == "ticker":
        return "ticker snapshot" if message.message_type == "snapshot" else "ticker update"
    if message.channel == "unsupported":
        return "unsupported"
    return "other"


def _kraken_duplicate_severity(message: _RawMessage) -> str:
    classification = _kraken_message_classification(message)
    if classification in {"heartbeat", "status", "repeated identical ticker state"}:
        return "informational"
    if classification == "subscription acknowledgement":
        return "informational or warning"
    if classification.startswith("trade"):
        return "warning"
    return "informational"


def _kraken_has_market_event(message: _RawMessage) -> bool:
    return message.channel in {"trade", "ticker"}


def _kraken_trade_duplicates(messages: list[_RawMessage]) -> dict[str, Any]:
    by_trade: dict[str, list[tuple[_RawMessage, dict[str, Any]]]] = defaultdict(list)
    previous_trade_id: int | None = None
    nonmonotonic = 0
    for message in messages:
        if message.channel != "trade":
            continue
        data = message.payload.get("data")
        if not isinstance(data, list):
            continue
        for record in data:
            if not isinstance(record, dict) or "trade_id" not in record:
                continue
            trade_id = str(record["trade_id"])
            by_trade[trade_id].append((message, record))
            if isinstance(record["trade_id"], int):
                if previous_trade_id is not None and record["trade_id"] < previous_trade_id:
                    nonmonotonic += 1
                previous_trade_id = record["trade_id"]
    duplicate_trade_ids = {}
    for trade_id, entries in by_trade.items():
        if len(entries) <= 1:
            continue
        contents = {json.dumps(entry[1], sort_keys=True) for entry in entries}
        hashes = {entry[0].frame_hash for entry in entries}
        duplicate_trade_ids[trade_id] = {
            "count": len(entries),
            "same_trade_id_with_identical_contents": len(contents) == 1,
            "same_trade_id_with_conflicting_contents": len(contents) > 1,
            "same_raw_frame_repeated": len(hashes) < len(entries),
            "different_frames_containing_same_trade": len(hashes) > 1,
            "record_indices": [entry[0].record_index for entry in entries[:MAX_EXAMPLES]],
        }
    return {
        "duplicate_trade_ids": duplicate_trade_ids,
        "nonmonotonic_trade_id": nonmonotonic,
    }


def _kraken_ticker_duplicates(quote_events: list[_QuoteEvent]) -> dict[str, Any]:
    identical_states = 0
    same_prices_diff_qty = 0
    for before, after in pairwise(quote_events):
        if before.state == after.state:
            identical_states += 1
        elif before.prices == after.prices:
            same_prices_diff_qty += 1
    return {
        "identical_normalized_bbo_state": identical_states,
        "same_bbo_prices_with_different_quantities": same_prices_diff_qty,
        "same_bbo_state_after_unrelated_control_messages": "not evaluated",
        "ticker_sequence_analysis_performed": False,
    }


def _stale_classification(
    before: _QuoteEvent,
    after: _QuoteEvent,
    interval_messages: list[_RawMessage],
    trades: list[_RawMessage],
    heartbeats: list[_RawMessage],
) -> str:
    if before.state == after.state:
        return "healthy unchanged quote"
    if not interval_messages:
        return "probable feed inactivity"
    if heartbeats and not trades:
        return "connection quiet but heartbeat healthy"
    if trades:
        return "active trading without quote refresh"
    return "insufficient evidence"


def _is_trade_message(message: _RawMessage) -> bool:
    return message.message_type in {"match", "last_match"} or message.channel == "trade"


def _is_control_message(message: _RawMessage) -> bool:
    return message.channel in {"heartbeat", "status", "subscriptions", "subscribe"}


def _nearby_message_types(messages: list[_RawMessage], record_index: int) -> list[str]:
    return [
        message.message_type
        for message in messages
        if abs(message.record_index - record_index) <= 3
    ]


def _consecutive_duplicate_count(messages: list[_RawMessage]) -> int:
    return sum(1 for before, after in pairwise(messages) if before.frame_hash == after.frame_hash)


def _maximum_duplicate_run(messages: list[_RawMessage]) -> int:
    maximum = 0
    current = 0
    previous_hash: str | None = None
    for message in messages:
        if message.frame_hash == previous_hash:
            current += 1
        else:
            current = 1
        maximum = max(maximum, current)
        previous_hash = message.frame_hash
    return maximum


def _duplicate_count(values: list[int]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _nonmonotonic_count(values: list[int]) -> int:
    return sum(1 for before, after in pairwise(values) if after < before)


def _jump_count(values: list[int]) -> int:
    return sum(1 for before, after in pairwise(values) if after > before + 1)


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil((len(ordered) - 1) * quantile)))
    return ordered[index]


def _iqr(values: list[float]) -> float | None:
    p75 = _percentile(values, 0.75)
    p25 = _percentile(values, 0.25)
    if p75 is None or p25 is None:
        return None
    return p75 - p25


def _bounded(items: list[Any]) -> list[Any]:
    return items[:MAX_EXAMPLES]
