from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cross_venue.config import MarketRulesConfig, load_market_rules_config


def valid_market_rules_data() -> dict[str, Any]:
    return {
        "rules": [
            {
                "venue_id": "coinbase",
                "market_type": "spot",
                "canonical_instrument": "BTC-USD",
                "venue_symbol": "BTC-USD",
                "maker_fee_rate": "0.0040",
                "taker_fee_rate": "0.0060",
                "fee_tier_assumption": "public lowest volume tier",
                "tick_size": "0.01",
                "minimum_order_size": "0.00000001",
                "effective_date": "2026-07-30",
                "source": "https://help.coinbase.com/en/exchange/trading-and-funding/exchange-fees",
            },
            {
                "venue_id": "kraken",
                "market_type": "spot",
                "canonical_instrument": "BTC-USD",
                "venue_symbol": "BTC/USD",
                "maker_fee_rate": "0.0025",
                "taker_fee_rate": "0.0040",
                "fee_tier_assumption": "public zero-volume tier",
                "tick_size": "0.1",
                "minimum_order_size": "0.00005",
                "effective_date": "2026-07-30",
                "source": "https://api.kraken.com/0/public/AssetPairs?pair=BTCUSD",
            },
        ]
    }


def test_market_rules_config_loads_required_venue_rules() -> None:
    config = load_market_rules_config(Path("configs/market_rules.toml"))

    assert config.rules[0].maker_fee_rate == Decimal("0.0040")
    assert config.rules[1].tick_size == Decimal("0.1")


@pytest.mark.parametrize(
    ("field_name", "bad_value", "expected_error"),
    [
        ("effective_date", "not-a-date", "valid date"),
        ("maker_fee_rate", "-0.0001", "greater than or equal to 0"),
        ("taker_fee_rate", "-0.0001", "greater than or equal to 0"),
        ("tick_size", "0", "greater than 0"),
        ("minimum_order_size", "0", "greater than 0"),
        ("source", "http://example.com", "https URL"),
        ("market_type", "perpetual", "Input should be"),
    ],
)
def test_market_rules_config_rejects_invalid_fields(
    field_name: str,
    bad_value: object,
    expected_error: str,
) -> None:
    data = valid_market_rules_data()
    data["rules"][0][field_name] = bad_value

    with pytest.raises(ValidationError, match=expected_error):
        MarketRulesConfig.model_validate(data)


def test_market_rules_config_rejects_unknown_venue() -> None:
    data = valid_market_rules_data()
    data["rules"][0]["venue_id"] = "gemini"

    with pytest.raises(ValidationError, match="Input should be"):
        MarketRulesConfig.model_validate(data)


def test_market_rules_config_rejects_duplicate_venue_entries() -> None:
    data = valid_market_rules_data()
    data["rules"][1]["venue_id"] = "coinbase"
    data["rules"][1]["venue_symbol"] = "BTC-USD"

    with pytest.raises(ValidationError, match="duplicate market-rule venue"):
        MarketRulesConfig.model_validate(data)


def test_market_rules_config_rejects_unknown_extra_field() -> None:
    data = valid_market_rules_data()
    data["rules"][0]["local_comment"] = "do not publish"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MarketRulesConfig.model_validate(data)
