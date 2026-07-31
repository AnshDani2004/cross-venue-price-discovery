"""File locking and stale attempt recovery for campaign runs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from cross_venue.campaigns.exceptions import CampaignLockError
from cross_venue.campaigns.models import CampaignConfig, CampaignLockRecord
from cross_venue.campaigns.paths import lock_path
from cross_venue.quality.io import current_git_commit


class CampaignLock:
    """Context manager for a campaign lock file."""

    def __init__(
        self,
        config: CampaignConfig,
        *,
        slot_id: str,
        campaign_attempt_id: str,
        stale_after_seconds: int = 7200,
    ) -> None:
        self.config = config
        self.slot_id = slot_id
        self.campaign_attempt_id = campaign_attempt_id
        self.stale_after_seconds = stale_after_seconds
        self.path = lock_path(config)
        self.record = CampaignLockRecord(
            campaign_id=config.campaign_id,
            slot_id=slot_id,
            campaign_attempt_id=campaign_attempt_id,
            process_id=os.getpid(),
            started_at=datetime.now(UTC),
            runtime_commit=current_git_commit(),
        )

    def __enter__(self) -> CampaignLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self._stale():
            raise CampaignLockError(f"campaign lock already exists: {self.path}")
        if self.path.exists():
            self.path.unlink()
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise CampaignLockError(f"campaign lock already exists: {self.path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self.record.model_dump(mode="json"), handle, sort_keys=True)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        if self.path.exists():
            existing = CampaignLockRecord.model_validate_json(self.path.read_text(encoding="utf-8"))
            if existing.campaign_attempt_id == self.campaign_attempt_id:
                self.path.unlink()

    def _stale(self) -> bool:
        try:
            existing = CampaignLockRecord.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CampaignLockError("campaign lock file is corrupt") from exc
        if existing.campaign_id != self.config.campaign_id:
            raise CampaignLockError("lock belongs to a different campaign")
        age = datetime.now(UTC) - existing.started_at.astimezone(UTC)
        return age > timedelta(seconds=self.stale_after_seconds)
