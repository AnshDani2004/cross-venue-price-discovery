import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from pydantic import BaseModel

from cross_venue.research.exceptions import ResearchError

logger = logging.getLogger(__name__)


class ReportingManifest(BaseModel):
    reporting_id: str
    reporting_schema_version: str = "v1"
    source_analysis_result_id: str
    source_config_hash: str
    analysis_mode: str
    final_inference_permitted: bool
    source_snapshot_id: str
    dataset_validation_id: str
    ordered_attempt_ids: list[str]
    generated_tables: list[str]
    generated_figures: list[str]
    generated_report: str
    file_hashes: dict[str, str]
    deterministic_content_hash: str


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _hash_dict(data: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(data, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _extract_session_date(attempt_id: str) -> str | None:
    parts = attempt_id.split("-")

    for idx in range(len(parts) - 2):
        year, month, day = parts[idx : idx + 3]

        if (
            len(year) == 4
            and year.isdigit()
            and len(month) == 2
            and month.isdigit()
            and len(day) == 2
            and day.isdigit()
        ):
            month_i = int(month)
            day_i = int(day)

            if 1 <= month_i <= 12 and 1 <= day_i <= 31:
                return f"{year}-{month}-{day}"

    return None


def render_econometric_results(econometric_output_root: Path, output_root: Path) -> None:
    if not econometric_output_root.exists():
        raise ResearchError(f"Missing source root: {econometric_output_root}")

    manifest_path = econometric_output_root / "output_manifest.json"
    if not manifest_path.exists():
        raise ResearchError("Missing output_manifest.json")

    manifest = json.loads(manifest_path.read_text())

    if not isinstance(manifest, list):
        raise ResearchError("Source output manifest must be a list")

    manifest_paths = {
        str(entry.get("relative_path")) for entry in manifest if isinstance(entry, dict)
    }

    required_source_artifacts = {
        "cointegration_diagnostics.parquet",
        "price_discovery_metrics.parquet",
        "granger_causality.parquet",
        "impulse_responses.parquet",
        "robustness_results.parquet",
        "var_model_diagnostics.parquet",
        "predictive_regressions.parquet",
        "aggregate_inference.parquet",
        "econometric_price_discovery_report.json",
    }

    missing_from_manifest = sorted(required_source_artifacts - manifest_paths)
    if missing_from_manifest:
        raise ResearchError(
            "Source manifest missing required artifacts: " + ", ".join(missing_from_manifest)
        )

    # Verify every manifest-bound artifact before reading it.
    for entry in manifest:
        if not isinstance(entry, dict):
            raise ResearchError("Invalid source manifest entry")

        rel = entry.get("relative_path")
        expected_hash = entry.get("sha256")

        if not isinstance(rel, str):
            raise ResearchError("Source manifest entry missing relative_path")
        if not isinstance(expected_hash, str):
            raise ResearchError(f"Source manifest entry missing sha256: {rel}")

        if rel != "output_manifest.json":
            phys = econometric_output_root / rel
            if not phys.exists():
                raise ResearchError(f"Missing required artifact: {rel}")
            if _hash_file(phys) != expected_hash:
                raise ResearchError(f"Corrupt artifact hash: {rel}")

    report_path = econometric_output_root / "econometric_price_discovery_report.json"
    if not report_path.exists():
        raise ResearchError("Missing econometric_price_discovery_report.json")

    source_report = json.loads(report_path.read_text())

    source_analysis_mode = source_report.get(
        "analysis_mode",
        "DEVELOPMENT",
    )
    source_final_inference = source_report.get(
        "final_inference_permitted",
        False,
    )

    if source_analysis_mode == "FINAL" and source_final_inference is not True:
        raise ResearchError("Source report is FINAL but final inference is not permitted")

    if source_analysis_mode != "FINAL" and source_final_inference is True:
        raise ResearchError("Source report permits final inference outside FINAL mode")

    tables_dir = output_root / "tables"
    figures_dir = output_root / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    try:
        coint_df = pl.read_parquet(econometric_output_root / "cointegration_diagnostics.parquet")
        pd_df = pl.read_parquet(econometric_output_root / "price_discovery_metrics.parquet")
        granger_df = pl.read_parquet(econometric_output_root / "granger_causality.parquet")
        irf_df = pl.read_parquet(econometric_output_root / "impulse_responses.parquet")
        rob_df = pl.read_parquet(econometric_output_root / "robustness_results.parquet")
        var_df = pl.read_parquet(econometric_output_root / "var_model_diagnostics.parquet")

        pred_df = pl.read_parquet(econometric_output_root / "predictive_regressions.parquet")
        aggregate_inference_df = pl.read_parquet(
            econometric_output_root / "aggregate_inference.parquet"
        )

        raw_attempt_ids = coint_df["campaign_attempt_id"].to_list()

        if len(raw_attempt_ids) != len(set(raw_attempt_ids)):
            raise ResearchError("Duplicate semantic identities detected in attempt IDs")

        attempt_ids = sorted(raw_attempt_ids)
    except ResearchError:
        raise
    except Exception as exc:
        raise ResearchError(f"Failed to read Parquet artifacts: {exc}") from exc

    summary_rows = []
    for att in attempt_ids:

        def _get_var_lag(att: str = att) -> int | None:
            rows = var_df.filter(pl.col("campaign_attempt_id") == att)
            return (
                int(rows["selected_lag"][0])
                if rows.height > 0 and rows["selected_lag"][0] is not None
                else None
            )

        def _get_var_status(att: str = att) -> str:
            rows = var_df.filter(pl.col("campaign_attempt_id") == att)
            if rows.height == 0:
                return "MISSING"
            st = rows["fit_status"][0]
            if st != "COMPUTED":
                return str(st)
            return "STABLE" if rows["is_stable"][0] else "UNSTABLE"

        def _get_granger(
            direction: str,
            att: str = att,
        ) -> tuple[
            float | None,
            float | None,
            float | None,
            str,
        ]:
            rows = granger_df.filter(
                (pl.col("campaign_attempt_id") == att) & (pl.col("direction") == direction)
            )
            if rows.height == 0:
                return None, None, None, "MISSING"
            row = rows.to_dicts()[0]
            if (
                not math.isfinite(row.get("test_statistic", float("nan")))
                and row.get("model_validity_status") == "COMPUTED"
            ):
                raise ResearchError(f"NaN found in valid Granger row for {att} {direction}")
            return (
                row.get("test_statistic"),
                row.get("raw_p_value"),
                row.get("adjusted_p_value"),
                str(row.get("decision")),
            )

        def _get_coint(att: str = att) -> tuple[int | None, str]:
            rows = coint_df.filter(pl.col("campaign_attempt_id") == att)
            if rows.height == 0:
                return None, "MISSING"
            return rows["inferred_cointegration_rank"][0], rows["vecm_status"][0]

        def _get_pd(
            metric: str,
            att: str = att,
        ) -> tuple[
            float | None, float | None, float | None, float | None, float | None, float | None, str
        ]:
            rows = pd_df.filter(
                (pl.col("campaign_attempt_id") == att) & (pl.col("metric") == metric)
            )
            if rows.height == 0:
                return None, None, None, None, None, None, "MISSING"
            row = rows.to_dicts()[0]

            st = row.get("status")
            if st == "COMPUTED":
                if metric == "GONZALO_GRANGER_COMPONENT_SHARE":
                    if not math.isfinite(
                        row.get("coinbase_value", float("nan"))
                    ) or not math.isfinite(row.get("kraken_value", float("nan"))):
                        raise ResearchError(f"NaN found in valid PD row for {att}")
                elif metric == "HASBROUCK_INFORMATION_SHARE" and (
                    not math.isfinite(row.get("coinbase_lower", float("nan")))
                    or not math.isfinite(row.get("kraken_upper", float("nan")))
                ):
                    raise ResearchError(f"NaN found in valid PD bounds row for {att}")

            return (
                row.get("coinbase_value"),
                row.get("kraken_value"),
                row.get("coinbase_lower"),
                row.get("coinbase_upper"),
                row.get("kraken_lower"),
                row.get("kraken_upper"),
                str(st),
            )

        def _get_pred(
            direction: str,
            att: str = att,
        ) -> tuple[float | None, float | None, str]:
            # Safe extraction for predictive regression per direction
            if "direction" not in pred_df.columns:
                return None, None, "MISSING"
            rows = pred_df.filter(
                (pl.col("campaign_attempt_id") == att) & (pl.col("direction") == direction)
            )
            if rows.height == 0:
                return None, None, "MISSING"
            row = rows.to_dicts()[0]
            st = row.get("fit_status", row.get("status", "MISSING"))
            if st == "COMPUTED":
                c = row.get("coefficient", float("nan"))
                p = row.get("raw_p_value", row.get("p_value", float("nan")))
                if not math.isfinite(c) or not math.isfinite(p):
                    raise ResearchError(
                        f"NaN found in valid predictive regression for {att} {direction}"
                    )
                return c, p, st
            return None, None, st

        cb_kr_stat, cb_kr_raw_p, cb_kr_adj_p, cb_kr_dec = _get_granger("coinbase_predicts_kraken")
        kr_cb_stat, kr_cb_raw_p, kr_cb_adj_p, kr_cb_dec = _get_granger("kraken_predicts_coinbase")
        coint_rank, coint_stat = _get_coint()

        gg_cb, gg_kr, _, _, _, _, gg_st = _get_pd("GONZALO_GRANGER_COMPONENT_SHARE")
        _, _, hasb_cb_l, hasb_cb_u, hasb_kr_l, hasb_kr_u, hasb_st = _get_pd(
            "HASBROUCK_INFORMATION_SHARE"
        )

        kr_pred_cb_coeff, kr_pred_cb_p, kr_pred_cb_st = _get_pred("kraken_predicts_coinbase")
        cb_pred_kr_coeff, cb_pred_kr_p, cb_pred_kr_st = _get_pred("coinbase_predicts_kraken")

        summary_rows.append(
            {
                "campaign_attempt_id": att,
                "session_date": _extract_session_date(att),
                "var_selected_lag": _get_var_lag(),
                "var_status": _get_var_status(),
                "cb_kr_granger_stat": cb_kr_stat,
                "cb_kr_granger_raw_p": cb_kr_raw_p,
                "cb_kr_granger_adj_p": cb_kr_adj_p,
                "cb_kr_granger_decision": cb_kr_dec,
                "kr_cb_granger_stat": kr_cb_stat,
                "kr_cb_granger_raw_p": kr_cb_raw_p,
                "kr_cb_granger_adj_p": kr_cb_adj_p,
                "kr_cb_granger_decision": kr_cb_dec,
                "cointegration_rank": coint_rank,
                "cointegration_status": coint_stat,
                "gg_coinbase_share": gg_cb,
                "gg_kraken_share": gg_kr,
                "gg_status": gg_st,
                "hasbrouck_cb_lower": hasb_cb_l,
                "hasbrouck_cb_upper": hasb_cb_u,
                "hasbrouck_kr_lower": hasb_kr_l,
                "hasbrouck_kr_upper": hasb_kr_u,
                "hasbrouck_status": hasb_st,
                "kr_pred_cb_coeff": kr_pred_cb_coeff,
                "kr_pred_cb_p": kr_pred_cb_p,
                "kr_pred_cb_status": kr_pred_cb_st,
                "cb_pred_kr_coeff": cb_pred_kr_coeff,
                "cb_pred_kr_p": cb_pred_kr_p,
                "cb_pred_kr_status": cb_pred_kr_st,
            }
        )

    summary_df = pl.DataFrame(summary_rows)
    summary_df.write_parquet(tables_dir / "attempt_summary.parquet")

    with (tables_dir / "attempt_summary.md").open("w") as f:

        def _fmt(val: Any) -> str:
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return "N/A"
            if isinstance(val, float):
                return f"{val:.4g}"
            return str(val)

        headers = list(summary_rows[0].keys())
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("|" + "|".join(["---"] * len(headers)) + "|\n")
        for row in summary_rows:
            f.write("| " + " | ".join([_fmt(row[k]) for k in headers]) + " |\n")

    # Figure 1: Granger Causality
    _render_granger_figure(summary_df, figures_dir / "granger_directional_predictability.png")

    # Figure 2: Impulse Responses (FIXED to preserve attempt identity and ordering)
    _render_irf_figure(irf_df, figures_dir / "impulse_responses.png")

    # Figure 3: Price Discovery
    _render_pd_figure(summary_df, figures_dir / "price_discovery_by_attempt.png")

    # Figure 4: Robustness (FIXED to show explicit metric values)
    _render_robustness_figure(rob_df, figures_dir / "robustness_summary.png")

    coint_df.write_parquet(tables_dir / "cointegration_results.parquet")
    granger_df.write_parquet(tables_dir / "granger_results.parquet")
    pd_df.write_parquet(tables_dir / "price_discovery_results.parquet")
    pred_df.write_parquet(tables_dir / "predictive_regressions.parquet")
    rob_df.write_parquet(tables_dir / "robustness_results.parquet")
    aggregate_inference_df.write_parquet(tables_dir / "aggregate_inference.parquet")

    _generate_markdown_report(
        output_root / "econometric_results_report.md",
        source_report,
        attempt_ids,
        aggregate_inference_df,
    )

    generated_tables = sorted(f.name for f in tables_dir.iterdir() if f.is_file())
    generated_figures = sorted(f.name for f in figures_dir.iterdir() if f.is_file())

    file_hashes: dict[str, str] = {}
    for t in generated_tables:
        file_hashes[f"tables/{t}"] = _hash_file(tables_dir / t)
    for fig_name in generated_figures:
        file_hashes[f"figures/{fig_name}"] = _hash_file(figures_dir / fig_name)
    file_hashes["econometric_results_report.md"] = _hash_file(
        output_root / "econometric_results_report.md"
    )

    manifest = ReportingManifest(
        reporting_id="report-"
        + hashlib.sha256(json.dumps(file_hashes, sort_keys=True).encode()).hexdigest()[:16],
        source_analysis_result_id=source_report["analysis_result_id"],
        source_config_hash=source_report["config_hash"],
        analysis_mode=source_report["analysis_mode"],
        final_inference_permitted=source_report["final_inference_permitted"],
        source_snapshot_id=source_report["dataset_snapshot_id"],
        dataset_validation_id=source_report["dataset_validation_id"],
        ordered_attempt_ids=attempt_ids,
        generated_tables=[f"tables/{t}" for t in generated_tables],
        generated_figures=[f"figures/{f}" for f in generated_figures],
        generated_report="econometric_results_report.md",
        file_hashes=file_hashes,
        deterministic_content_hash=_hash_dict(file_hashes),
    )

    manifest_out = output_root / "reporting_manifest.json"
    manifest_out.write_text(json.dumps(manifest.model_dump(), indent=2) + "\n")


def _render_granger_figure(summary_df: pl.DataFrame, out_path: Path) -> None:
    plt.figure(figsize=(10, 6))
    attempts = summary_df["campaign_attempt_id"].to_list()
    cb_kr_p = summary_df["cb_kr_granger_adj_p"].to_list()
    kr_cb_p = summary_df["kr_cb_granger_adj_p"].to_list()

    y_pos = np.arange(len(attempts))

    plt.scatter(
        [-np.log10(p) if p is not None else 0 for p in cb_kr_p],
        y_pos + 0.1,
        label="Coinbase -> Kraken",
        alpha=0.7,
    )
    plt.scatter(
        [-np.log10(p) if p is not None else 0 for p in kr_cb_p],
        y_pos - 0.1,
        label="Kraken -> Coinbase",
        alpha=0.7,
    )

    plt.axvline(-np.log10(0.05), color="red", linestyle="--", label="Alpha 0.05")
    plt.yticks(y_pos, [a.split("-")[-2] + "-" + a.split("-")[-1] for a in attempts], fontsize=8)
    plt.xlabel("-log10(FDR Adjusted p-value)")
    plt.title("Directional Predictability (Granger Causality)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def _render_irf_figure(irf_df: pl.DataFrame, out_path: Path) -> None:
    """Render Coinbase-shock-to-Kraken IRFs under both Cholesky orderings."""
    valid = irf_df.filter(
        (pl.col("model_status") == "COMPUTED")
        & (pl.col("shock_venue") == "coinbase")
        & (pl.col("response_venue") == "kraken")
    )

    if valid.height == 0:
        plt.figure(figsize=(8, 4))
        plt.text(
            0.5,
            0.5,
            "No computed Coinbase-to-Kraken IRF results",
            ha="center",
            va="center",
        )
        plt.tight_layout()
        plt.savefig(out_path)
        plt.close()
        return

    attempts = sorted(set(valid["campaign_attempt_id"].to_list()))
    orderings = sorted(set(valid["ordering"].to_list()))

    fig, axes = plt.subplots(
        1,
        len(orderings),
        figsize=(7 * len(orderings), 6),
        squeeze=False,
    )

    for col_idx, ordering in enumerate(orderings):
        ax = axes[0, col_idx]

        subset = valid.filter(pl.col("ordering") == ordering)

        for att in attempts:
            att_sub = subset.filter(pl.col("campaign_attempt_id") == att).sort("horizon")

            if att_sub.height == 0:
                continue

            short_att = "-".join(att.split("-")[-3:]) if len(att.split("-")) >= 3 else att

            ax.plot(
                att_sub["horizon"],
                att_sub["cumulative_response"],
                label=short_att,
                linewidth=1,
                alpha=0.7,
            )

        ax.set_title(f"Coinbase shock -> Kraken response (ordering: {ordering})")
        ax.set_xlabel("Horizon")
        ax.set_ylabel("Cumulative response")

    axes[0, -1].legend(
        bbox_to_anchor=(1.05, 1),
        loc="upper left",
        fontsize=8,
    )

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _render_pd_figure(summary_df: pl.DataFrame, out_path: Path) -> None:
    plt.figure(figsize=(10, 6))
    attempts = summary_df["campaign_attempt_id"].to_list()
    y_pos = np.arange(len(attempts))

    gg_cb = summary_df["gg_coinbase_share"].to_list()
    hasb_cb_l = summary_df["hasbrouck_cb_lower"].to_list()
    hasb_cb_u = summary_df["hasbrouck_cb_upper"].to_list()

    for i, (g, hl, hu) in enumerate(zip(gg_cb, hasb_cb_l, hasb_cb_u, strict=False)):
        if g is not None:
            plt.plot(g, i, "bo", label="Gonzalo-Granger" if i == 0 else "")
        if hl is not None and hu is not None:
            plt.plot(
                [hl, hu], [i, i], "r-", linewidth=2, label="Hasbrouck Bounds" if i == 0 else ""
            )

    plt.axvline(0.5, color="gray", linestyle="--", label="Equal Share")
    plt.yticks(y_pos, [a.split("-")[-2] + "-" + a.split("-")[-1] for a in attempts], fontsize=8)
    plt.xlabel("Coinbase price-discovery weight / information-share bound")
    plt.title("Price Discovery Estimates by Attempt")

    handles, labels = plt.gca().get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    plt.legend(by_label.values(), by_label.keys())

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def _render_robustness_figure(
    rob_df: pl.DataFrame,
    out_path: Path,
) -> None:
    """Render per-attempt VAR-stability robustness results."""
    valid = rob_df.filter((pl.col("status") == "COMPUTED") & (pl.col("scope") == "per_attempt"))

    if valid.height == 0:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(
            0.5,
            0.5,
            "No estimable robustness results",
            ha="center",
            va="center",
        )
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return

    cfgs = sorted(set(valid["configuration_id"].to_list()))
    metrics = sorted(set(valid["metric"].to_list()))

    if not metrics:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(
            0.5,
            0.5,
            "No estimable robustness results",
            ha="center",
            va="center",
        )
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return

    fig, axes = plt.subplots(
        len(metrics),
        1,
        figsize=(12, 4 * len(metrics)),
        squeeze=False,
    )

    for metric_idx, metric in enumerate(metrics):
        ax = axes[metric_idx, 0]
        metric_rows = valid.filter(pl.col("metric") == metric)

        for config_idx, config_id in enumerate(cfgs):
            config_rows = metric_rows.filter(pl.col("configuration_id") == config_id)
            values = config_rows["value"].to_list()

            if values:
                ax.scatter(
                    [config_idx] * len(values),
                    values,
                    alpha=0.7,
                )

        ax.set_xticks(np.arange(len(cfgs)))
        ax.set_xticklabels(
            cfgs,
            rotation=45,
            ha="right",
        )
        ax.set_ylabel(metric)
        ax.set_title(f"VAR Stability Robustness: {metric}")

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _generate_markdown_report(
    out_path: Path,
    source_report: dict[str, Any],
    attempt_ids: list[str],
    aggregate_inference_df: pl.DataFrame,
) -> None:
    """Render a deterministic report without overstating statistical evidence."""
    is_dev = source_report.get("analysis_mode", "DEVELOPMENT") != "FINAL"

    def _aggregate_row(
        analysis: str,
        direction: str,
    ) -> dict[str, Any]:
        rows = aggregate_inference_df.filter(
            (pl.col("analysis") == analysis)
            & (pl.col("direction") == direction)
            & (pl.col("specification_id") == "baseline")
            & (pl.col("scope") == "aggregate")
        )

        if rows.height != 1:
            raise ResearchError(
                "Expected exactly one aggregate inference row for "
                f"{analysis} / {direction}; found {rows.height}"
            )

        row = rows.to_dicts()[0]

        if row.get("status") == "COMPUTED":
            p_value = row.get("combined_p_value")
            if (
                p_value is None
                or not math.isfinite(float(p_value))
                or not 0.0 <= float(p_value) <= 1.0
            ):
                raise ResearchError(f"Invalid aggregate p-value for {analysis} / {direction}")

        return row

    def _fmt_p(row: dict[str, Any]) -> str:
        if row.get("status") != "COMPUTED":
            return "N/A"

        p_value = row.get("combined_p_value")
        if p_value is None:
            return "N/A"

        return f"{float(p_value):.6g}"

    cb_kr_granger = _aggregate_row(
        "granger_causality",
        "coinbase_predicts_kraken",
    )
    kr_cb_granger = _aggregate_row(
        "granger_causality",
        "kraken_predicts_coinbase",
    )
    cb_kr_predictive = _aggregate_row(
        "predictive_regression",
        "coinbase_predicts_kraken",
    )
    kr_cb_predictive = _aggregate_row(
        "predictive_regression",
        "kraken_predicts_coinbase",
    )

    with Path(out_path).open("w") as f:
        f.write("# Econometric Results Report\n\n")

        if is_dev:
            f.write("> [!WARNING]\n")
            f.write("> DEVELOPMENT / PRELIMINARY RESULTS — FINAL INFERENCE NOT PERMITTED\n")
            f.write("> \n")
            f.write("> The dataset does not satisfy final composite requirements.\n")
            f.write("> This run validates the econometric analysis machinery only.\n")
            f.write(
                "> Final empirical, causal, VAR, Granger, or "
                "price-discovery conclusions are prohibited.\n\n"
            )

        f.write("## 1. Dataset and inference status\n\n")

        if is_dev:
            f.write(
                "The table outputs below are DEVELOPMENT results "
                "produced by the frozen Phase 4C specification. "
                "They are included for pipeline validation only.\n\n"
            )
        else:
            f.write(
                "The dataset satisfies final composite requirements "
                "and final inference is permitted.\n\n"
            )

        f.write(f"- Dataset Validation ID: `{source_report.get('dataset_validation_id')}`\n")
        f.write(f"- Source analysis result ID: `{source_report.get('analysis_result_id')}`\n")
        f.write(f"- Total accepted attempts: {source_report.get('total_attempt_count')}\n")
        f.write(f"- Econometrically usable attempts: {len(attempt_ids)}\n")
        f.write(
            "- Authoritative paired overlap, seconds: "
            f"{source_report.get('authoritative_paired_overlap_seconds')}\n"
        )
        f.write(
            "- Empirical paired overlap, seconds: "
            f"{source_report.get('empirical_paired_overlap_seconds')}\n\n"
        )

        f.write("## 2. Aggregate directional inference\n\n")

        f.write(
            "Aggregate inference uses Fisher combination of raw "
            "per-attempt p-values under the frozen Phase 4C policy. "
            "These statistics measure directional predictability, "
            "not structural or economic causation.\n\n"
        )

        f.write("| Analysis | Direction | Contributing attempts | Combined p-value | Status |\n")
        f.write("|---|---|---:|---:|---|\n")

        aggregate_rows = [
            (
                "Granger causality",
                "Coinbase predicts Kraken",
                cb_kr_granger,
            ),
            (
                "Granger causality",
                "Kraken predicts Coinbase",
                kr_cb_granger,
            ),
            (
                "One-step HAC predictive regression",
                "Coinbase predicts Kraken",
                cb_kr_predictive,
            ),
            (
                "One-step HAC predictive regression",
                "Kraken predicts Coinbase",
                kr_cb_predictive,
            ),
        ]

        for label, direction, row in aggregate_rows:
            f.write(
                f"| {label} | {direction} | "
                f"{row.get('contributing_attempt_count')} | "
                f"{_fmt_p(row)} | "
                f"{row.get('status')} |\n"
            )

        f.write("\n")
        f.write(
            "The per-attempt Granger results remain important for "
            "evaluating consistency across sessions; an aggregate "
            "p-value must not be interpreted as evidence that every "
            "session exhibits the same directional relationship.\n\n"
        )

        f.write("![Granger Causality]")
        f.write("(figures/granger_directional_predictability.png)\n\n")

        f.write("## 3. VAR and impulse-response diagnostics\n\n")
        f.write(
            "The IRF figure holds the economic impulse fixed as a "
            "Coinbase shock followed by the Kraken response and "
            "reports that path under both Cholesky orderings.\n\n"
        )
        f.write("![Impulse Responses](figures/impulse_responses.png)\n\n")

        f.write("## 4. Cointegration and VECM support\n\n")
        f.write(
            "- Attempts supporting cointegration diagnostics: "
            f"{source_report.get('attempts_supporting_cointegration')}\n"
        )
        f.write(
            "- Attempts supporting rank-one VECM estimation: "
            f"{source_report.get('attempts_supporting_vecm')}\n\n"
        )
        f.write(
            "Gonzalo-Granger and Hasbrouck measures are therefore "
            "reported only where the frozen rank-one requirement "
            "is satisfied.\n\n"
        )

        f.write("## 5. Price-discovery measures\n\n")
        f.write(
            "Gonzalo-Granger values are signed normalized "
            "permanent-component weights and are not constrained "
            "to the unit interval. Hasbrouck results are reported "
            "as Cholesky-ordering bounds; no methodology-frozen "
            "point estimate is inserted between those bounds.\n\n"
        )
        f.write("![Price Discovery]")
        f.write("(figures/price_discovery_by_attempt.png)\n\n")

        f.write("## 6. Predictive regressions\n\n")
        f.write(
            "Per-attempt one-step predictive regressions use the "
            "frozen HAC/Newey-West covariance specification. "
            "Individual-session coefficients and p-values are "
            "provided in the attempt summary table.\n\n"
        )

        f.write("## 7. Robustness and model stability\n\n")
        f.write(
            "The Phase 4C robustness artifact evaluates VAR "
            "stability across the frozen alternative sampling, "
            "horizon, trimming, and ordering configurations. "
            "It should not be interpreted as a robustness test of "
            "every substantive price-leadership conclusion. "
            "The figure displays per-attempt observations only; "
            "aggregate rows remain available in the underlying "
            "robustness table.\n\n"
        )
        f.write("![Robustness](figures/robustness_summary.png)\n\n")

        f.write("## 8. Limitations\n\n")
        f.write(
            "Granger causality denotes incremental temporal "
            "predictability and does not by itself establish "
            "economic or structural causation. Price-discovery "
            "estimates are session-dependent, and rank-one "
            "cointegration is not supported in every usable "
            "attempt. Aggregate Fisher evidence should therefore "
            "be interpreted alongside the per-attempt results. "
        )

        if is_dev:
            f.write(
                "These DEVELOPMENT outputs must not be interpreted as final empirical conclusions."
            )

        f.write("\n")
