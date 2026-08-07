# Phase 03c3: Normalized Dataset Validation Report

**Date:** 2026-08-05
**Dataset Identifier:** `normalized-analysis-snapshot-7-session-v1-5f796ab67a5c801c-b13bc5307c07`
**Source Snapshot Identifier:** `analysis-snapshot-7-session-v1-5f796ab67a5c801c`
**Status:** VALID
**Preliminary Analysis Eligibility:** ELIGIBLE
**Final Composite Status:** FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED

---

## Verified Dataset Status

The immutable normalized dataset contains 7 accepted campaign attempts and 14 venue sessions.

The Phase 3C.3 validator confirmed:

- Aggregate disposition: `VALID`
- Preliminary analysis eligibility: `ELIGIBLE`
- Final composite status: `FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED`
- Source catalog immutability: `VERIFIED_UNCHANGED`
- Source snapshot immutability: `VERIFIED_UNCHANGED`
- Normalized output immutability: `VERIFIED_UNCHANGED`
- Validation errors: none
- Validation warnings: none

The official validated campaign paired overlap represented by this snapshot is
13,005.314148 seconds.

The snapshot remains below the final composite requirements of 10 accepted
attempts and 18,000 seconds of validated paired overlap.

The accepted follow-up F01 attempt is not part of this immutable seven-session
snapshot. Current collection progress is provisionally 8 accepted attempts,
leaving 2 additional accepted attempts required for the future composite.

## 2. Code-Identity Reconciliation
A minor divergence in code identity was investigated between the normalization artifact code identity (`e534e672c074fa12e0a19b85f9797adb535e97a1`) and the final pushed Phase 2 commit (`8530d7525b65f7c8cb57656d0244981ae1b65e95`).
- The divergence consisted strictly of documentation changes (`docs/audits/phase_03c2_snapshot_normalization_report.md`).
- No normalization logic, configuration, schema, or executable pipeline code was modified.
- The `normalize-analysis-snapshot` deterministic command accurately reproduced the exact dataset hashes under the original code identity.
**Disposition:** The existing normalized dataset artifact is formally verified, fully reproducible, and rigorously preserved.

## 3. Immutability and Determinism
- **Source Catalog Hash:** `2c0ace336c01d87073cabca77170c0c16b78913076f15652464f4e6942d741e4` (VERIFIED UNCHANGED)
- **Dataset Manifest Hash:** `a93eae1017c684bf206d5a321bcd248f1d6104a907d3ec7b1c2d638af4bc8acd` (VERIFIED UNCHANGED)
- **Validation Report Hash:** `validation-report-d321166185eba618` (STABLE)

The validation layer generated `normalized_dataset_validation.json` deterministically, yielding stable identification of the validation attempt.

## 4. Lineage and Exclusions
- **Accepted Attempts Count:** 7
- **Venue-Session Count:** 14 (7 Coinbase, 7 Kraken)
- **Intraday Overlap Integrity:** No duplicate source mappings exist; attempts map 1:1 to required slots.

## 5. Dataset Metrics & Integrity Checks
Row counts, constraints, and semantics were thoroughly tested across all files.

### Trade Validation
- **Coinbase Trades:** 90,515
- **Kraken Trades:** 9,051
- **Numeric Checks:** Prices and quantities > 0.
- **Duplicate normalized events:** 0
- **Missing Exchange Timestamps:** 0

### BBO (Best-Bid-and-Offer) Validation
- **Coinbase Quotes:** 90,512
- **Kraken Quotes:** 137,035
- **Numeric Checks:** Bid prices and Ask prices > 0.
- **Market State:** Locked (0), Crossed (0)

## 6. Real Dataset Results & Performance
The validation executed natively on the actual data using PyArrow and successfully generated the validation artifacts (`session_validation.parquet`, `field_summary.parquet`, `reconciliation_summary.parquet`) in the `validation/` directory.

- **Aggregate Disposition:** VALID
- **Preliminary Analysis:** ELIGIBLE
- **Final Analysis:** FINAL_COMPOSITE_REQUIREMENTS_UNSATISFIED

## Idempotency Verification

Phase 3C.3 idempotency was verified by executing the real validation command
twice against unchanged inputs.

The following values remained unchanged:

- Validation report SHA-256
- Validation report modification time
- Validation report ID
- Validation timestamp

Result: `PHASE_3C3_IDEMPOTENCY_VERIFIED: True`
