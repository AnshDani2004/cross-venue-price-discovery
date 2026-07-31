"""Campaign configuration loading."""

from __future__ import annotations

import tomllib
from pathlib import Path

from cross_venue.campaigns.models import CampaignConfig


def load_campaign_config(path: Path) -> CampaignConfig:
    """Load and validate a strict Phase 3B campaign TOML file."""

    with path.open("rb") as handle:
        return CampaignConfig.model_validate(tomllib.load(handle))
