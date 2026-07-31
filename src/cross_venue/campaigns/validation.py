"""Campaign registry and ledger validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cross_venue.campaigns.exceptions import CampaignValidationError
from cross_venue.campaigns.ledger import ledger_sha256
from cross_venue.campaigns.models import AttemptStatus, CampaignConfig, InclusionStatus
from cross_venue.campaigns.paths import ledger_path, reports_root
from cross_venue.campaigns.registry import load_registry, validate_registry_and_ledger
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json


def validate_campaign(config: CampaignConfig) -> dict[str, Any]:
    """Validate campaign config, registry, ledger, and accepted-attempt invariants."""

    errors: list[str] = []
    try:
        registry = validate_registry_and_ledger(config)
    except Exception as exc:
        registry = load_registry(config)
        errors.append(str(exc))
    config_path = Path(registry.campaign_config_path)
    if not config_path.exists():
        errors.append(f"campaign config path missing: {registry.campaign_config_path}")
    elif registry.campaign_config_sha256 != sha256_file(config_path):
        errors.append("campaign config hash mismatch")
    if registry.quality_policy_sha256 != sha256_file(Path("configs/data_quality.toml")):
        errors.append("quality policy hash mismatch")
    if registry.ledger_sha256 != ledger_sha256(ledger_path(config)):
        errors.append("ledger sha mismatch")
    if len(registry.attempts) > config.maximum_attempts:
        errors.append("maximum attempts exceeded")
    accepted = [
        attempt
        for attempt in registry.attempts.values()
        if attempt.attempt_status == AttemptStatus.ACCEPTED
    ]
    for attempt in accepted:
        if attempt.inclusion_status != InclusionStatus.INCLUDED:
            errors.append(f"accepted attempt omitted: {attempt.campaign_attempt_id}")
        if not attempt.validated_pair_manifest_path:
            errors.append(f"accepted attempt missing manifest: {attempt.campaign_attempt_id}")
        if attempt.paired_overlap_seconds < config.minimum_overlap_seconds_per_accepted_session:
            errors.append(f"accepted attempt overlap too short: {attempt.campaign_attempt_id}")
    report = {
        "campaign_id": config.campaign_id,
        "campaign_role": registry.campaign_role.value,
        "validation_status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "attempt_count": len(registry.attempts),
        "accepted_attempt_count": registry.accepted_attempt_count,
        "accepted_overlap_seconds": registry.accepted_overlap_seconds,
    }
    root = reports_root(config)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "campaign_validation_report.json", dict(report))
    if errors:
        raise CampaignValidationError("; ".join(errors))
    return report
