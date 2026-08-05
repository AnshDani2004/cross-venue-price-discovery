"""Campaign status text helpers."""

from __future__ import annotations

from cross_venue.campaigns.models import CampaignRegistry


def registry_summary_text(registry: CampaignRegistry) -> str:
    """Return a concise user-facing registry summary."""

    return "\n".join(
        [
            f"Campaign ID: {registry.campaign_id}",
            f"Role: {registry.campaign_role.value}",
            f"Status: {registry.campaign_status.value}",
            f"Runtime commit: {registry.runtime_git_commit}",
            f"Accepted attempts: {registry.accepted_attempt_count}",
            f"Accepted overlap seconds: {registry.accepted_overlap_seconds}",
            f"Completion: {registry.completion_status.value}",
        ]
    )
