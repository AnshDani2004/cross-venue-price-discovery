"""Storage exceptions for raw archival and recovery."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for Phase 2C storage errors."""


class ArchiveWriterError(StorageError):
    """Raised when raw archival writing fails."""


class ArchiveBackpressureError(ArchiveWriterError):
    """Raised when a bounded archive queue cannot accept a record."""


class ArchiveRotationError(ArchiveWriterError):
    """Raised when shard rotation or finalization fails."""


class ManifestPersistenceError(StorageError):
    """Raised when a manifest cannot be persisted atomically."""


class QualityPersistenceError(StorageError):
    """Raised when a quality summary cannot be persisted atomically."""


class ChecksumError(StorageError):
    """Raised when checksum creation or validation fails."""


class RecoveryError(StorageError):
    """Raised when archive recovery cannot be completed safely."""
