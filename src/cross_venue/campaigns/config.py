"""Campaign configuration loading."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from cross_venue.campaigns.exceptions import CampaignConfigError
from cross_venue.campaigns.models import (
    DEFAULT_PHASE_3B_CAMPAIGN_ID,
    CampaignConfig,
    CampaignId,
    validate_campaign_id,
)

DEFAULT_CAMPAIGN_CONFIG_PATH = Path("configs/campaigns/phase_3b_btc_usd.toml")
DEFAULT_CAMPAIGN_REGISTRY_ROOT = Path("data/campaigns")


def load_campaign_config(path: Path) -> CampaignConfig:
    """Load and validate a strict campaign TOML file."""

    with path.open("rb") as handle:
        return CampaignConfig.model_validate(tomllib.load(handle))


def load_campaign_config_for_id(
    campaign_id: str,
    *,
    config_path: Path | None = None,
) -> CampaignConfig:
    """Load the selected campaign config from an explicit path or its registry."""

    validated_id = validate_campaign_id(campaign_id)
    if config_path is not None:
        config = load_campaign_config(config_path)
        _require_config_identity(config, validated_id)
        return config
    registry_path = _registry_path_for_id(validated_id)
    if registry_path.exists():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        stored_config_path = Path(str(payload["campaign_config_path"]))
        config = load_campaign_config(stored_config_path)
        _require_config_identity(config, validated_id)
        return config
    if validated_id == DEFAULT_PHASE_3B_CAMPAIGN_ID:
        return load_campaign_config(DEFAULT_CAMPAIGN_CONFIG_PATH)
    raise CampaignConfigError(f"campaign config could not be resolved for ID: {validated_id}")


def stored_config_path(config_path: Path) -> str:
    """Return a portable config path suitable for registry storage."""

    if config_path.is_absolute():
        try:
            return config_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError as exc:
            raise CampaignConfigError(
                "campaign config path must be under the repository root"
            ) from exc
    return config_path.as_posix()


def _registry_path_for_id(campaign_id: CampaignId) -> Path:
    return (
        DEFAULT_CAMPAIGN_REGISTRY_ROOT
        / f"campaign={campaign_id}"
        / "registry"
        / "campaign_registry.json"
    )


def _require_config_identity(config: CampaignConfig, campaign_id: CampaignId) -> None:
    if config.campaign_id != campaign_id:
        raise CampaignConfigError(
            f"campaign ID {campaign_id} does not match config ID {config.campaign_id}"
        )
