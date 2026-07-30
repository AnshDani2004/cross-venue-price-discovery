import pytest

from cross_venue.collectors.supervision import HeartbeatSupervisor, InactivityTimeoutError


def test_supervisor_tracks_frame_control_and_market_liveness() -> None:
    supervisor = HeartbeatSupervisor(inactivity_timeout_seconds=5, last_frame_monotonic=10)

    supervisor.record_frame(11)
    supervisor.record_control(12)
    supervisor.record_market_event(13)
    supervisor.check(15)

    assert supervisor.last_frame_monotonic == 11
    assert supervisor.last_control_monotonic == 12
    assert supervisor.last_market_event_monotonic == 13


def test_supervisor_uses_monotonic_inactivity_timeout() -> None:
    supervisor = HeartbeatSupervisor(inactivity_timeout_seconds=5, last_frame_monotonic=10)

    with pytest.raises(InactivityTimeoutError, match="inactivity"):
        supervisor.check(16)


def test_supervisor_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        HeartbeatSupervisor(inactivity_timeout_seconds=0, last_frame_monotonic=0)
