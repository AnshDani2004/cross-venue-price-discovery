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
    AttemptSummary,
    CampaignConfig,
    CampaignStatus,
    FailureClassification,
    LedgerEventType,
    RuntimeMigrationReason,
)
from cross_venue.campaigns.paths import attempt_root, campaign_root, ledger_path
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
    if registry.campaign_status not in {CampaignStatus.PLANNED, CampaignStatus.IN_PROGRESS}:
        raise CampaignRuntimeCommitError("campaign status does not allow runtime migration")
    if not working_tree_clean():
        raise CampaignRuntimeCommitError("runtime migration requires a clean working tree")
    if registry.accepted_attempt_count != 0 or registry.accepted_overlap_seconds != 0:
        raise CampaignRuntimeCommitError("runtime migration requires zero accepted campaign data")
    if registry.campaign_config_sha256 != sha256_file(Path(registry.campaign_config_path)):
        raise CampaignRuntimeCommitError("runtime migration blocked by campaign config hash drift")
    if registry.quality_policy_sha256 != sha256_file(Path("configs/data_quality.toml")):
        raise CampaignRuntimeCommitError("runtime migration blocked by quality policy hash drift")
    current_commit = current_git_commit()
    if not current_commit:
        raise CampaignRuntimeCommitError("current runtime commit could not be determined")
    target_commit = new_runtime_commit or current_commit
    old_runtime_commit = registry.runtime_git_commit
    if target_commit == old_runtime_commit:
        raise CampaignRuntimeCommitError("runtime migration target matches existing runtime")
    if any(
        event.payload.get("new_runtime_commit") == target_commit
        for event in events
        if event.event_type
        in {
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE,
            LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS,
        }
    ):
        raise CampaignRuntimeCommitError("campaign runtime has already migrated to target commit")

    zero_data_failed_attempt_ids = _zero_data_failed_attempt_ids(config, registry.attempts)
    excluded_attempt_ids = _excluded_terminal_attempt_ids(registry.attempts)
    if registry.attempts and not zero_data_failed_attempt_ids and not excluded_attempt_ids:
        raise CampaignRuntimeCommitError(
            "runtime migration is blocked by collected attempt evidence"
        )
    if (
        zero_data_failed_attempt_ids
        and reason != RuntimeMigrationReason.LONG_DURATION_PREFLIGHT_FIX
    ):
        raise CampaignRuntimeCommitError(
            "zero-data failed attempt migration requires LONG_DURATION_PREFLIGHT_FIX"
        )
    if (
        excluded_attempt_ids
        and not zero_data_failed_attempt_ids
        and reason
        not in {
            RuntimeMigrationReason.CAMPAIGN_MESSAGE_LIMIT_PROPAGATION_FIX,
            RuntimeMigrationReason.COLLECTOR_INTERNAL_MESSAGE_LIMIT_FIX,
        }
    ):
        raise CampaignRuntimeCommitError(
            "excluded attempt migration requires a corrective excluded-attempt reason"
        )
    if not registry.attempts and _campaign_attempt_archives_exist(config):
        raise CampaignRuntimeCommitError("runtime migration is blocked when attempt archives exist")
    no_accepted_dataset_membership = all(
        attempt.validated_pair_manifest_id is None
        and attempt.validated_pair_manifest_path is None
        and attempt.validated_pair_manifest_sha256 is None
        for attempt in registry.attempts.values()
    )
    if not no_accepted_dataset_membership:
        raise CampaignRuntimeCommitError(
            "runtime migration is blocked by accepted dataset membership"
        )

    payload = {
        "old_runtime_commit": old_runtime_commit,
        "new_runtime_commit": target_commit,
        "migration_reason": reason.value,
        "migration_timestamp": utc_now().isoformat(),
        "campaign_config_sha256": registry.campaign_config_sha256,
        "quality_policy_sha256": registry.quality_policy_sha256,
        "no_collection_attempt_existed": not registry.attempts,
        "zero_data_failed_attempt_ids": zero_data_failed_attempt_ids,
        "excluded_attempt_ids": excluded_attempt_ids,
        "attempt_statuses": {
            attempt_id: registry.attempts[attempt_id].attempt_status.value
            for attempt_id in excluded_attempt_ids
        },
        "attempt_inclusion_states": {
            attempt_id: registry.attempts[attempt_id].inclusion_status.value
            for attempt_id in excluded_attempt_ids
        },
        "attempt_source_hashes": {
            attempt_id: _attempt_source_hashes(registry.attempts[attempt_id])
            for attempt_id in excluded_attempt_ids
        },
        "no_accepted_dataset_membership": no_accepted_dataset_membership,
        "no_market_data_evidence_existed": not excluded_attempt_ids,
        "generic_engine_schema_version": CAMPAIGN_SCHEMA_VERSION,
        "runtime_working_tree_clean": working_tree_clean(),
    }
    if zero_data_failed_attempt_ids:
        event_type = LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_ZERO_DATA_FAILURE
    elif excluded_attempt_ids:
        event_type = LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED_AFTER_EXCLUDED_ATTEMPTS
    else:
        event_type = LedgerEventType.CAMPAIGN_RUNTIME_MIGRATED
    lpath = ledger_path(config)
    event = make_event(
        path=lpath,
        campaign_id=config.campaign_id,
        event_type=event_type,
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
        "migration_event_type": event.event_type.value,
        "ledger_event_index": event.event_index,
        "ledger_event_hash": event.event_hash,
    }


def _campaign_attempt_archives_exist(config: CampaignConfig) -> bool:
    attempts_root = campaign_root(config) / "attempts"
    return attempts_root.exists() and any(attempts_root.iterdir())


def _zero_data_failed_attempt_ids(
    config: CampaignConfig,
    attempts: dict[str, AttemptSummary],
) -> tuple[str, ...]:
    if not attempts:
        return ()
    qualified: list[str] = []
    for attempt in attempts.values():
        if not _is_zero_data_failed_attempt(config, attempt):
            return ()
        qualified.append(attempt.campaign_attempt_id)
    return tuple(sorted(qualified))


def _is_zero_data_failed_attempt(config: CampaignConfig, attempt: AttemptSummary) -> bool:
    if attempt.attempt_status != AttemptStatus.FAILED:
        return False
    if attempt.failure_classification not in {
        FailureClassification.UNKNOWN_FAILURE,
        FailureClassification.COLLECTION_PREFLIGHT_FAILURE,
    }:
        return False
    if attempt.actual_collection_duration_seconds not in {None, 0}:
        return False
    if attempt.coinbase_frame_count != 0 or attempt.kraken_frame_count != 0:
        return False
    if attempt.coinbase_session_id is not None or attempt.kraken_session_id is not None:
        return False
    if attempt.paired_collection_id is not None or attempt.paired_overlap_seconds != 0:
        return False
    if attempt.validated_pair_manifest_id is not None:
        return False
    if attempt.validated_pair_manifest_path is not None:
        return False
    if attempt.validated_pair_manifest_sha256 is not None:
        return False
    if attempt.source_session_manifest_hashes:
        return False
    if attempt.source_raw_shard_checksums:
        return False
    if attempt.session_quality_report_hashes or attempt.paired_quality_report_hash is not None:
        return False
    if attempt.promotion_dry_run_allowed:
        return False
    return not attempt_root(config, attempt.slot_id, attempt.attempt_number).exists()


def _excluded_terminal_attempt_ids(
    attempts: dict[str, AttemptSummary],
) -> tuple[str, ...]:
    if not attempts:
        return ()
    allowed_statuses = {AttemptStatus.FAILED, AttemptStatus.REJECTED}
    qualified: list[str] = []
    for attempt in attempts.values():
        if attempt.attempt_status not in allowed_statuses:
            return ()
        if attempt.inclusion_status.value != "EXCLUDED":
            return ()
        if attempt.validated_pair_manifest_id is not None:
            return ()
        if attempt.validated_pair_manifest_path is not None:
            return ()
        if attempt.validated_pair_manifest_sha256 is not None:
            return ()
        qualified.append(attempt.campaign_attempt_id)
    return tuple(sorted(qualified))


def _attempt_source_hashes(attempt: AttemptSummary) -> dict[str, Any]:
    return {
        "source_session_manifest_hashes": dict(attempt.source_session_manifest_hashes),
        "source_raw_shard_checksums": {
            session_id: dict(checksums)
            for session_id, checksums in attempt.source_raw_shard_checksums.items()
        },
        "session_quality_report_hashes": dict(attempt.session_quality_report_hashes),
        "paired_quality_report_hash": attempt.paired_quality_report_hash,
        "validated_pair_manifest_sha256": attempt.validated_pair_manifest_sha256,
    }
