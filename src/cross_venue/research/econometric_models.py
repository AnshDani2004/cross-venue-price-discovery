"""Econometric models and schemas for Phase 4C."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EconometricPriceDiscoveryReport(BaseModel):
    """Canonical JSON report for Phase 4C econometric analysis."""

    analysis_result_id: str
    output_schema_version: str = "v1"
    analysis_mode: str
    final_inference_permitted: bool
    dataset_validation_id: str
    dataset_snapshot_id: str
    phase_04b_result_id: str
    config_hash: str
    analysis_code_fingerprint: str
    runtime_git_commit: str
    dirty_working_tree: bool

    # Summary counts
    total_attempt_count: int
    venue_session_count: int
    authoritative_paired_overlap_seconds: float
    empirical_paired_overlap_seconds: float

    # Model Eligibility
    attempts_usable_for_stationarity: int
    attempts_usable_for_var: int
    attempts_usable_for_granger: int
    attempts_usable_for_irf: int
    attempts_supporting_cointegration: int
    attempts_supporting_vecm: int
    attempts_supporting_gonzalo_granger: int
    attempts_supporting_hasbrouck_is: int

    # Row Counts
    predictive_regression_row_count: int
    robustness_row_count: int

    warnings: list[str] = Field(default_factory=list)
    blocking_conditions: list[str] = Field(default_factory=list)

    output_inventory: list[str] = Field(default_factory=list)


# Parquet Schemas
# We will use Polars to enforce these during serialization.
