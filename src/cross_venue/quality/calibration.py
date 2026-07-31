"""Policy-calibrated paired reanalysis and before/after comparison."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cross_venue.config import DataQualityConfig, StorageConfig
from cross_venue.quality.analyzer import analyze_session_quality
from cross_venue.quality.exceptions import QualityError
from cross_venue.quality.io import current_git_commit, persist_model_json, utc_now
from cross_venue.quality.models import PairedQualityReport, QualityFinding, SessionQualityReport
from cross_venue.quality.overlap import build_paired_quality_report
from cross_venue.quality.promotion import promote_dataset
from cross_venue.storage.checksum import sha256_file
from cross_venue.storage.manifest_store import atomic_write_json
from cross_venue.storage.paths import resolve_under_root


@dataclass(frozen=True, slots=True)
class CalibratedReanalysisResult:
    """Output paths from a calibrated paired reanalysis."""

    output_root: Path
    coinbase_report_path: Path
    kraken_report_path: Path
    paired_report_path: Path
    comparison_json_path: Path
    comparison_markdown_path: Path
    promotion_dry_run_path: Path
    paired_report: PairedQualityReport
    comparison: dict[str, Any]

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Output root: {self.output_root}",
                f"Coinbase disposition: {self.paired_report.coinbase_report.disposition.value}",
                f"Kraken disposition: {self.paired_report.kraken_report.disposition.value}",
                f"Paired disposition: {self.paired_report.disposition.value}",
                f"Before/after: {self.comparison_json_path}",
            ]
        )


def reanalyze_calibrated_pair(
    paired_report_path: Path,
    *,
    storage_config: StorageConfig,
    quality_config: DataQualityConfig,
    require_clean: bool = True,
    expected_commit: str | None = None,
) -> CalibratedReanalysisResult:
    """Reanalyze an existing paired collection under the active calibrated policy."""

    lineage = _analysis_lineage(
        quality_config=quality_config,
        paired_report_path=paired_report_path,
        require_clean=require_clean,
        expected_commit=expected_commit,
    )
    source_path = resolve_under_root(quality_config.report_root, paired_report_path)
    original = PairedQualityReport.model_validate_json(source_path.read_text(encoding="utf-8"))
    output_root = (
        quality_config.report_root
        / "calibrated"
        / f"policy={quality_config.policy_version}"
        / original.paired_collection_id
    )
    coinbase_path = output_root / "coinbase_quality_report.json"
    kraken_path = output_root / "kraken_quality_report.json"
    paired_path = output_root / "paired_quality_report.json"
    coinbase = analyze_session_quality(
        storage_config.archive_root / original.coinbase_report.source_session_relative_path,
        storage_config=storage_config,
        quality_config=quality_config,
        report_path=coinbase_path,
    )
    kraken = analyze_session_quality(
        storage_config.archive_root / original.kraken_report.source_session_relative_path,
        storage_config=storage_config,
        quality_config=quality_config,
        report_path=kraken_path,
    )
    _verify_source_lineage(original, coinbase, kraken)
    paired = build_paired_quality_report(
        paired_collection_id=original.paired_collection_id,
        requested_duration_seconds=original.overlap.requested_duration_seconds,
        start_skew_seconds=original.overlap.start_skew_seconds,
        coinbase_report=coinbase,
        kraken_report=kraken,
        quality_config=quality_config,
    )
    persist_model_json(coinbase_path, coinbase)
    persist_model_json(kraken_path, kraken)
    persist_model_json(paired_path, paired)
    comparison = _comparison_payload(original, paired, lineage)
    comparison_json = output_root / "before_after_comparison.json"
    comparison_md = output_root / "before_after_comparison.md"
    promotion_path = output_root / "promotion_dry_run.json"
    atomic_write_json(comparison_json, comparison)
    comparison_md.parent.mkdir(parents=True, exist_ok=True)
    comparison_md.write_text(_comparison_markdown(comparison), encoding="utf-8")
    atomic_write_json(promotion_path, _promotion_dry_run(paired, quality_config))
    return CalibratedReanalysisResult(
        output_root=output_root,
        coinbase_report_path=coinbase_path,
        kraken_report_path=kraken_path,
        paired_report_path=paired_path,
        comparison_json_path=comparison_json,
        comparison_markdown_path=comparison_md,
        promotion_dry_run_path=promotion_path,
        paired_report=paired,
        comparison=comparison,
    )


def _analysis_lineage(
    *,
    quality_config: DataQualityConfig,
    paired_report_path: Path,
    require_clean: bool,
    expected_commit: str | None,
) -> dict[str, Any]:
    commit = current_git_commit()
    clean = _working_tree_clean()
    if require_clean and not clean:
        raise QualityError("calibrated final report requires a clean working tree")
    if expected_commit is not None and commit != expected_commit:
        raise QualityError(f"expected commit {expected_commit}, found {commit}")
    source_path = resolve_under_root(quality_config.report_root, paired_report_path)
    return {
        "analysis_code_git_commit": commit,
        "analysis_working_tree_clean": clean,
        "quality_policy_version": quality_config.policy_version,
        "quality_policy_sha256": sha256_file(Path("configs/data_quality.toml")),
        "report_schema_version": "0.1.0",
        "source_paired_report_sha256": sha256_file(source_path),
        "analysis_started_at": utc_now().isoformat(),
    }


def _working_tree_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == ""


def _verify_source_lineage(
    original: PairedQualityReport,
    coinbase: SessionQualityReport,
    kraken: SessionQualityReport,
) -> None:
    pairs = (
        (original.coinbase_report, coinbase),
        (original.kraken_report, kraken),
    )
    for original_report, current_report in pairs:
        if original_report.source_manifest_sha256 != current_report.source_manifest_sha256:
            raise QualityError(f"source manifest changed for {original_report.session_id}")
        if original_report.input_shard_checksums != current_report.input_shard_checksums:
            raise QualityError(f"source shard checksum changed for {original_report.session_id}")


def _comparison_payload(
    original: PairedQualityReport,
    calibrated: PairedQualityReport,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for venue, old_report, new_report in (
        ("coinbase", original.coinbase_report, calibrated.coinbase_report),
        ("kraken", original.kraken_report, calibrated.kraken_report),
    ):
        for finding in old_report.findings:
            rows.append(
                _comparison_row(venue, finding, new_report.findings, old_report, new_report)
            )
    for finding in original.findings:
        rows.append(_comparison_row("pair", finding, calibrated.findings, original, calibrated))
    completed = lineage | {"analysis_completed_at": utc_now().isoformat()}
    return {
        **completed,
        "paired_collection_id": original.paired_collection_id,
        "old_policy_version": original.quality_policy_version,
        "new_policy_version": calibrated.quality_policy_version,
        "old_disposition": original.disposition.value,
        "new_disposition": calibrated.disposition.value,
        "original_findings_preserved": True,
        "findings": rows,
    }


def _comparison_row(
    venue: str,
    old: QualityFinding,
    new_findings: tuple[QualityFinding, ...],
    old_report: Any,
    new_report: Any,
) -> dict[str, Any]:
    replacement = _replacement_finding(old, new_findings)
    return {
        "finding_id": old.finding_id,
        "venue": venue,
        "old_category": old.category,
        "old_severity": old.severity.value,
        "old_observed_value": old.observed_value,
        "old_threshold": old.threshold,
        "new_category": replacement.category if replacement else old.category,
        "new_severity": replacement.severity.value if replacement else "INFO",
        "new_observed_value": replacement.observed_value if replacement else old.observed_value,
        "new_threshold": replacement.threshold if replacement else old.threshold,
        "record_evidence": old.evidence,
        "semantic_reason": _semantic_reason(old.finding_id, replacement),
        "official_source_reference": _official_source(old.finding_id, venue),
        "old_disposition": old_report.disposition.value,
        "new_disposition": new_report.disposition.value,
        "underlying_observation_still_exists": replacement is not None,
        "change_type": "semantic" if replacement else "severity_or_grouping",
    }


def _replacement_finding(
    old: QualityFinding,
    candidates: tuple[QualityFinding, ...],
) -> QualityFinding | None:
    category_matches = [item for item in candidates if item.category == old.category]
    if old.finding_id.startswith("TIMESTAMP_NEGATIVE"):
        return next((item for item in candidates if "DELTA_PATTERN" in item.finding_id), None)
    if old.finding_id == "CONTINUITY_IDENTIFIER_ANOMALY":
        return next((item for item in candidates if item.category == "continuity"), None)
    if old.finding_id == "DUPLICATES_RAW_FRAME_RATE":
        return next((item for item in candidates if item.category == "duplicates"), None)
    if old.finding_id == "QUOTES_STALE_INTERVALS":
        return next((item for item in candidates if item.category == "quotes"), None)
    return category_matches[0] if category_matches else None


def _semantic_reason(finding_id: str, replacement: QualityFinding | None) -> str:
    if replacement is None:
        return (
            "Original observation is preserved in calibrated metrics but no longer "
            "disposition-gating."
        )
    if "DELTA" in finding_id:
        return "Negative exchange-receipt deltas are classified by offset pattern, not latency."
    if finding_id == "CONTINUITY_IDENTIFIER_ANOMALY":
        return (
            "Partial-subscription Coinbase sequence jumps are diagnostic absent stronger "
            "trade loss evidence."
        )
    if finding_id == "DUPLICATES_RAW_FRAME_RATE":
        return "Raw duplicates are split by control, ticker, and trade semantics."
    if finding_id == "QUOTES_STALE_INTERVALS":
        return "Quote age is separated from connection inactivity and documented feed behavior."
    return "Calibrated policy preserves the observation with evidence-based severity."


def _official_source(finding_id: str, venue: str) -> str:
    if venue == "coinbase" or "CONTINUITY" in finding_id:
        return "https://docs.cdp.coinbase.com/exchange/websocket-feed/channels"
    if venue == "kraken":
        return "https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker"
    return "repository quality policy 2d.2"


def _comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Before/After Quality Comparison",
        "",
        f"Paired collection: `{comparison['paired_collection_id']}`",
        f"Old disposition: `{comparison['old_disposition']}`",
        f"New disposition: `{comparison['new_disposition']}`",
        "",
        "| Finding | Venue | Old severity | New severity | Semantic reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in comparison["findings"]:
        lines.append(
            "| {finding_id} | {venue} | {old_severity} | {new_severity} | {reason} |".format(
                finding_id=row["finding_id"],
                venue=row["venue"],
                old_severity=row["old_severity"],
                new_severity=row["new_severity"],
                reason=row["semantic_reason"],
            )
        )
    return "\n".join(lines) + "\n"


def _promotion_dry_run(
    paired_report: PairedQualityReport,
    quality_config: DataQualityConfig,
) -> dict[str, Any]:
    try:
        manifest, message = promote_dataset(
            paired_report, quality_config=quality_config, apply=False
        )
    except Exception as exc:
        return {"allowed": False, "message": str(exc)}
    return {
        "allowed": manifest is not None,
        "message": message,
        "dataset_manifest_id": manifest.dataset_manifest_id if manifest else None,
    }
