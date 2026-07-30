from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cross_venue.config import ResearchConfig, load_research_config
from cross_venue.schemas import Exchange


def valid_research_data() -> dict[str, Any]:
    return {
        "canonical_instrument": "BTC-USD",
        "initiating_venues": ["coinbase", "kraken"],
        "response_horizons_ms": [100, 250, 500],
        "event_threshold_ticks": 1,
        "target_type": "direction",
        "sampling_method": "event_time_with_receipt_time_ordering",
        "primary_baseline": "no_change_and_unconditional_response",
        "data_quality_exclusions": ["missing_exchange_timestamp"],
        "random_seed": 20260730,
        "final_holdout_policy": "chronological_last_20_percent",
        "multiple_testing_policy": "benjamini_hochberg_fdr_5pct",
    }


def test_research_config_loads_declared_phase_one_design() -> None:
    config = load_research_config(Path("configs/research.toml"))

    assert config.initiating_venues == (Exchange.COINBASE, Exchange.KRAKEN)
    assert config.response_horizons_ms == (100, 250, 500)
    assert config.data_quality_exclusions


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_error"),
    [
        ("response_horizons_ms", [100, 500, 250], "sorted ascending"),
        ("response_horizons_ms", [100, 100, 250], "unique"),
        ("response_horizons_ms", [0, 100, 250], "positive"),
        ("event_threshold_ticks", 0, "greater than 0"),
        ("target_type", "return", "Input should be"),
        ("sampling_method", "clock_time", "Input should be"),
        ("primary_baseline", "random_forest", "Input should be"),
        ("final_holdout_policy", "random_split", "Input should be"),
        ("multiple_testing_policy", "none", "Input should be"),
    ],
)
def test_research_config_rejects_invalid_design_fields(
    field_name: str,
    bad_value: object,
    expected_error: str,
) -> None:
    data = valid_research_data()
    data[field_name] = bad_value

    with pytest.raises(ValidationError, match=expected_error):
        ResearchConfig.model_validate(data)


def test_research_config_rejects_unknown_venue() -> None:
    data = valid_research_data()
    data["initiating_venues"] = ["coinbase", "gemini"]

    with pytest.raises(ValidationError, match="Input should be"):
        ResearchConfig.model_validate(data)


def test_research_config_rejects_duplicate_venue() -> None:
    data = valid_research_data()
    data["initiating_venues"] = ["coinbase", "coinbase"]

    with pytest.raises(ValidationError, match="duplicate initiating venues"):
        ResearchConfig.model_validate(data)


def test_research_config_allows_empty_exclusion_list() -> None:
    data = valid_research_data()
    data["data_quality_exclusions"] = []

    config = ResearchConfig.model_validate(data)

    assert config.data_quality_exclusions == ()


def test_research_config_rejects_unknown_extra_field() -> None:
    data = valid_research_data()
    data["notes_for_me"] = "keep this out of recruiter-facing config"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchConfig.model_validate(data)
