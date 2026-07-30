import pytest

from cross_venue.collectors import (
    CollectorLifecycle,
    CollectorState,
    InvalidCollectorStateTransition,
)
from cross_venue.collectors.lifecycle import allowed_transitions


def test_all_documented_lifecycle_transitions_are_valid() -> None:
    for start_state in CollectorState:
        lifecycle = CollectorLifecycle(state=start_state)
        for end_state in allowed_transitions(start_state):
            assert lifecycle.transition_to(end_state).state == end_state


@pytest.mark.parametrize(
    ("start_state", "end_state"),
    [
        (CollectorState.CREATED, CollectorState.RUNNING),
        (CollectorState.RUNNING, CollectorState.STARTING),
        (CollectorState.STOPPED, CollectorState.RUNNING),
        (CollectorState.FAILED, CollectorState.RUNNING),
    ],
)
def test_invalid_lifecycle_transitions_raise(
    start_state: CollectorState,
    end_state: CollectorState,
) -> None:
    with pytest.raises(InvalidCollectorStateTransition, match="cannot transition"):
        CollectorLifecycle(state=start_state).transition_to(end_state)


def test_failed_collector_can_transition_to_stopped() -> None:
    lifecycle = CollectorLifecycle(state=CollectorState.FAILED)

    assert lifecycle.transition_to(CollectorState.STOPPED).state is CollectorState.STOPPED


def test_stop_before_startup_is_allowed_for_cancellation() -> None:
    lifecycle = CollectorLifecycle()

    assert lifecycle.transition_to(CollectorState.STOPPED).state is CollectorState.STOPPED


def test_repeated_stop_is_idempotent_after_stopped() -> None:
    lifecycle = CollectorLifecycle(state=CollectorState.STOPPED)

    assert lifecycle.transition_to(CollectorState.STOPPED).state is CollectorState.STOPPED
