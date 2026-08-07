"""Research snapshot exception hierarchy."""

from __future__ import annotations


class ResearchError(Exception):
    """Base class for research-analysis failures."""


class ResearchSnapshotError(ResearchError):
    """Base class for analysis source snapshot failures."""


class SourceCatalogError(ResearchSnapshotError):
    """Source campaign state cannot be converted into a valid source catalog."""


class SnapshotPersistenceError(ResearchSnapshotError):
    """Analysis snapshot persistence failed or would violate immutability."""


class SnapshotValidationError(ResearchSnapshotError):
    """Analysis snapshot validation failed."""
