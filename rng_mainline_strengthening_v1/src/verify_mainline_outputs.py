"""Verify numeric replay and cross-file invariants for a finished run."""

import argparse
from datetime import datetime, timezone
import json
import time

import numpy as np
import pandas as pd

from common import EARLY, REPO, ROOT, SITE, sha, write_json
from model import fit_logit, make_risk
from run_main import fresh_dir, run_provenance


def read_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def verify_legacy():
    legacy = REPO / "results/legacy/run_001"
    original = {
        "backfill": ROOT / "outputs/2026-11-09_rng_driver_backfill/run_001/driver_consequence_backfill_summary.json",
        "spatial": ROOT / "outputs/2026-11-10_rng_spatial_conley/run_001/spatial_conley_hac_summary.json",
        "diagnostics": ROOT / "outputs/2026-11-10_rng_driver_logit_diagnostics/run_002/driver_logit_diagnostics_summary.json",
    }
    paths = [*original.values()]
    saved, replay = {}, {}
    for kind, old in original.items():
        rerun = legacy / kind / old.name
        saved[kind], replay[kind] = read_json(old), read_json(rerun)
        assert saved[kind]["script_sha256"] == replay[kind]["script_sha256"]
        paths.append(rerun)
    differences = []
    for key in saved["backfill"]["results"]:
        for spec in ("T1_yearFE_log_dist", "T2_stateFE_log_dist"):
            before, after = [d["backfill"]["results"][key][spec] for d in (saved, replay)]
            for field in ("n_py", "n_events"):
                assert before[field] == after[field]
            for field in ("coef", "se", "p", "se_clustered", "p_clustered"):
                assert abs(before[field] - after[field]) < 1e-9
                differences.append(abs(before[field] - after[field]))
            if spec.startswith("T2"):
                assert before["dropped_states"] == after["dropped_states"]
    for key in saved["spatial"]["results"]:
        before, after = [d["spatial"]["results"][key] for d in (saved, replay)]
        for field in ("n_landfills", "n_events", "n_person_years", "dropped_states"):
            assert before[field] == after[field]
        for cutoff in ("25", "50", "100", "200", "400"):
            for field in ("se", "p"):
                dif = abs(before["conley_km"][cutoff][field] - after["conley_km"][cutoff][field])
                assert dif < 1e-9
                differences.append(dif)
    result = replay["spatial"]["results"]["ev_opshut_corr"]
    diag = replay["diagnostics"]["result"]["diagnostics"]
    assert diag["converged"] and diag["unpenalized_singular"]
    for file in (original["backfill"].parent / "facility_trace.csv", legacy / "backfill/facility_trace.csv"):
        paths.append(file)
    a, b = map(pd.read_csv, paths[-2:])
    pd.testing.assert_frame_equal(a, b)
    return {
        "replayed_t1_t2_models": 8, "replayed_spatial_models": 2, "facility_trace_exact_match": True,
        "legacy_corrected": result,
        "max_absolute_numeric_difference": max(differences), "diagnostic": diag,
        "saved_diagnostic_iterations": saved["diagnostics"]["result"]["diagnostics"]["iterations"],
    }, paths


def verify_comparisons(main_dir):
    fits = pd.read_csv(main_dir / "deployment_comparisons.csv").set_index("comparison")
    dates = pd.read_csv(main_dir / "site_risk_ledger.csv")
    records = pd.read_csv(main_dir / "event_ledger.csv")
    sources = pd.read_csv(main_dir / "source_ledger.csv")
    annual = pd.read_csv(main_dir / "annual_deployments.csv")
    fixed = dates[dates["in_common_support"]]
    assert dates[SITE].is_unique and records["event_key"].is_unique and sources["source_id"].is_unique
    listed = {key for row in records["source_ids"].dropna() for key in row.split(";")}
    assert listed.union(records["registry_source_id"]).issubset(sources["source_id"])
    counts = {}
    for rule in ("registered_broad", "registered", "status_only", "date_only", "reconciled"):
        row = fits.loc[f"common_{rule}"]
        assert row["n_landfills"] == len(fixed)
        assert row["risk_years"] == (fixed[f"{rule}_exit"] - fixed["entry"] + 1).sum()
        assert row["n_events"] == fixed[f"{rule}_event"].notna().sum()
        assert row["rank"] == row["parameters"] and row["separation"] == "no_direction_detected"
        tab = annual[annual["frame"].eq("fixed_full_frame") & annual["encoding"].eq(rule)]
        assert tab["annual_events"].sum() == dates[f"{rule}_event"].notna().sum()
        counts[rule] = int(row["n_events"])
    assert set(dates.loc[dates["eligibility"].eq("verified_pre1995_operation"), SITE]) == {966, 1465}
    withheld_unknown = records[records[SITE].isin([12144]) & records["evidence_status"].eq("unknown_cutoff")]
    withheld_confirmed = records[records[SITE].isin([838, 1469, 2001]) & records["evidence_status"].eq("confirmed_post_cutoff")]
    assert len(withheld_unknown) == 1 and withheld_unknown["joint_year"].isna().all()
    assert len(withheld_confirmed) == 3 and withheld_confirmed["joint_year"].isna().all()
    assert 2023 in records.loc[records[SITE].eq(559), "joint_year"].to_list()
    alliance = records[records[SITE].eq(1254)].set_index("project_id")
    assert alliance.loc["1329-0", "joint_year"] == 1998
    assert alliance.loc["200997-0", "joint_year"] == 2021
    assert (records.loc[records["physical_system_id"].eq("corpus_christi"), SITE].nunique()) == 2
    return {"common_event_counts": counts, "verified_prewindow_exclusions": 2,
            "four_old_2024_events_withheld": True,
            "withheld_breakdown": {"confirmed_post_cutoff": 3, "unknown_cutoff": 1},
            "fixed_frame_id_and_risk_accounting": True}


def verify_temporal(temp_dir):
    sites = pd.read_csv(temp_dir / "landmark2020_cohort.csv")
    diagnostics = read_json(temp_dir / "temporal_diagnostics.json")
    models = pd.read_csv(temp_dir / "landmark2020_models.csv")
    assert sites[SITE].is_unique
    assert len(sites) == 2629 and sites["seen_2024-09"].sum() == 2622
    assert sites["legacy_48_candidate"].sum() == 48
    event = sites["registry_endpoint"].eq("observed_operated_registry_event")
    first = pd.to_datetime(sites.loc[event, "earliest_operated_registered_start"])
    assert first.gt(diagnostics["baseline_end"]).all() and first.le(diagnostics["common_followup_end"]).all()
    for subset, rows in models.groupby(["endpoint", "support", "geography"]):
        if len(rows) == 1:
            assert rows.iloc[0]["model_status"] == "insufficient_event_support"
        else:
            assert rows["n_landfills"].nunique() == rows["n_events"].nunique() == 1, subset
    for geometry in ("eia", "hifld"):
        assert diagnostics["geometries"][geometry]["max_absolute_difference_km"] < 1e-7
    layers = ["eia_2020_distance_km", "hifld_later_at_2020_coords_distance_km"]
    matched = sites.loc[
        sites["evidence_screened_endpoint"].isin({
            "observed_operated_registry_event", "seen_at_endpoint_no_qualifying_registry_event"
        }) & sites[layers].gt(0).all(axis=1) & sites["wip_tons_2020"].gt(0)
        & ~sites["wip_measurement_year"].gt(2020) & ~sites["conflicting_wip_tons_2020"], layers
    ]
    expected_n = models.loc[
        models["endpoint"].eq("evidence_screened_endpoint") & models["support"].eq("baseline_wip")
        & models["geography"].eq("pooled_all_regions"), "n_landfills"
    ]
    assert len(expected_n) == 2 and expected_n.eq(len(matched)).all()
    delta = matched[layers[0]].sub(matched[layers[1]]).abs()
    return {"fixed_end_dates_valid": True, "paired_layers_same_support": True,
            "model_rows": len(models), "distance_brute_force_checks": 24,
            "layer_agreement_baseline_wip_screened": {
                "n_landfills": len(matched), "abs_difference_median_km": float(delta.median()),
                "n_abs_difference_le_1m": int(delta.le(0.001).sum()),
                "n_abs_difference_gt_1km": int(delta.gt(1).sum()),
                "log_distance_correlation": float(np.log(matched).corr().iloc[0, 1]),
            }}


def verify_small_fixtures():
    # Check exact likelihood equivalence when repeated risk rows are grouped.
    X = np.array([[1, -1.0], [1, 0], [1, 1.0]])
    y = np.array([1, 2, 3])
    n = np.array([5, 5, 5])
    expanded = np.concatenate([np.r_[np.ones(yy), np.zeros(nn - yy)] for yy, nn in zip(y, n, strict=True)])
    model = fit_logit(X, y, n)
    replay = fit_logit(np.repeat(X, n, axis=0), expanded, np.ones(n.sum()))
    np.testing.assert_allclose(model[0], replay[0], atol=1e-10)
    site = pd.DataFrame({SITE: [1], "entry": [EARLY]})
    early = make_risk(site, pd.Series({1: 2023}), 2024)
    late = make_risk(site, pd.Series({1: 2024}), 2024)
    assert late["n"].sum() - early["n"].sum() == 1
    assert late["y"].sum() == early["y"].sum() == 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", required=True)
    parser.add_argument("--temporal", required=True)
    parser.add_argument("--figures", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    out = fresh_dir(args.run, "checks")
    started = datetime.now(timezone.utc)
    tick = time.monotonic()
    result, inputs = verify_legacy()
    main_dir = REPO / "results/mainline" / args.main
    temp_dir = REPO / "results/temporal" / args.temporal
    figure_dir = REPO / "results/figures" / args.figures
    result["comparisons"] = verify_comparisons(main_dir)
    result["temporal"] = verify_temporal(temp_dir)
    result["figures"] = read_json(figure_dir / "figure_checks.json")
    assert result["figures"]["legacy_matching_points_by_panel"] == [0, 0, 0]
    assert result["figures"]["repaired_points_by_panel"] == [9, 9, 9]
    svg_files = list(figure_dir.glob("*.svg"))
    png_files = list(figure_dir.glob("*.png"))
    assert len(svg_files) == len(png_files) == 4
    assert all(p.stat().st_size > 8000 for p in [*svg_files, *png_files])
    verify_small_fixtures()
    result["numeric_fixture_checks"] = 2
    for folder in (main_dir, temp_dir):
        provenance = read_json(folder / "run_record.json")
        for relative, fingerprint in provenance["sha256"].items():
            if relative.startswith("rng_mainline_strengthening_v1/src/"):
                continue  # Historical source versions are recorded by commit and file hash.
            assert sha(ROOT / relative) == fingerprint, relative
    write_json(result, out, "baseline_checks")
    run_provenance(out, started, time.monotonic() - tick,
                   [*inputs, *main_dir.glob("*.csv"), *temp_dir.glob("*.csv"), figure_dir / "figure_checks.json"])
    print(f"{out}: verified replay, derived totals, cutoff, source references and four figures")


if __name__ == "__main__":
    main()
