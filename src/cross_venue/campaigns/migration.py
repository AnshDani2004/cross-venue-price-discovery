"""Controlled campaign runtime migration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cross_venue.campaigns.completion import recalculate_registry
from cross_venue.campaigns.exceptions import CampaignRuntimeCommitError
from cross_venue.campaigns.ledger import (
    append_event,
    ledger_sha256,
    make_event,
    read_ledger,
    rebuild_registry_from_ledger,
)
from cross_venue.campaigns.models import (
    CAMPAIGN_SCHEMA_VERSION,
    AttemptStatus,
    CampaignConfig,
    CampaignStatus,
    LedgerEventType,
    RuntimeMigrationReason,
)
from cross_venue.campaigns.paths import campaign_root, ledger_path
from cross_venue.campaigns.registry import (
    validate_registry_and_ledger,
    working_tree_clean,
    write_registry,
)
from cross_venue.quality.io import current_git_commit, utc_now
from cross_venue.storage.checksum import sha256_file


def migrate_campaign_runtime(
    config: CampaignConfig,
    *,
    reason: RuntimeMigrationReason,
    new_runtime_commit: str | None = None,
) -> dict[str, Any]:
    """Append a pre-collection runtime migration event and rebuild the registry."""

    registry = validate_registry_and_ledger(config)
    events = read_ledger(ledger_path(config))
    if any(event.event_type == LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED for event in events):
        raise CampaignRuntimeCommitError("campaign runtime has already been migrated")
    if registry.campaign_status not in {CampaignStatus.PLANNED, CampaignStatus.IN_PROGRESS}:
        raise CampaignRuntimeCommitError("campaign status does not allow runtime migration")
    if not working_tree_clean():
        raise CampaignRuntimeCommitError("runtime migration requires a clean working tree")
    if any(event.event_type == LedgerEventType.ATTEMPT_STARTED for event in events):
        raise CampaignRuntimeCommitError("runtime migration is blocked after an attempt starts")
    if registry.attempts:
        raise CampaignRuntimeCommitError("runtime migration is blocked when attempts exist")
    if _campaign_attempt_archives_exist(config):
        raise CampaignRuntimeCommitError("runtime migration is blocked when attempt archives exist")
    if registry.accepted_attempt_count != 0 or registry.accepted_overlap_seconds != 0:
        raise CampaignRuntimeCommitError("runtime migration requires zero accepted campaign data")
    if registry.campaign_config_sha256 != sha256_file(Path(registry.campaign_config_path)):
        raise CampaignRuntimeCommitError("runtime migration blocked by campaign config hash drift")
    if registry.quality_policy_sha256 != sha256_file(Path("configs/data_quality.toml")):
        raise CampaignRuntimeCommitError("runtime migration blocked by quality policy hash drift")
    if any(
        attempt.attempt_status
        in {
            AttemptStatus.STARTED,
            AttemptStatus.ACCEPTED,
            AttemptStatus.QUARANTINED,
            AttemptStatus.REJECTED,
            AttemptStatus.FAILED,
            AttemptStatus.ABORTED,
        }
        for attempt in registry.attempts.values()
    ):
        raise CampaignRuntimeCommitError("runtime migration is blocked by existing attempt status")

    current_commit = current_git_commit()
    if not current_commit:
        raise CampaignRuntimeCommitError("current runtime commit could not be determined")
    target_commit = new_runtime_commit or current_commit
    old_runtime_commit = registry.runtime_git_commit
    if target_commit == old_runtime_commit:
        raise CampaignRuntimeCommitError("runtime migration target matches existing runtime")

    payload = {
        "old_runtime_commit": old_runtime_commit,
        "new_runtime_commit": target_commit,
        "migration_reason": reason.value,
        "migration_timestamp": utc_now().isoformat(),
        "campaign_config_sha256": registry.campaign_config_sha256,
        "quality_policy_sha256": registry.quality_policy_sha256,
        "no_collection_attempt_existed": True,
        "generic_engine_schema_version": CAMPAIGN_SCHEMA_VERSION,
        "runtime_working_tree_clean": working_tree_clean(),
    }
    lpath = ledger_path(config)
    event = make_event(
        path=lpath,
        campaign_id=config.campaign_id,
        event_type=LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED,
        payload=payload,
    )
    append_event(lpath, event)
    rebuilt = rebuild_registry_from_ledger(config, read_ledger(lpath)).model_copy(
        update={"ledger_sha256": ledger_sha256(lpath), "updated_at": utc_now()}
    )
    rebuilt = recalculate_registry(rebuilt)
    write_registry(config, rebuilt)
    return {
        "campaign_id": config.campaign_id,
        "migration_status": "MIGRATED",
        "old_runtime_commit": old_runtime_commit,
        "new_runtime_commit": target_commit,
        "migration_reason": reason.value,
        "ledger_event_index": event.event_index,
        "ledger_event_hash": event.event_hash,
    }


def _campaign_attempt_archives_exist(config: CampaignConfig) -> bool:
    attempts_root = campaign_root(config) / "attempts"
    return attempts_root.exists() and any(attempts_root.iterdir())
