"""Deterministic collector lifecycle state machine."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from cross_venue.collectors.exceptions import InvalidCollectorStateTransition


class CollectorState(StrEnum):
    """Lifecycle states for future public market-data collectors."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[CollectorState, frozenset[CollectorState]] = {
    CollectorState.CREATED: frozenset({CollectorState.STARTING, CollectorState.STOPPED}),
    CollectorState.STARTING: frozenset({CollectorState.RUNNING, CollectorState.FAILED}),
    CollectorState.RUNNING: frozenset({CollectorState.STOPPING, CollectorState.FAILED}),
    CollectorState.STOPPING: frozenset({CollectorState.STOPPED, CollectorState.FAILED}),
    CollectorState.FAILED: frozenset({CollectorState.STOPPED}),
    CollectorState.STOPPED: frozenset({CollectorState.STOPPED}),
}


class CollectorLifecycle(BaseModel):
    """Immutable lifecycle state with explicit allowed transitions.

    ``CREATED -> STOPPED`` is allowed for cancellation before startup. ``STOPPED ->
    STOPPED`` is allowed so repeated stop calls are idempotent after shutdown.
    Reconnection states are intentionally omitted from Phase 2A.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CollectorState = CollectorState.CREATED

    def transition_to(self, new_state: CollectorState) -> CollectorLifecycle:
        """Return a new lifecycle instance after a valid transition."""

        if new_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidCollectorStateTransition(
                f"cannot transition collector from {self.state} to {new_state}"
            )
        return self.model_copy(update={"state": new_state})


def allowed_transitions(state: CollectorState) -> frozenset[CollectorState]:
    """Return allowed next states for documentation and tests."""

    return _ALLOWED_TRANSITIONS[state]
