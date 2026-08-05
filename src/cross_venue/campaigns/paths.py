"""Path helpers for ignored campaign state."""

from __future__ import annotations

from pathlib import Path

from cross_venue.campaigns.models import CampaignConfig
from cross_venue.storage.paths import resolve_under_root, safe_path_component


def campaign_root(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    """Return the ignored root for one campaign."""

    return (
        config.registry_root / f"campaign={safe_path_component(campaign_id or config.campaign_id)}"
    )


def registry_path(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    return campaign_root(config, campaign_id) / "registry" / "campaign_registry.json"


def ledger_path(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    return campaign_root(config, campaign_id) / "ledger" / "campaign_events.jsonl"


def lock_path(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    return campaign_root(config, campaign_id) / "locks" / "campaign.lock"


def reports_root(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    return campaign_root(config, campaign_id) / "reports"


def manifest_root(config: CampaignConfig, campaign_id: str | None = None) -> Path:
    return campaign_root(config, campaign_id) / "manifest"


def attempt_root(config: CampaignConfig, slot_id: str, attempt_number: int) -> Path:
    return (
        campaign_root(config)
        / "attempts"
        / f"slot={safe_path_component(slot_id)}"
        / f"attempt={attempt_number:03d}"
    )


def resolve_campaign_path(config: CampaignConfig, path: Path) -> Path:
    """Resolve a path under the campaign root."""

    return resolve_under_root(campaign_root(config), campaign_root(config) / path)
