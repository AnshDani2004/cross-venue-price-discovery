"""Append-only hash-chained campaign ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from cross_venue.campaigns.exceptions import CampaignValidationError
from cross_venue.campaigns.models import (
    AttemptSummary,
    CampaignConfig,
    CampaignRegistry,
    LedgerEvent,
    LedgerEventType,
    MissedReason,
    SlotStatus,
)
from cross_venue.quality.io import sha256_text
from cross_venue.storage.checksum import sha256_file

GENESIS_PREVIOUS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    """Return canonical JSON for hashing."""

    def default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        return str(item)

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)


def event_hash_payload(event: LedgerEvent) -> dict[str, Any]:
    """Return the event fields that participate in the event hash."""

    data = event.model_dump(mode="json")
    data.pop("event_hash", None)
    return data


def compute_event_hash(event: LedgerEvent) -> str:
    """Compute the canonical event hash."""

    return sha256_text(canonical_json(event_hash_payload(event)))


def make_event(
    *,
    path: Path,
    campaign_id: str,
    event_type: LedgerEventType,
    payload: dict[str, Any],
    slot_id: str | None = None,
    campaign_attempt_id: str | None = None,
    occurred_at: datetime | None = None,
) -> LedgerEvent:
    """Create the next ledger event for a path."""

    events = read_ledger(path) if path.exists() else []
    previous_hash = events[-1].event_hash if events else GENESIS_PREVIOUS_HASH
    event = LedgerEvent(
        event_index=len(events),
        campaign_id=campaign_id,
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        slot_id=slot_id,
        campaign_attempt_id=campaign_attempt_id,
        payload=_bounded_payload(payload),
        previous_event_hash=previous_hash,
        event_hash="",
    )
    return event.model_copy(update={"event_hash": compute_event_hash(event)})


def append_event(path: Path, event: LedgerEvent) -> None:
    """Append an event after validating the existing chain head."""

    path.parent.mkdir(parents=True, exist_ok=True)
    events = read_ledger(path) if path.exists() else []
    expected_previous = events[-1].event_hash if events else GENESIS_PREVIOUS_HASH
    if event.event_index != len(events) or event.previous_event_hash != expected_previous:
        raise CampaignValidationError("ledger append does not match current chain head")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(event.model_dump(mode="json")) + "\n")


def read_ledger(path: Path) -> list[LedgerEvent]:
    """Read all ledger events."""

    if not path.exists():
        return []
    events = [
        LedgerEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    validate_ledger_events(events)
    return events


def validate_ledger_events(events: list[LedgerEvent]) -> None:
    """Validate event indexes and hash chain."""

    previous = GENESIS_PREVIOUS_HASH
    for index, event in enumerate(events):
        if event.event_index != index:
            raise CampaignValidationError("ledger event index mismatch")
        if event.previous_event_hash != previous:
            raise CampaignValidationError("ledger previous hash mismatch")
        if compute_event_hash(event) != event.event_hash:
            raise CampaignValidationError("ledger event hash mismatch")
        previous = event.event_hash


def ledger_sha256(path: Path) -> str:
    """Return the current ledger file hash."""

    return sha256_file(path) if path.exists() else sha256_text("")


def rebuild_registry_from_ledger(
    config: CampaignConfig, events: list[LedgerEvent]
) -> CampaignRegistry:
    """Rebuild the current registry from append-only ledger events."""

    if not events or events[0].event_type != LedgerEventType.CAMPAIGN_INITIALIZED:
        raise CampaignValidationError("campaign ledger missing initialization event")
    registry = CampaignRegistry.model_validate(events[0].payload["registry"])
    planned_slots = dict(registry.planned_slots)
    attempts = dict(registry.attempts)
    for event in events[1:]:
        if event.event_type == LedgerEventType.SLOT_MARKED_MISSED:
            slot_id = _require_slot(event)
            state = planned_slots[slot_id]
            planned_slots[slot_id] = state.model_copy(
                update={
                    "status": SlotStatus.MISSED,
                    "missed_reason": MissedReason(event.payload["reason"]),
                }
            )
        elif event.event_type == LedgerEventType.ATTEMPT_STARTED:
            attempt = AttemptSummary.model_validate(event.payload["attempt"])
            attempts[attempt.campaign_attempt_id] = attempt
            state = planned_slots[attempt.slot_id]
            planned_slots[attempt.slot_id] = state.model_copy(
                update={
                    "status": SlotStatus.RUNNING,
                    "attempts": (*state.attempts, attempt.campaign_attempt_id),
                }
            )
        elif event.event_type in {
            LedgerEventType.ATTEMPT_ACCEPTED,
            LedgerEventType.ATTEMPT_QUARANTINED,
            LedgerEventType.ATTEMPT_REJECTED,
            LedgerEventType.ATTEMPT_FAILED,
            LedgerEventType.ATTEMPT_ABORTED,
        }:
            attempt = AttemptSummary.model_validate(event.payload["attempt"])
            attempts[attempt.campaign_attempt_id] = attempt
            state = planned_slots[attempt.slot_id]
            planned_slots[attempt.slot_id] = state.model_copy(
                update={"status": SlotStatus(attempt.attempt_status.value)}
            )
        elif event.event_type in {
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS,
        }:
            registry = registry.model_copy(
                update={
                    "runtime_git_commit": event.payload["new_runtime_commit"],
                    "runtime_working_tree_clean": event.payload["runtime_working_tree_clean"],
                }
            )
    return registry.model_copy(
        update={
            "planned_slots": planned_slots,
            "attempts": attempts,
            "ledger_sha256": ledger_sha256(config.registry_root / "__placeholder__"),
        }
    )


def _require_slot(event: LedgerEvent) -> str:
    if event.slot_id is None:
        raise CampaignValidationError("ledger event missing slot ID")
    return event.slot_id


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = canonical_json(payload)
    if len(encoded) > 250_000:
        raise CampaignValidationError("ledger payload is too large")
    if "raw_payload" in encoded or "frame_bytes" in encoded:
        raise CampaignValidationError("ledger payload must not include raw WebSocket payloads")
    return payload
