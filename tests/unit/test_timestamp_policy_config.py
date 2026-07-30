from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cross_venue.config import TimestampPolicyConfig, load_timestamp_policy_config


def valid_timestamp_policy_data() -> dict[str, Any]:
    return {
        "timezone": "UTC",
        "timezone_aware_required": True,
        "preserve_exchange_timestamp": True,
        "simulated_information_ordering": "receipt_time",
        "venue_reconstruction_ordering": "exchange_sequence_then_exchange_timestamp",
        "equal_timestamp_tie_breaker": [
            "local_receipt_ts",
            "venue",
            "sequence_number",
            "message_type",
        ],
        "clock_offset_jitter_audit_required": True,
        "naive_datetime_policy": "reject",
        "timestamp_precision": "microsecond",
    }


def test_timestamp_policy_config_loads_required_ordering_policy() -> None:
    config = load_timestamp_policy_config(Path("configs/timestamp_policy.toml"))

    assert config.timezone == "UTC"
    assert config.equal_timestamp_tie_breaker == (
        "local_receipt_ts",
        "venue",
        "sequence_number",
        "message_type",
    )


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_error"),
    [
        ("timezone", "Mars/Base", "unknown timezone"),
        ("timezone_aware_required", False, "timezone-aware timestamps are required"),
        ("preserve_exchange_timestamp", False, "exchange timestamps must be preserved"),
        ("simulated_information_ordering", "exchange_timestamp", "Input should be"),
        ("clock_offset_jitter_audit_required", False, "clock-offset jitter audits"),
        ("naive_datetime_policy", "coerce", "Input should be"),
        ("timestamp_precision", "nanosecond", "Input should be"),
    ],
)
def test_timestamp_policy_config_rejects_invalid_policy(
    field_name: str,
    bad_value: object,
    expected_error: str,
) -> None:
    data = valid_timestamp_policy_data()
    data[field_name] = bad_value

    with pytest.raises(ValidationError, match=expected_error):
        TimestampPolicyConfig.model_validate(data)


def test_timestamp_policy_config_rejects_nondeterministic_equal_timestamp_policy() -> None:
    data = valid_timestamp_policy_data()
    data["equal_timestamp_tie_breaker"] = ["venue", "local_receipt_ts"]

    with pytest.raises(ValidationError, match="deterministic"):
        TimestampPolicyConfig.model_validate(data)


def test_timestamp_policy_config_rejects_old_receipt_name() -> None:
    data = valid_timestamp_policy_data()
    old_name = "receipt" + "_timestamp"
    data["equal_timestamp_tie_breaker"] = [
        old_name,
        "venue",
        "sequence_number",
        "message_type",
    ]

    with pytest.raises(ValidationError, match="Input should be"):
        TimestampPolicyConfig.model_validate(data)


def test_timestamp_policy_config_rejects_unknown_extra_field() -> None:
    data = valid_timestamp_policy_data()
    data["private_clock_note"] = "local only"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TimestampPolicyConfig.model_validate(data)
