"""Bounded campaign slot execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from cross_venue.campaigns.exceptions import (
    CampaignAttemptError,
    CampaignRuntimeCommitError,
    CampaignSlotNotDueError,
)
from cross_venue.campaigns.locking import CampaignLock
from cross_venue.campaigns.models import (
    AttemptExclusionReason,
    AttemptStatus,
    AttemptSummary,
    CampaignConfig,
    FailureClassification,
    InclusionStatus,
    LedgerEventType,
)
from cross_venue.campaigns.registry import (
    next_attempt_number,
    record_attempt_event,
    validate_registry_and_ledger,
    working_tree_clean,
)
from cross_venue.campaigns.schedule import require_slot_executable
from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.collection import PairedCollectionResult, collect_paired_quality
from cross_venue.quality.exceptions import CollectionPreflightError, PromotionError
from cross_venue.quality.io import current_git_commit, model_sha256, portable_relative_path
from cross_venue.quality.models import QualityDisposition
from cross_venue.quality.promotion import promote_dataset
from cross_venue.storage.checksum import sha256_file

PairedRunner = Callable[[float, int], Awaitable[PairedCollectionResult]]


async def run_campaign_slot(
    config: CampaignConfig,
    *,
    slot_id: str,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    runner: PairedRunner | None = None,
    now: datetime | None = None,
) -> AttemptSummary:
    """Run one currently due campaign slot."""

    registry = validate_registry_and_ledger(config)
    slot = config.slot_by_id(slot_id)
    require_slot_executable(config, slot, now=now)
    if config.require_clean_working_tree and not working_tree_clean():
        raise CampaignAttemptError("campaign slot execution requires a clean working tree")
    if config.require_frozen_runtime_commit and current_git_commit() != registry.runtime_git_commit:
        raise CampaignRuntimeCommitError("runtime commit differs from frozen campaign commit")
    attempt_number = next_attempt_number(registry, slot_id)
    attempt_id = f"{config.campaign_id}-{slot_id}-{attempt_number:03d}"
    started = datetime.now(UTC)
    started_attempt = AttemptSummary(
        campaign_id=config.campaign_id,
        slot_id=slot_id,
        attempt_number=attempt_number,
        campaign_attempt_id=attempt_id,
        slot_type=slot.slot_type,
        planned_start_utc=slot.planned_start_utc,
        planned_start_local=slot.planned_start_local,
        time_bucket=slot.time_bucket,
        actual_started_at=started,
        requested_duration_seconds=config.requested_duration_seconds,
        maximum_messages_per_venue=config.maximum_messages_per_venue,
        attempt_runtime_git_commit=registry.runtime_git_commit,
        attempt_status=AttemptStatus.STARTED,
        exclusion_reason=AttemptExclusionReason.ATTEMPT_NOT_COMPLETE.value,
    )
    with CampaignLock(config, slot_id=slot_id, campaign_attempt_id=attempt_id):
        record_attempt_event(
            config,
            event_type=LedgerEventType.ATTEMPT_STARTED,
            attempt=started_attempt,
        )
        try:
            paired_runner = runner or _default_runner(storage_config, quality_config)
            result = await paired_runner(
                float(config.requested_duration_seconds),
                config.maximum_messages_per_venue,
            )
            final = _attempt_from_result(
                config,
                started_attempt,
                result,
                quality_config=quality_config,
            )
        except CampaignSlotNotDueError:
            raise
        except CollectionPreflightError as exc:
            final = started_attempt.model_copy(
                update={
                    "actual_completed_at": datetime.now(UTC),
                    "attempt_status": AttemptStatus.FAILED,
                    "failure_classification": FailureClassification.COLLECTION_PREFLIGHT_FAILURE,
                    "failure_message": str(exc)[:500],
                    "exclusion_reason": (AttemptExclusionReason.COLLECTION_PREFLIGHT_FAILED.value),
                }
            )
        except Exception as exc:
            final = started_attempt.model_copy(
                update={
                    "actual_completed_at": datetime.now(UTC),
                    "attempt_status": AttemptStatus.FAILED,
                    "failure_classification": FailureClassification.UNKNOWN_FAILURE,
                    "failure_message": str(exc)[:500],
                    "exclusion_reason": AttemptExclusionReason.ATTEMPT_FAILED.value,
                }
            )
        record_attempt_event(config, event_type=_final_event_type(final), attempt=final)
        return final


def _default_runner(
    storage_config: StorageConfig, quality_config: DataQualityConfig
) -> PairedRunner:
    async def wrapped(
        duration_seconds: float, max_messages_per_venue: int
    ) -> PairedCollectionResult:
        return await collect_paired_quality(
            storage_config=storage_config,
            quality_config=quality_config,
            duration_seconds=duration_seconds,
            max_messages_per_venue=max_messages_per_venue,
        )

    return wrapped


def _attempt_from_result(
    config: CampaignConfig,
    started: AttemptSummary,
    result: PairedCollectionResult,
    *,
    quality_config: DataQualityConfig,
) -> AttemptSummary:
    paired = result.paired_report
    coinbase = paired.coinbase_report
    kraken = paired.kraken_report
    promotion_dry_run_allowed = False
    manifest_id: str | None = None
    manifest_path: str | None = None
    manifest_sha: str | None = None
    status = AttemptStatus.REJECTED
    inclusion = InclusionStatus.EXCLUDED
    exclusion_reason: str | None = _rejected_exclusion_reason(config, result)
    failure_classification: FailureClassification | None = None
    failure_message: str | None = None
    try:
        dry_manifest, _message = promote_dataset(
            paired,
            quality_config=quality_config,
            apply=False,
        )
        promotion_dry_run_allowed = dry_manifest is not None
    except PromotionError as exc:
        failure_classification = FailureClassification.PROMOTION_FAILURE
        failure_message = str(exc)[:500]
    if (
        coinbase.archive_validation_passed
        and kraken.archive_validation_passed
        and coinbase.disposition == QualityDisposition.ACCEPTED
        and kraken.disposition == QualityDisposition.ACCEPTED
        and paired.disposition == QualityDisposition.ACCEPTED
        and paired.overlap.market_event_overlap_duration_seconds
        >= config.minimum_overlap_seconds_per_accepted_session
        and promotion_dry_run_allowed
    ):
        applied_manifest, _message = promote_dataset(
            paired,
            quality_config=quality_config,
            apply=True,
        )
        if applied_manifest is None:
            raise CampaignAttemptError("accepted attempt did not create validated manifest")
        manifest_id = applied_manifest.dataset_manifest_id
        manifest_path = portable_relative_path(
            config.validated_manifest_root,
            config.validated_manifest_root / f"{manifest_id}.json",
        )
        manifest_sha = sha256_file(config.validated_manifest_root / f"{manifest_id}.json")
        status = AttemptStatus.ACCEPTED
        inclusion = InclusionStatus.INCLUDED
        exclusion_reason = None
    elif paired.disposition == QualityDisposition.QUARANTINED:
        status = AttemptStatus.QUARANTINED
        exclusion_reason = AttemptExclusionReason.PAIRED_QUALITY_QUARANTINED.value
    else:
        status = AttemptStatus.REJECTED
    completed = datetime.now(UTC)
    return started.model_copy(
        update={
            "actual_completed_at": completed,
            "actual_collection_duration_seconds": (
                completed - (started.actual_started_at or completed)
            ).total_seconds(),
            "paired_overlap_seconds": paired.overlap.market_event_overlap_duration_seconds,
            "paired_collection_id": paired.paired_collection_id,
            "coinbase_session_id": coinbase.session_id,
            "kraken_session_id": kraken.session_id,
            "coinbase_frame_count": coinbase.metrics.coverage.frames_received,
            "kraken_frame_count": kraken.metrics.coverage.frames_received,
            "coinbase_effective_duration_limit_seconds": (
                result.coinbase_summary.effective_duration_limit_seconds
            ),
            "kraken_effective_duration_limit_seconds": (
                result.kraken_summary.effective_duration_limit_seconds
            ),
            "coinbase_effective_message_limit": result.coinbase_summary.effective_message_limit,
            "kraken_effective_message_limit": result.kraken_summary.effective_message_limit,
            "coinbase_stop_reason": str(result.coinbase_summary.stop_reason),
            "kraken_stop_reason": str(result.kraken_summary.stop_reason),
            "coinbase_trade_count": coinbase.metrics.coverage.trades,
            "kraken_trade_count": kraken.metrics.coverage.trades,
            "coinbase_bbo_count": coinbase.metrics.coverage.top_of_book_events,
            "kraken_bbo_count": kraken.metrics.coverage.top_of_book_events,
            "coinbase_archive_valid": coinbase.archive_validation_passed,
            "kraken_archive_valid": kraken.archive_validation_passed,
            "coinbase_disposition": coinbase.disposition.value,
            "kraken_disposition": kraken.disposition.value,
            "paired_disposition": paired.disposition.value,
            "promotion_dry_run_allowed": promotion_dry_run_allowed,
            "validated_pair_manifest_id": manifest_id,
            "validated_pair_manifest_path": manifest_path,
            "validated_pair_manifest_sha256": manifest_sha,
            "source_session_manifest_hashes": {
                coinbase.session_id: coinbase.source_manifest_sha256,
                kraken.session_id: kraken.source_manifest_sha256,
            },
            "source_raw_shard_checksums": {
                coinbase.session_id: dict(coinbase.input_shard_checksums),
                kraken.session_id: dict(kraken.input_shard_checksums),
            },
            "session_quality_report_hashes": {
                coinbase.session_id: model_sha256(coinbase),
                kraken.session_id: model_sha256(kraken),
            },
            "paired_quality_report_hash": model_sha256(paired),
            "attempt_status": status,
            "failure_classification": failure_classification,
            "failure_message": failure_message,
            "inclusion_status": inclusion,
            "exclusion_reason": exclusion_reason,
        }
    )


def _rejected_exclusion_reason(
    config: CampaignConfig,
    result: PairedCollectionResult,
) -> str:
    paired = result.paired_report
    coinbase = paired.coinbase_report
    kraken = paired.kraken_report
    if not coinbase.archive_validation_passed or not kraken.archive_validation_passed:
        return AttemptExclusionReason.ARCHIVE_VALIDATION_FAILED.value
    if coinbase.disposition != QualityDisposition.ACCEPTED:
        return AttemptExclusionReason.COINBASE_QUALITY_NOT_ACCEPTED.value
    if kraken.disposition != QualityDisposition.ACCEPTED:
        return AttemptExclusionReason.KRAKEN_QUALITY_NOT_ACCEPTED.value
    if paired.disposition != QualityDisposition.ACCEPTED:
        return AttemptExclusionReason.PAIRED_QUALITY_NOT_ACCEPTED.value
    observed = paired.overlap.market_event_overlap_duration_seconds
    required = config.minimum_overlap_seconds_per_accepted_session
    if observed < required:
        return (
            f"{AttemptExclusionReason.INSUFFICIENT_PAIRED_OVERLAP.value}: "
            f"observed={observed:g}, required={required:g}"
        )
    return AttemptExclusionReason.PROMOTION_DRY_RUN_BLOCKED.value


def _final_event_type(attempt: AttemptSummary) -> LedgerEventType:
    return {
        AttemptStatus.ACCEPTED: LedgerEventType.ATTEMPT_ACCEPTED,
        AttemptStatus.QUARANTINED: LedgerEventType.ATTEMPT_QUARANTINED,
        AttemptStatus.REJECTED: LedgerEventType.ATTEMPT_REJECTED,
        AttemptStatus.FAILED: LedgerEventType.ATTEMPT_FAILED,
        AttemptStatus.ABORTED: LedgerEventType.ATTEMPT_ABORTED,
    }.get(attempt.attempt_status, LedgerEventType.ATTEMPT_FAILED)
