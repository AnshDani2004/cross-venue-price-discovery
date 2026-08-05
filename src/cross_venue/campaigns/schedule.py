"""Fixed schedule evaluation for campaign slots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cross_venue.campaigns.exceptions import CampaignSlotNotDueError
from cross_venue.campaigns.models import CampaignConfig, CampaignSlot, SlotStatus


@dataclass(frozen=True, slots=True)
class SlotWindow:
    """Evaluated execution window for one slot."""

    slot: CampaignSlot
    earliest_start: datetime
    latest_start: datetime
    now: datetime

    @property
    def executable(self) -> bool:
        return self.earliest_start <= self.now <= self.latest_start

    @property
    def passed(self) -> bool:
        return self.now > self.latest_start

    @property
    def due_status(self) -> SlotStatus:
        if self.executable:
            return SlotStatus.DUE
        if self.passed:
            return SlotStatus.MISSED
        return SlotStatus.PLANNED


def evaluate_slot_window(
    config: CampaignConfig,
    slot: CampaignSlot,
    *,
    now: datetime | None = None,
) -> SlotWindow:
    """Evaluate whether a slot is currently executable."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    return SlotWindow(
        slot=slot,
        earliest_start=slot.planned_start_utc
        - timedelta(seconds=config.early_start_tolerance_seconds),
        latest_start=slot.planned_start_utc
        + timedelta(seconds=config.late_start_tolerance_seconds),
        now=current,
    )


def require_slot_executable(
    config: CampaignConfig,
    slot: CampaignSlot,
    *,
    now: datetime | None = None,
) -> SlotWindow:
    """Raise if a slot cannot be started now."""

    window = evaluate_slot_window(config, slot, now=now)
    if not window.executable:
        raise CampaignSlotNotDueError(
            f"slot {slot.slot_id} is outside execution window "
            f"{window.earliest_start.isoformat()} to {window.latest_start.isoformat()}"
        )
    return window


def next_actionable_slot(
    config: CampaignConfig, completed_slot_ids: set[str]
) -> CampaignSlot | None:
    """Return the next incomplete slot in deterministic schedule order."""

    for slot in config.slots:
        if slot.slot_id not in completed_slot_ids:
            return slot
    return None
