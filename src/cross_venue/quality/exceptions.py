"""Exceptions for Phase 2D quality analysis."""

from __future__ import annotations


class QualityError(Exception):
    """Base class for quality-analysis failures."""


class QualityAnalysisError(QualityError):
    """Raised when a session cannot be analyzed safely."""


class PromotionError(QualityError):
    """Raised when validated dataset promotion is not allowed."""
