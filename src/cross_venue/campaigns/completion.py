"""Campaign completion evaluation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from cross_venue.campaigns.models import (
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    CampaignRegistry,
    CampaignStatus,
    CompletionRequirements,
    CompletionState,
    InclusionStatus,
    PlannedSlotState,
    SlotStatus,
)


def evaluate_completion(
    config: CampaignConfig,
    planned_slots: dict[str, PlannedSlotState],
    attempts: Mapping[str, AttemptSummary],
    *,
    runtime_commit: str,
    registry_and_ledger_valid: bool,
) -> tuple[CompletionRequirements, CompletionState, dict[str, object]]:
    """Evaluate Phase 3B completion requirements."""

    accepted = [
        attempt
        for attempt in attempts.values()
        if attempt.attempt_status == AttemptStatus.ACCEPTED
        and attempt.inclusion_status == InclusionStatus.INCLUDED
    ]
    accepted_overlap = sum(float(attempt.paired_overlap_seconds) for attempt in accepted)
    dates = tuple(
        sorted(
            {
                attempt.planned_start_local.split(" ")[0]
                for attempt in accepted
                if attempt.planned_start_local
            }
        )
    )
    buckets = tuple(sorted({attempt.time_bucket for attempt in accepted}))
    policy_consistency = all(
        attempt.attempt_status == AttemptStatus.ACCEPTED for attempt in accepted
    )
    runtime_consistency = bool(runtime_commit)
    attempted_slots = {
        slot_id
        for slot_id, state in planned_slots.items()
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
    requirements = CompletionRequirements(
        accepted_sessions=len(accepted) >= config.minimum_accepted_sessions,
        accepted_overlap_seconds=accepted_overlap >= config.minimum_total_accepted_overlap_seconds,
        calendar_dates=len(dates) >= config.minimum_calendar_dates,
        time_buckets=len(buckets) >= config.minimum_time_buckets,
        policy_consistency=policy_consistency,
        runtime_consistency=runtime_consistency,
        attempts_registered=all(
            slot.slot_type.value == "RESERVE" or slot_id in attempted_slots
            for slot_id, slot in ((slot_id, state.slot) for slot_id, state in planned_slots.items())
        ),
        registry_and_ledger_valid=registry_and_ledger_valid,
    )
    status = CompletionState.SATISFIED if requirements.satisfied else CompletionState.UNSATISFIED
    evidence: dict[str, object] = {
        "accepted_attempt_count": len(accepted),
        "accepted_overlap_seconds": accepted_overlap,
        "accepted_calendar_dates": dates,
        "accepted_time_buckets": [bucket.value for bucket in buckets],
    }
    return requirements, status, evidence


def recalculate_registry(registry: CampaignRegistry) -> CampaignRegistry:
    """Recalculate derived counters and completion status."""

    attempts = registry.attempts
    status_counts = Counter(attempt.attempt_status for attempt in attempts.values())
    accepted = [
        attempt
        for attempt in attempts.values()
        if attempt.attempt_status == AttemptStatus.ACCEPTED
        and attempt.inclusion_status == InclusionStatus.INCLUDED
    ]
    dates = tuple(sorted({attempt.planned_start_local.split(" ")[0] for attempt in accepted}))
    buckets = tuple(sorted({attempt.time_bucket for attempt in accepted}))
    terminal_statuses = {
        SlotStatus.ACCEPTED,
        SlotStatus.QUARANTINED,
        SlotStatus.REJECTED,
        SlotStatus.FAILED,
        SlotStatus.ABORTED,
        SlotStatus.MISSED,
        SlotStatus.NOT_NEEDED,
    }
    requirements = CompletionRequirements(
        accepted_sessions=len(accepted) >= registry.minimum_accepted_sessions,
        accepted_overlap_seconds=sum(attempt.paired_overlap_seconds for attempt in accepted)
        >= registry.minimum_total_accepted_overlap_seconds,
        calendar_dates=len(dates) >= registry.minimum_calendar_dates,
        time_buckets=len(buckets) >= registry.minimum_time_buckets,
        policy_consistency=True,
        runtime_consistency=bool(registry.runtime_git_commit),
        attempts_registered=all(
            state.slot.slot_type.value == "RESERVE" or state.status in terminal_statuses
            for state in registry.planned_slots.values()
        ),
        registry_and_ledger_valid=True,
    )
    completion_state = (
        CompletionState.SATISFIED if requirements.satisfied else CompletionState.UNSATISFIED
    )
    campaign_status = (
        CampaignStatus.COMPLETE
        if completion_state == CompletionState.SATISFIED
        else CampaignStatus.IN_PROGRESS
    )
    return registry.model_copy(
        update={
            "campaign_status": campaign_status,
            "accepted_attempt_count": status_counts[AttemptStatus.ACCEPTED],
            "quarantined_attempt_count": status_counts[AttemptStatus.QUARANTINED],
            "rejected_attempt_count": status_counts[AttemptStatus.REJECTED],
            "failed_attempt_count": status_counts[AttemptStatus.FAILED],
            "missed_slot_count": sum(
                state.status == SlotStatus.MISSED for state in registry.planned_slots.values()
            ),
            "accepted_overlap_seconds": sum(attempt.paired_overlap_seconds for attempt in accepted),
            "accepted_calendar_dates": dates,
            "accepted_time_buckets": buckets,
            "completion_requirements": requirements,
            "completion_status": completion_state,
        }
    )
