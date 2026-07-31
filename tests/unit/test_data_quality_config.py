from pathlib import Path

import pytest
from pydantic import ValidationError

from cross_venue.config import load_data_quality_config


def test_data_quality_config_loads_defaults() -> None:
    config = load_data_quality_config(Path("configs/data_quality.toml"))

    assert config.policy_version == "2d.1"
    assert config.quality.coverage.minimum_cross_venue_overlap_seconds == 90
    assert config.quality.timestamps.stale_quote_threshold_ms == 2000


def test_data_quality_config_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        Path("configs/data_quality.toml").read_text(encoding="utf-8") + "\nunknown_field = true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Extra inputs"):
        load_data_quality_config(path)


def test_data_quality_config_rejects_invalid_rates_and_overlap(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    text = Path("configs/data_quality.toml").read_text(encoding="utf-8")
    text = text.replace("max_parse_error_rate = 0.001", "max_parse_error_rate = 1.5")
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_data_quality_config(path)

    path.write_text(
        text.replace("max_parse_error_rate = 1.5", "max_parse_error_rate = 0.001").replace(
            "minimum_cross_venue_overlap_seconds = 90",
            "minimum_cross_venue_overlap_seconds = 121",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="minimum overlap"):
        load_data_quality_config(path)
