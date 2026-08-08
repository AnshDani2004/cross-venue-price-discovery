import json

import polars as pl
import pytest

import cross_venue.cli as cli
from cross_venue.research.econometric_reporting import render_econometric_results
from cross_venue.research.exceptions import ResearchError


@pytest.fixture
def mock_econometric_output(tmp_path):
    root = tmp_path / "mock_eco"
    root.mkdir()

    # Manifest
    manifest = []
    for f in [
        "cointegration_diagnostics.parquet",
        "price_discovery_metrics.parquet",
        "granger_causality.parquet",
        "impulse_responses.parquet",
        "robustness_results.parquet",
        "var_model_diagnostics.parquet",
        "stationarity_diagnostics.parquet",
        "predictive_regressions.parquet",
        "aggregate_inference.parquet",
        "econometric_price_discovery_report.json",
    ]:
        manifest.append({"relative_path": f, "sha256": "fakehash"})

    (root / "output_manifest.json").write_text(json.dumps(manifest))

    # Report JSON
    (root / "econometric_price_discovery_report.json").write_text(
        json.dumps(
            {
                "analysis_result_id": "test",
                "config_hash": "test",
                "analysis_mode": "DEVELOPMENT",
                "final_inference_permitted": False,
                "dataset_snapshot_id": "test",
                "dataset_validation_id": "test",
                "total_attempt_count": 2,
                "authoritative_paired_overlap_seconds": 3600.0,
                "empirical_paired_overlap_seconds": 3590.0,
                "attempts_supporting_cointegration": 2,
                "attempts_supporting_vecm": 2,
                "aggregate_inference_row_count": 4,
            }
        )
    )

    # Parquet files
    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-2", "A-1"],
            "inferred_cointegration_rank": [1, 1],
            "vecm_status": ["ESTIMABLE", "ESTIMABLE"],
        }
    ).write_parquet(root / "cointegration_diagnostics.parquet")

    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-2", "A-1", "A-2", "A-1"],
            "metric": [
                "GONZALO_GRANGER_COMPONENT_SHARE",
                "GONZALO_GRANGER_COMPONENT_SHARE",
                "HASBROUCK_INFORMATION_SHARE",
                "HASBROUCK_INFORMATION_SHARE",
            ],
            "coinbase_value": [0.6, 0.7, None, None],
            "kraken_value": [0.4, 0.3, None, None],
            "coinbase_lower": [None, None, 0.4, 0.5],
            "coinbase_upper": [None, None, 0.6, 0.7],
            "kraken_lower": [None, None, 0.4, 0.3],
            "kraken_upper": [None, None, 0.6, 0.5],
            "status": ["COMPUTED", "COMPUTED", "COMPUTED", "COMPUTED"],
        }
    ).write_parquet(root / "price_discovery_metrics.parquet")

    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-2", "A-2", "A-1", "A-1"],
            "direction": [
                "coinbase_predicts_kraken",
                "kraken_predicts_coinbase",
                "coinbase_predicts_kraken",
                "kraken_predicts_coinbase",
            ],
            "test_statistic": [10.0, 2.0, 15.0, 1.0],
            "raw_p_value": [0.01, 0.5, 0.001, 0.8],
            "adjusted_p_value": [0.02, 0.6, 0.002, 0.9],
            "decision": [
                "REJECT_NULL",
                "FAIL_TO_REJECT",
                "REJECT_NULL",
                "FAIL_TO_REJECT",
            ],
            "model_validity_status": [
                "COMPUTED",
                "COMPUTED",
                "COMPUTED",
                "COMPUTED",
            ],
        }
    ).write_parquet(root / "granger_causality.parquet")

    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-1"],
            "shock_venue": ["coinbase"],
            "response_venue": ["kraken"],
            "horizon": [1],
            "response": [0.1],
            "cumulative_response": [0.1],
            "model_status": ["COMPUTED"],
            "ordering": ["coinbase_first"],
        }
    ).write_parquet(root / "impulse_responses.parquet")

    pl.DataFrame(
        {
            "configuration_id": ["baseline", "kraken_first"],
            "scope": ["per_attempt", "per_attempt"],
            "campaign_attempt_id": ["A-1", "A-1"],
            "metric": [
                "VAR_STABILITY",
                "VAR_STABILITY",
            ],
            "value": [1.0, 1.0],
            "status": ["COMPUTED", "COMPUTED"],
        }
    ).write_parquet(root / "robustness_results.parquet")

    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-1", "A-2"],
            "selected_lag": [2, 3],
            "fit_status": ["COMPUTED", "COMPUTED"],
            "is_stable": [True, True],
        }
    ).write_parquet(root / "var_model_diagnostics.parquet")

    pl.DataFrame({"campaign_attempt_id": ["A-1"]}).write_parquet(
        root / "stationarity_diagnostics.parquet"
    )

    pl.DataFrame(
        {
            "campaign_attempt_id": ["A-1", "A-2"],
            "direction": [
                "kraken_predicts_coinbase",
                "coinbase_predicts_kraken",
            ],
            "prediction_horizon": [1, 1],
            "predictor_lag": [1, 1],
            "coefficient": [0.5, 0.4],
            "standard_error": [0.1, 0.1],
            "t_statistic": [5.0, 4.0],
            "raw_p_value": [0.01, 0.05],
            "effective_sample_count": [500, 500],
            "fit_status": ["COMPUTED", "COMPUTED"],
        }
    ).write_parquet(root / "predictive_regressions.parquet")

    pl.DataFrame(
        {
            "analysis": [
                "granger_causality",
                "granger_causality",
                "predictive_regression",
                "predictive_regression",
            ],
            "specification_id": [
                "baseline",
                "baseline",
                "baseline",
                "baseline",
            ],
            "direction": [
                "coinbase_predicts_kraken",
                "kraken_predicts_coinbase",
                "coinbase_predicts_kraken",
                "kraken_predicts_coinbase",
            ],
            "scope": [
                "aggregate",
                "aggregate",
                "aggregate",
                "aggregate",
            ],
            "combination_method": [
                "fisher",
                "fisher",
                "fisher",
                "fisher",
            ],
            "p_value_source": [
                "raw_p_value",
                "raw_p_value",
                "raw_p_value",
                "raw_p_value",
            ],
            "contributing_attempt_count": [2, 2, 2, 2],
            "fisher_statistic": [20.0, 2.0, 18.0, 1.0],
            "degrees_of_freedom": [4, 4, 4, 4],
            "combined_p_value": [0.001, 0.7, 0.002, 0.8],
            "status": [
                "COMPUTED",
                "COMPUTED",
                "COMPUTED",
                "COMPUTED",
            ],
            "insufficiency_reason": [None, None, None, None],
        }
    ).write_parquet(root / "aggregate_inference.parquet")

    # Fix hashes
    import hashlib

    manifest = []
    for f in [
        "cointegration_diagnostics.parquet",
        "price_discovery_metrics.parquet",
        "granger_causality.parquet",
        "impulse_responses.parquet",
        "robustness_results.parquet",
        "var_model_diagnostics.parquet",
        "stationarity_diagnostics.parquet",
        "predictive_regressions.parquet",
        "aggregate_inference.parquet",
        "econometric_price_discovery_report.json",
    ]:
        h = hashlib.sha256()
        h.update((root / f).read_bytes())
        manifest.append({"relative_path": f, "sha256": h.hexdigest()})
    (root / "output_manifest.json").write_text(json.dumps(manifest))

    return root


def test_successful_reporting(mock_econometric_output, tmp_path) -> None:
    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)

    assert (out / "econometric_results_report.md").exists()
    assert (out / "reporting_manifest.json").exists()
    assert (out / "tables/attempt_summary.parquet").exists()
    assert (out / "tables/aggregate_inference.parquet").exists()
    assert (out / "figures/price_discovery_by_attempt.png").exists()

    summary = pl.read_parquet(out / "tables/attempt_summary.parquet")

    assert summary["cb_kr_granger_stat"].drop_nulls().len() == 2
    assert summary["kr_cb_granger_stat"].drop_nulls().len() == 2
    assert set(summary["var_status"].to_list()) == {"STABLE"}

    md = (out / "econometric_results_report.md").read_text()
    assert "Aggregate directional inference" in md
    assert "Coinbase predicts Kraken" in md
    assert "Kraken predicts Coinbase" in md


def test_deterministic_attempt_ordering(mock_econometric_output, tmp_path) -> None:
    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)
    df = pl.read_parquet(out / "tables/attempt_summary.parquet")
    assert df["campaign_attempt_id"].to_list() == ["A-1", "A-2"]


def test_session_date_not_inferred_from_attempt_suffix(
    mock_econometric_output,
    tmp_path,
) -> None:
    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)

    df = pl.read_parquet(out / "tables/attempt_summary.parquet")

    assert df["session_date"].null_count() == 2


def test_missing_manifest(mock_econometric_output, tmp_path) -> None:
    (mock_econometric_output / "output_manifest.json").unlink()
    with pytest.raises(ResearchError, match=r"Missing output_manifest\.json"):
        render_econometric_results(mock_econometric_output, tmp_path / "out")


def test_computed_numeric_row_nan(mock_econometric_output, tmp_path) -> None:
    # Corrupt PD metrics
    df = pl.read_parquet(mock_econometric_output / "price_discovery_metrics.parquet").to_dicts()
    df[0]["coinbase_value"] = float("nan")
    pl.DataFrame(df).write_parquet(mock_econometric_output / "price_discovery_metrics.parquet")

    # Fix hash
    import hashlib

    h = hashlib.sha256()
    h.update((mock_econometric_output / "price_discovery_metrics.parquet").read_bytes())
    manifest = json.loads((mock_econometric_output / "output_manifest.json").read_text())
    for m in manifest:
        if m["relative_path"] == "price_discovery_metrics.parquet":
            m["sha256"] = h.hexdigest()
    (mock_econometric_output / "output_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ResearchError, match="NaN found in valid PD row"):
        render_econometric_results(mock_econometric_output, tmp_path / "out")


def test_computed_numeric_row_inf(mock_econometric_output, tmp_path) -> None:
    df = pl.read_parquet(mock_econometric_output / "predictive_regressions.parquet").to_dicts()
    df[0]["coefficient"] = float("inf")
    pl.DataFrame(df).write_parquet(mock_econometric_output / "predictive_regressions.parquet")

    import hashlib

    h = hashlib.sha256()
    h.update((mock_econometric_output / "predictive_regressions.parquet").read_bytes())
    manifest = json.loads((mock_econometric_output / "output_manifest.json").read_text())
    for m in manifest:
        if m["relative_path"] == "predictive_regressions.parquet":
            m["sha256"] = h.hexdigest()
    (mock_econometric_output / "output_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ResearchError, match=r"NaN found in valid predictive regression"):
        render_econometric_results(mock_econometric_output, tmp_path / "out")


def test_not_estimable_remains_unavailable(mock_econometric_output, tmp_path) -> None:
    df = pl.read_parquet(mock_econometric_output / "price_discovery_metrics.parquet").to_dicts()
    df[0]["status"] = "NOT_ESTIMABLE"
    pl.DataFrame(df).write_parquet(mock_econometric_output / "price_discovery_metrics.parquet")

    import hashlib

    h = hashlib.sha256()
    h.update((mock_econometric_output / "price_discovery_metrics.parquet").read_bytes())
    manifest = json.loads((mock_econometric_output / "output_manifest.json").read_text())
    for m in manifest:
        if m["relative_path"] == "price_discovery_metrics.parquet":
            m["sha256"] = h.hexdigest()
    (mock_econometric_output / "output_manifest.json").write_text(json.dumps(manifest))

    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)
    res = pl.read_parquet(out / "tables/attempt_summary.parquet")

    row_a2 = res.filter(pl.col("campaign_attempt_id") == "A-2").to_dicts()[0]
    assert row_a2["gg_status"] == "NOT_ESTIMABLE"


def test_development_input_marked_non_final(mock_econometric_output, tmp_path) -> None:
    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)
    md = (out / "econometric_results_report.md").read_text()
    assert "DEVELOPMENT / PRELIMINARY RESULTS — FINAL INFERENCE NOT PERMITTED" in md


def test_final_input_fixture(mock_econometric_output, tmp_path) -> None:
    rep = json.loads(
        (mock_econometric_output / "econometric_price_discovery_report.json").read_text()
    )
    rep["analysis_mode"] = "FINAL"
    rep["final_inference_permitted"] = True
    (mock_econometric_output / "econometric_price_discovery_report.json").write_text(
        json.dumps(rep)
    )

    import hashlib

    h = hashlib.sha256()
    h.update((mock_econometric_output / "econometric_price_discovery_report.json").read_bytes())
    manifest = json.loads((mock_econometric_output / "output_manifest.json").read_text())
    for m in manifest:
        if m["relative_path"] == "econometric_price_discovery_report.json":
            m["sha256"] = h.hexdigest()
    (mock_econometric_output / "output_manifest.json").write_text(json.dumps(manifest))

    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)
    md = (out / "econometric_results_report.md").read_text()
    assert "DEVELOPMENT / PRELIMINARY RESULTS" not in md
    assert "The dataset satisfies final composite requirements" in md


def test_source_artifacts_unchanged(mock_econometric_output, tmp_path) -> None:
    import hashlib

    def _hash_all():
        hashes = {}
        for f in mock_econometric_output.rglob("*"):
            if f.is_file():
                h = hashlib.sha256()
                h.update(f.read_bytes())
                hashes[str(f)] = h.hexdigest()
        return hashes

    before = _hash_all()
    out = tmp_path / "out"
    render_econometric_results(mock_econometric_output, out)
    after = _hash_all()
    assert before == after


def test_cli_success(mock_econometric_output, tmp_path) -> None:
    import argparse

    out = tmp_path / "out"
    args = argparse.Namespace(
        command="render-econometric-results",
        econometric_output_root=mock_econometric_output,
        output_root=out,
    )
    assert cli.render_econometric_results_cmd(args) == 0
    assert (out / "reporting_manifest.json").exists()


def test_cli_failure(mock_econometric_output, tmp_path) -> None:
    import argparse

    (mock_econometric_output / "output_manifest.json").unlink()
    out = tmp_path / "out"
    args = argparse.Namespace(
        command="render-econometric-results",
        econometric_output_root=mock_econometric_output,
        output_root=out,
    )
    assert cli.render_econometric_results_cmd(args) == 1


def test_required_artifact_must_be_manifest_bound(
    mock_econometric_output,
    tmp_path,
) -> None:
    manifest_path = mock_econometric_output / "output_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    manifest = [
        entry for entry in manifest if entry["relative_path"] != "aggregate_inference.parquet"
    ]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(
        ResearchError,
        match="Source manifest missing required artifacts",
    ):
        render_econometric_results(
            mock_econometric_output,
            tmp_path / "out",
        )


def test_duplicate_attempt_identity_rejected(
    mock_econometric_output,
    tmp_path,
) -> None:
    import hashlib

    artifact = mock_econometric_output / "cointegration_diagnostics.parquet"

    df = pl.read_parquet(artifact)
    duplicated = pl.concat(
        [df, df.head(1)],
        how="vertical",
    )
    duplicated.write_parquet(artifact)

    manifest_path = mock_econometric_output / "output_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

    for entry in manifest:
        if entry["relative_path"] == "cointegration_diagnostics.parquet":
            entry["sha256"] = digest

    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(
        ResearchError,
        match="Duplicate semantic identities",
    ):
        render_econometric_results(
            mock_econometric_output,
            tmp_path / "out",
        )


def test_final_mode_requires_final_inference_permission(
    mock_econometric_output,
    tmp_path,
) -> None:
    import hashlib

    report_path = mock_econometric_output / "econometric_price_discovery_report.json"

    report = json.loads(report_path.read_text())
    report["analysis_mode"] = "FINAL"
    report["final_inference_permitted"] = False
    report_path.write_text(json.dumps(report))

    manifest_path = mock_econometric_output / "output_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()

    for entry in manifest:
        if entry["relative_path"] == "econometric_price_discovery_report.json":
            entry["sha256"] = digest

    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(
        ResearchError,
        match=("Source report is FINAL but final inference is not permitted"),
    ):
        render_econometric_results(
            mock_econometric_output,
            tmp_path / "out",
        )
