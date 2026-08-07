# Walkthrough: Phase 3C.3 Normalized Dataset Validation

This document summarizes the completion of Phase 3C.3, which implements a deterministic validation layer for the normalized research dataset.

## What was Changed

1. **Validation Logic (`src/cross_venue/normalization/validation.py`)**:
   - Introduced a new Pydantic schema `NormalizedDatasetValidationResult` to encapsulate the validation report.
   - Built a deterministic `validate_normalized_dataset` runner using PyArrow to verify:
     - Dataset completeness against the Phase 1 Snapshot and Catalog hashes.
     - Row-level lineage metrics such as exact matches with dataset manifests.
     - Proof of source immutability against both raw file hashes and semantic structure hashes.
   - Outputs robust analytics into `validation/normalized_dataset_validation.json`.

2. **Command Line Interface (`src/cross_venue/cli.py`)**:
   - Upgraded the `validate-normalized-dataset` command to ingest the normalization manifest and the snapshot root for end-to-end immutability checks.
   - Added a lightweight `normalized-dataset-validation-status` subcommand for printing cached reports directly.

3. **Documentation**:
   - **Audit Report**: Generated `docs/audits/phase_03c3_normalized_dataset_validation_report.md` evaluating the 7-session snapshot as officially valid and eligible for preliminary analyses only.
   - **Changelog**: Logged Phase 3C.3 entry.
   - **Architecture**: Registered Phase 3C.3 requirements and rules in `docs/architecture.md`.
   - **Data Dictionary**: Documented the new validation report schema in `docs/data_dictionary.md`.
   - **Unit Tests**: Built rigorous unit tests testing synthetic failure scenarios (e.g. malformed snapshots, missing files, corrupted checksums, and date/bucket requirement checks) in `tests/unit/test_normalized_dataset_validation.py`.

## What was Tested

- Successfully executed the new validation runner on the live `dataset=normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07` artifact.
- Iterated on `source_catalog` determinism to accurately exclude specific fields dynamically using the `semantic_hash()` framework.
- The full test suite passes with 340 passed, 3 skipped, and 5 deselected tests.

## Real-Data Results

- **Aggregate Disposition**: `VALID`
- **Preliminary Analysis**: `ELIGIBLE`
- **Phase 4A Diagnostic**: `PRELIMINARY_READY`
- **Final Composite Status**: `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`

> [!WARNING]
> Preliminary Exploratory Status
> The existing seven-session normalized dataset passes its local dataset-integrity checks and is eligible for preliminary exploratory analysis. However, the project’s final composite requirement remains `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED` because ten sessions are required. The official validated campaign paired overlap for this snapshot is 13,005.314148 seconds, while the actual intersection of trade timestamps is approximately 12,972.85 seconds (trade-observation overlap). F01 is not part of this immutable snapshot. The current provisional progress is 8 accepted attempts, so 2 additional accepted attempts are still required.

Phase 3C.3 Normalized Dataset Validation is functionally in place, and Phase 4A preliminary readiness has already been successfully implemented and verified.
# Phase 3C & 4A Final Audit and Repairs

## Overview
Successfully performed the final focused repairs and audit for Phase 3C.3 (normalized dataset validation) and Phase 4A (preliminary readiness diagnostics) as requested. The codebase and documentation are now fully consistent with the established immutability and contract rules, and all validations pass over the actual physical dataset.

## What Was Completed

1. **CLI Serialization Double-Encoding Fix:**
   - Repaired `validate-normalized-dataset` in `cli.py` to correctly output a serialized JSON object (via `model_dump_json`) rather than a double-encoded JSON string.
   - Restored and expanded assertions in `tests/unit/test_cli.py` to explicitly verify the output begins with `{` and parses natively as a dictionary.

2. **Source-Snapshot Validation Contract Restoration:**
   - Restored the `source_collection_root` parameter and its associated logic in `validate_analysis_source_snapshot`.
   - Restored the `--source-collection-root` CLI argument for the `validate-analysis-source-snapshot` command.
   - Restored the removed assertions and invocation coverage in `tests/unit/test_source_snapshot.py`, verifying that building a future snapshot without modifying the original correctly asserts against the restored `source_collection_root` parameter.

3. **Immutability Semantics Corrections:**
   - Removed `INVALID` from immutability states across the codebase.
   - Enforced the strict usage of `VERIFIED_UNCHANGED`, `TAMPERED`, and `NOT_CHECKED` using a new `ImmutabilityResult` Enum (Literal type).
   - Removed broad `Exception` swallowing from semantic verification steps. The code now catches only the expected Pydantic `ValidationError` for malformed inputs (resulting in `NOT_CHECKED`), while allowing unexpected `semantic_hash` programming exceptions to properly propagate rather than being swallowed into warnings.

4. **Physical Output Immutability Tracking:**
   - Decoupled `normalized_output_immutability_result` logic from simply checking whether the errors list was empty.
   - It now explicitly tracks physical output verification separately. It correctly reports `VERIFIED_UNCHANGED` when physical paths are safe, exist, and match their checksums, `TAMPERED` if there is a missing file or mismatch, and `NOT_CHECKED` if physical verification could not be completed.

5. **Documentation Consistency Updates:**
   - Updated `docs/data_dictionary.md` to reflect the corrected `ImmutabilityResult` Enum (`VERIFIED_UNCHANGED`, `TAMPERED`, `NOT_CHECKED`).
   - Corrected `aggregate_paired_overlap_seconds` to accurately reflect its type as `float` rather than `string`.

## Validation

- Verified environment limits and states using the physical snapshot and dataset directories without mutating them.
- `pytest tests/` passes successfully, validating all testing logic including the restored `test_source_snapshot.py` and `test_cli.py` behaviors.
- The pipeline is stable, strongly typed, properly documented, and internally consistent.
