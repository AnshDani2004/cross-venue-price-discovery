import pytest

from cross_venue.collectors.retry import RetryPolicy


def test_retry_policy_exponential_delay_is_bounded() -> None:
    policy = RetryPolicy(initial_delay_seconds=1, multiplier=2, max_delay_seconds=3)

    assert policy.delay_for_attempt(1) == 1
    assert policy.delay_for_attempt(2) == 2
    assert policy.delay_for_attempt(3) == 3
    assert policy.delay_for_attempt(4) == 3


def test_retry_policy_applies_bounded_jitter() -> None:
    policy = RetryPolicy(initial_delay_seconds=10, jitter_fraction=0.5)

    assert policy.delay_for_attempt(1, jitter_source=lambda: 1.0) == 15


def test_retry_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="initial delay"):
        RetryPolicy(initial_delay_seconds=0)
    with pytest.raises(ValueError, match="maximum attempts"):
        RetryPolicy(max_attempts=-1)
    with pytest.raises(ValueError, match="jitter"):
        RetryPolicy(jitter_fraction=2)
