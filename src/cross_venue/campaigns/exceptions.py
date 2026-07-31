"""Campaign-specific exception hierarchy."""

from __future__ import annotations


class CampaignError(Exception):
    """Base class for Phase 3B campaign failures."""


class CampaignConfigError(CampaignError):
    """Campaign configuration is invalid."""


class CampaignRegistryError(CampaignError):
    """Campaign registry is invalid or cannot be updated."""


class CampaignScheduleError(CampaignError):
    """Campaign schedule is invalid."""


class CampaignSlotNotDueError(CampaignError):
    """A collection slot is outside its execution window."""


class CampaignLockError(CampaignError):
    """Campaign lock acquisition or recovery failed."""


class CampaignRuntimeCommitError(CampaignError):
    """Runtime commit does not match the frozen campaign commit."""


class CampaignAttemptError(CampaignError):
    """Campaign attempt failed."""


class CampaignCompletionError(CampaignError):
    """Campaign cannot be completed or finalized."""


class CampaignManifestError(CampaignError):
    """Validated campaign manifest cannot be created or verified."""


class CampaignValidationError(CampaignError):
    """Campaign validation failed."""
