"""Phase 3A normalization exception hierarchy."""


class NormalizationError(Exception):
    """Base class for deterministic normalization failures."""


class ValidatedManifestError(NormalizationError):
    """Validated dataset manifest input is missing, unsafe, or inconsistent."""


class ReplayError(NormalizationError):
    """Raw archive replay failed."""


class NormalizationSchemaError(NormalizationError):
    """Normalized schema validation failed."""


class DecimalRepresentationError(NormalizationError):
    """A financial Decimal cannot be represented exactly."""


class ReconciliationError(NormalizationError):
    """Normalized row counts or lineage do not reconcile to source records."""


class NormalizedDatasetValidationError(NormalizationError):
    """Final normalized dataset validation failed."""


class CatalogBuildError(NormalizationError):
    """DuckDB catalog creation failed."""


class DeterminismError(NormalizationError):
    """Repeated normalization did not produce deterministic results."""
