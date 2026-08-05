"""Campaign registry initialization and updates."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cross_venue.campaigns.completion import recalculate_registry
from cross_venue.campaigns.exceptions import CampaignRegistryError, CampaignValidationError
from cross_venue.campaigns.ledger import (
    append_event,
    ledger_sha256,
    make_event,
    read_ledger,
    rebuild_registry_from_ledger,
)
from cross_venue.campaigns.models import (
    CAMPAIGN_SCHEMA_VERSION,
    AttemptSummary,
    CampaignConfig,
    CampaignRegistry,
    CampaignStatus,
    CompletionRequirements,
    CompletionState,
    LedgerEventType,
    MissedReason,
    PlannedSlotState,
    SlotStatus,
)
from cross_venue.campaigns.paths import ledger_path, registry_path, reports_root
from cross_venue.quality.io import current_git_commit, utc_now
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json


def working_tree_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == ""


def initialize_campaign(config: CampaignConfig, *, config_path: Path) -> CampaignRegistry:
    """Create a new campaign registry and genesis ledger event."""

    if config.require_clean_working_tree and not working_tree_clean():
        raise CampaignRegistryError("campaign initialization requires a clean working tree")
    rpath = registry_path(config)
    lpath = ledger_path(config)
    config_sha = sha256_file(config_path)
    quality_sha = sha256_file(Path("configs/data_quality.toml"))
    if rpath.exists() or lpath.exists():
        existing = load_registry(config)
        if (
            existing.campaign_id == config.campaign_id
            and existing.campaign_config_sha256 == config_sha
            and existing.quality_policy_sha256 == quality_sha
        ):
            return existing
        raise CampaignRegistryError("existing campaign state has different identity or hashes")
    now = utc_now()
    planned_slots = {
        slot.slot_id: PlannedSlotState(slot=slot, status=SlotStatus.PLANNED)
        for slot in config.slots
    }
    registry = CampaignRegistry(
        campaign_schema_version=CAMPAIGN_SCHEMA_VERSION,
        campaign_id=config.campaign_id,
        campaign_status=CampaignStatus.IN_PROGRESS,
        campaign_config_path=config_path.as_posix(),
        campaign_config_sha256=config_sha,
        quality_policy_version=config.quality_policy_version,
        quality_policy_sha256=quality_sha,
        runtime_git_commit=current_git_commit(),
        runtime_working_tree_clean=working_tree_clean(),
        created_at=now,
        updated_at=now,
        instrument=config.instrument,
        venues=config.venues,
        timezone=config.timezone,
        requested_duration_seconds=config.requested_duration_seconds,
        minimum_overlap_seconds_per_accepted_session=(
            config.minimum_overlap_seconds_per_accepted_session
        ),
        minimum_accepted_sessions=config.minimum_accepted_sessions,
        minimum_total_accepted_overlap_seconds=config.minimum_total_accepted_overlap_seconds,
        minimum_calendar_dates=config.minimum_calendar_dates,
        minimum_time_buckets=config.minimum_time_buckets,
        maximum_attempts=config.maximum_attempts,
        planned_slots=planned_slots,
        attempts={},
        completion_requirements=CompletionRequirements(
            accepted_sessions=False,
            accepted_overlap_seconds=False,
            calendar_dates=False,
            time_buckets=False,
            policy_consistency=True,
            runtime_consistency=True,
            attempts_registered=False,
            registry_and_ledger_valid=True,
        ),
        completion_status=CompletionState.UNSATISFIED,
        ledger_sha256="",
    )
    event = make_event(
        path=lpath,
        campaign_id=config.campaign_id,
        event_type=LedgerEventType.CAMPAIGN_INITIALIZED,
        payload={"registry": registry.model_dump(mode="json")},
    )
    append_event(lpath, event)
    registry = registry.model_copy(
        update={"ledger_sha256": ledger_sha256(lpath), "updated_at": utc_now()}
    )
    write_registry(config, registry)
    return registry


def load_registry(config: CampaignConfig) -> CampaignRegistry:
    """Load the derived campaign registry."""

    path = registry_path(config)
    if not path.exists():
        raise CampaignRegistryError(f"campaign registry does not exist: {path}")
    return CampaignRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def write_registry(config: CampaignConfig, registry: CampaignRegistry) -> None:
    """Atomically persist a derived registry."""

    path = registry_path(config)
    atomic_write_json(path, registry.model_dump(mode="json"))


def validate_registry_and_ledger(config: CampaignConfig) -> CampaignRegistry:
    """Validate ledger chain and registry reconstruction."""

    events = read_ledger(ledger_path(config))
    rebuilt = rebuild_registry_from_ledger(config, events).model_copy(
        update={"ledger_sha256": ledger_sha256(ledger_path(config))}
    )
    rebuilt = recalculate_registry(rebuilt).model_copy(
        update={"updated_at": load_registry(config).updated_at}
    )
    current = load_registry(config)
    comparable_rebuilt = _registry_comparable(rebuilt)
    comparable_current = _registry_comparable(current)
    if comparable_rebuilt != comparable_current:
        raise CampaignValidationError("registry does not match ledger reconstruction")
    return current


def mark_slot_missed(
    config: CampaignConfig,
    *,
    slot_id: str,
    reason: MissedReason,
) -> CampaignRegistry:
    """Mark one slot missed with an enumerated reason."""

    registry = validate_registry_and_ledger(config)
    state = registry.planned_slots[slot_id]
    if state.status not in {SlotStatus.PLANNED, SlotStatus.DUE}:
        raise CampaignRegistryError(f"slot {slot_id} cannot be marked missed from {state.status}")
    event = make_event(
        path=ledger_path(config),
        campaign_id=config.campaign_id,
        event_type=LedgerEventType.SLOT_MARKED_MISSED,
        slot_id=slot_id,
        payload={"reason": reason.value},
    )
    append_event(ledger_path(config), event)
    updated_slots = dict(registry.planned_slots)
    updated_slots[slot_id] = state.model_copy(
        update={"status": SlotStatus.MISSED, "missed_reason": reason}
    )
    updated = registry.model_copy(
        update={
            "planned_slots": updated_slots,
            "updated_at": utc_now(),
            "ledger_sha256": ledger_sha256(ledger_path(config)),
        }
    )
    updated = recalculate_registry(updated)
    write_registry(config, updated)
    write_status_reports(config, updated)
    return updated


def record_attempt_event(
    config: CampaignConfig,
    *,
    event_type: LedgerEventType,
    attempt: AttemptSummary,
) -> CampaignRegistry:
    """Append an attempt event and update the derived registry."""

    registry = validate_registry_and_ledger(config)
    event = make_event(
        path=ledger_path(config),
        campaign_id=config.campaign_id,
        event_type=event_type,
        slot_id=attempt.slot_id,
        campaign_attempt_id=attempt.campaign_attempt_id,
        payload={"attempt": attempt.model_dump(mode="json")},
    )
    append_event(ledger_path(config), event)
    updated_attempts = dict(registry.attempts)
    updated_attempts[attempt.campaign_attempt_id] = attempt
    updated_slots = dict(registry.planned_slots)
    state = updated_slots[attempt.slot_id]
    status = SlotStatus.RUNNING
    if attempt.attempt_status.value in SlotStatus:
        status = SlotStatus(attempt.attempt_status.value)
    updated_slots[attempt.slot_id] = state.model_copy(
        update={
            "status": status,
            "attempts": tuple(dict.fromkeys((*state.attempts, attempt.campaign_attempt_id))),
        }
    )
    updated = registry.model_copy(
        update={
            "planned_slots": updated_slots,
            "attempts": updated_attempts,
            "updated_at": utc_now(),
            "ledger_sha256": ledger_sha256(ledger_path(config)),
        }
    )
    updated = recalculate_registry(updated)
    write_registry(config, updated)
    write_status_reports(config, updated)
    return updated


def next_attempt_number(registry: CampaignRegistry, slot_id: str) -> int:
    """Return the next attempt number for a slot."""

    return len(registry.planned_slots[slot_id].attempts) + 1


def write_status_reports(config: CampaignConfig, registry: CampaignRegistry) -> None:
    """Write machine and human-readable status reports."""

    root = reports_root(config)
    root.mkdir(parents=True, exist_ok=True)
    status = campaign_status_payload(config, registry)
    atomic_write_json(root / "campaign_status.json", status)
    (root / "campaign_status.md").write_text(status_markdown(status), encoding="utf-8")


def campaign_status_payload(config: CampaignConfig, registry: CampaignRegistry) -> dict[str, Any]:
    """Return the current campaign status payload."""

    now = datetime.now(UTC)
    completed = {
        slot_id
        for slot_id, state in registry.planned_slots.items()
        if state.status
        in {
            SlotStatus.ACCEPTED,
            SlotStatus.QUARANTINED,
            SlotStatus.REJECTED,
            SlotStatus.FAILED,
            SlotStatus.ABORTED,
            SlotStatus.MISSED,
            SlotStatus.NOT_NEEDED,
        }
    }
    next_slot = next(
        (
            state.slot
            for slot_id, state in registry.planned_slots.items()
            if slot_id not in completed
        ),
        None,
    )
    next_command = None
    if next_slot is not None:
        next_command = (
            "python -m cross_venue run-campaign-slot "
            f"--campaign-id {config.campaign_id} --slot-id {next_slot.slot_id}"
        )
    return {
        "campaign_id": registry.campaign_id,
        "campaign_status": registry.campaign_status.value,
        "runtime_git_commit": registry.runtime_git_commit,
        "current_utc_time": now.isoformat(),
        "next_scheduled_slot": next_slot.model_dump(mode="json") if next_slot else None,
        "accepted_sessions": registry.accepted_attempt_count,
        "accepted_overlap_seconds": registry.accepted_overlap_seconds,
        "accepted_calendar_dates": list(registry.accepted_calendar_dates),
        "accepted_time_buckets": [bucket.value for bucket in registry.accepted_time_buckets],
        "attempt_counts": {
            "accepted": registry.accepted_attempt_count,
            "quarantined": registry.quarantined_attempt_count,
            "rejected": registry.rejected_attempt_count,
            "failed": registry.failed_attempt_count,
            "missed": registry.missed_slot_count,
        },
        "completion_requirements": registry.completion_requirements.model_dump(mode="json"),
        "completion_status": registry.completion_status.value,
        "reserve_slots_remaining": sum(
            state.slot.slot_type.value == "RESERVE" and state.status == SlotStatus.PLANNED
            for state in registry.planned_slots.values()
        ),
        "next_command": next_command,
    }


def status_markdown(status: dict[str, Any]) -> str:
    """Render campaign status as Markdown."""

    lines = [
        f"# Campaign Status: {status['campaign_id']}",
        "",
        f"- Status: {status['campaign_status']}",
        f"- Runtime commit: `{status['runtime_git_commit']}`",
        f"- Current UTC time: `{status['current_utc_time']}`",
        f"- Accepted sessions: {status['accepted_sessions']}",
        f"- Accepted overlap seconds: {status['accepted_overlap_seconds']}",
        f"- Completion: {status['completion_status']}",
    ]
    if status["next_scheduled_slot"] is not None:
        lines.append(f"- Next slot: `{status['next_scheduled_slot']['slot_id']}`")
    if status["next_command"] is not None:
        lines.extend(["", "```bash", status["next_command"], "```"])
    return "\n".join(lines) + "\n"


def registry_sha256(config: CampaignConfig) -> str:
    """Return current registry file hash."""

    return sha256_file(registry_path(config))


def _registry_comparable(registry: CampaignRegistry) -> str:
    payload = json.loads(registry.model_dump_json())
    payload.pop("updated_at", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
