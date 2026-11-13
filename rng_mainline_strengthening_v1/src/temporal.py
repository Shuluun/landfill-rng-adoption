"""Track the August 2020 LMOP frame through all available comparable snapshots."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import time
from zipfile import ZipFile

import numpy as np
import pandas as pd

from common import AUDIT30, AUDIT36, CONUS, EIA, HIFLD, HIST_SCREEN, HISTORY, LMOP, OP, REPO, SITE
from common import csv, pipeline_rows, read_book, write_json
from events import ledger
from geometry import ArcIndex, eia_arcs, read_arcs, unit_vectors
from model import SpatialWeights, fit, paired_difference
from run_main import fresh_dir, run_provenance

BASE = pd.Timestamp("2020-08-31")
END = pd.Timestamp("2024-08-31")
SHEETS = {
    "2020-08": "2020Aug_lmopdata.xlsx", "2021-09": "2021Sep_lmopdata.xlsx",
    "2022-08": "2022Aug_lmopdata.xlsx", "2023-07": "2023Jul_lmopdata.xlsx",
}
REGION = {
    state: region for region, states in {
        "Northeast": "CT ME MA NH RI VT NJ NY PA",
        "Midwest": "IN IL MI OH WI IA KS MN MO NE ND SD",
        "South": "DE DC FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX",
        "West": "AZ CO ID MT NV NM UT WY CA OR WA",
    }.items() for state in states.split()
}


def snapshots():
    books, metadata = {}, {}
    with ZipFile(HISTORY) as archive:
        for month, name in SHEETS.items():
            content = archive.read(name)
            books[month] = read_book(BytesIO(content))
            metadata[month] = {"member": name, "member_sha256": sha256(content).hexdigest()}
    books["2024-09"] = read_book(LMOP)
    metadata["2024-09"] = {"member": LMOP.name}
    for month, book in books.items():
        metadata[month].update(rows=len(book), n_landfills=int(book[SITE].nunique()))
    return books, metadata


def first_project_history(books):
    pieces = []
    for month, book in books.items():
        p = pipeline_rows(book)
        p = p[[SITE, "Project ID", "parent_project_id", "Current Project Status", "Project Start Date",
               "Project Shutdown Date", "excel_row"]].copy()
        p["snapshot_month"] = month
        p["operated_marker"] = p["Current Project Status"].isin(OP)
        last_snapshot_day = pd.Timestamp(month) + pd.offsets.MonthEnd(0)
        p["start_consistent_with_observation"] = p["Project Start Date"].le(last_snapshot_day)
        pieces.append(p)
    return pd.concat(pieces, ignore_index=True)


def pre_energy(book):
    # Snapshot-as-observed categories only. Missing registrations and historical
    # shutdown are not equivalent to absence of utilization.
    out = {}
    for lid, g in book.groupby(SITE):
        typ = g["Project Type Category"].astype("string")
        op = g["Current Project Status"].eq("Operational") & g["Project Start Date"].le(BASE)
        conventional = typ.isin(["Electricity", "Direct"])
        current = sorted(typ[op & conventional].unique())
        if current:
            label = "electricity_and_direct" if len(current) == 2 else {
                "Electricity": "electricity", "Direct": "direct_use"
            }[current[0]]
        elif (conventional & g["Current Project Status"].eq("Shutdown") & g["Project Shutdown Date"].le(BASE)).any():
            label = "previous_use_stopped_in_registry"
        elif conventional.any():
            label = "uncertain_stage_or_date"
        elif (g["Project ID"].notna() & (typ.isna() | typ.isin(["Unknown"]))).any():
            label = "unknown_project_use"
        else:
            label = "no_electricity_or_direct_use_registered"
        out[lid] = label
    return out


def lost_identity_candidates(cohort, last_book):
    fields = [SITE, "GHGRP ID", "Landfill Name", "State", "City", "Physical Address"]
    other = last_book[fields].drop_duplicates(SITE)
    result = []
    for row in cohort[~cohort["seen_2024-09"]].to_dict("records"):
        same_id = other["GHGRP ID"].eq(row["ghgrp_id"]) if pd.notna(row["ghgrp_id"]) else pd.Series(False, index=other.index)
        same_name = other["Landfill Name"].astype(str).str.lower().str.strip().eq(str(row["landfill_name"]).lower().strip())
        hits = other[other["State"].eq(row["state"]) & (same_id | same_name)]
        result.append({SITE: row[SITE], "landfill_name": row["landfill_name"], "state": row["state"],
                       "ghgrp_id": row["ghgrp_id"],
                       "archive_presence": ";".join(k for k in [*SHEETS, "2024-09"] if row[f"seen_{k}"]),
                       "same_ghgrp_or_name_candidate_ids": ";".join(map(str, hits[SITE])),
                       "candidate_names": ";".join(hits["Landfill Name"].astype(str)),
                       "identity_resolution": "plausible_duplicate_same_name_city_and_street_alias_not_adopted"
                       if row[SITE] == 21054 and 1853 in set(hits[SITE])
                       else "unresolved_no_alias_adopted"})
    return pd.DataFrame(result)


def build_cohort(books, projects, history):
    b = books["2020-08"]
    columns = {
        "Landfill Name": "landfill_name", "State": "state", "GHGRP ID": "ghgrp_id",
        "County": "county", "Latitude": "lat", "Longitude": "lon", "Waste in Place (tons)": "wip_tons_2020",
        "Waste in Place Year": "wip_measurement_year", "Year Landfill Opened": "opened",
    }
    g = b.groupby(SITE)
    b0 = g[list(columns)].first().rename(columns=columns).reset_index()
    for key in ("Latitude", "Longitude", "State", "Waste in Place (tons)", "Waste in Place Year"):
        b0["conflicting_" + columns[key]] = b0[SITE].map(g[key].nunique()).gt(1)
    b0["baseline_snapshot_month"] = "2020-08"
    b0["wip_publication_date_exact"] = ""
    b0["wip_observable_in_snapshot_month"] = "2020-08"
    b0["region"] = b0["state"].map(REGION)
    b0["baseline_electricity_direct_use_proxy"] = b0[SITE].map(pre_energy(b))
    for month, book in books.items():
        b0[f"seen_{month}"] = b0[SITE].isin(book[SITE])
    b0["n_observed_snapshots"] = b0[[f"seen_{k}" for k in books]].sum(axis=1)
    b0["legacy_48_candidate"] = b0[SITE].isin(pd.read_csv(HIST_SCREEN)[SITE])

    prior = set(history.loc[history["snapshot_month"].eq("2020-08") & history["operated_marker"], SITE])
    base_with_future_start = set(history.loc[
        history["snapshot_month"].eq("2020-08") & history["operated_marker"]
        & history["Project Start Date"].gt(BASE), SITE
    ])
    actual_markers = history[history["operated_marker"] & history["start_consistent_with_observation"]].copy()
    dated = actual_markers.groupby(SITE)["Project Start Date"].agg(["min", "max"])
    b0["earliest_operated_registered_start"] = b0[SITE].map(dated["min"])
    b0["latest_operated_registered_start"] = b0[SITE].map(dated["max"])
    b0["any_operated_status_later"] = b0[SITE].isin(history.loc[
        history["operated_marker"] & history["snapshot_month"].ne("2020-08"), SITE])
    b0["baseline_prior_operated_or_shutdown"] = b0[SITE].isin(prior)
    b0["preexisting_in_later_archive"] = b0["earliest_operated_registered_start"].le(BASE) & ~b0["baseline_prior_operated_or_shutdown"]
    b0["baseline_month_boundary"] = b0["earliest_operated_registered_start"].between(pd.Timestamp("2020-08-01"), BASE)
    b0["prior_status_date_conflict"] = b0[SITE].isin(base_with_future_start)
    b0["registry_incidence_eligible"] = ~(
        b0["baseline_prior_operated_or_shutdown"] | b0["preexisting_in_later_archive"]
    ) & ~b0["opened"].gt(2020)

    b0["first_operated_observation_month"] = b0[SITE].map(actual_markers.groupby(SITE)["snapshot_month"].min())
    b0["any_shutdown_by_2024_snapshot"] = b0[SITE].isin(history.loc[
        history["Current Project Status"].eq("Shutdown"), SITE
    ])
    prior_shutdown = history[history["Current Project Status"].eq("Shutdown")].groupby(
        [SITE, "parent_project_id"]
    )["snapshot_month"].min().rename("first_shutdown_snapshot")
    operated_after = history[history["Current Project Status"].eq("Operational")].join(
        prior_shutdown, on=[SITE, "parent_project_id"]
    )
    later_operated = operated_after["first_shutdown_snapshot"].notna() & operated_after["snapshot_month"].gt(
        operated_after["first_shutdown_snapshot"]
    )
    b0["restart_or_registry_revision_candidate"] = b0[SITE].isin(operated_after.loc[later_operated, SITE])
    shutdown_within_followup = set(actual_markers.loc[
        actual_markers["Current Project Status"].eq("Shutdown")
        & actual_markers["Project Start Date"].gt(BASE)
        & actual_markers["Project Shutdown Date"].le(END), SITE])
    last_positive = set(history.loc[history["operated_marker"] & history["snapshot_month"].eq("2024-09"), SITE])
    b0["ever_operated_interval_ended_by_cutoff"] = b0[SITE].isin(shutdown_within_followup)
    b0["has_observed_operated_marker_in_terminal_snapshot"] = b0[SITE].isin(last_positive)
    event = b0["earliest_operated_registered_start"].gt(BASE) & b0["earliest_operated_registered_start"].le(END)
    b0["registry_endpoint"] = np.select([
        ~b0["registry_incidence_eligible"], event,
        ~b0["seen_2024-09"], b0["any_operated_status_later"] & b0["earliest_operated_registered_start"].isna(),
    ], ["excluded_baseline_or_preexisting", "observed_operated_registry_event",
        "lost_identity_or_followup", "operated_marker_date_unresolved"],
        default="seen_at_endpoint_no_qualifying_registry_event")

    # External timing checks can improve this registry endpoint case by case.
    # They do not establish absence of unrecorded events in observed noncases.
    source_backed = projects[projects["evidence_status"].isin({
        "confirmed_year", "dated_operating_evidence_inherited", "registry_year_corroborated_inherited"
    }) & projects["joint_year"].notna()].sort_values("joint_year").drop_duplicates(SITE).set_index(SITE)
    b0["external_first_lower"] = pd.to_datetime(b0[SITE].map(source_backed["date_lower"]), errors="coerce")
    b0["external_first_upper"] = pd.to_datetime(b0[SITE].map(source_backed["date_upper"]), errors="coerce")
    b0["external_source_ids"] = b0[SITE].map(source_backed["source_ids"])
    ambiguous = projects[projects["evidence_status"].isin({
        "unknown_cutoff", "no_confirmed_date_evidence_incomplete"
    })].sort_values("registered_date").drop_duplicates(SITE).set_index(SITE)
    b0["targeted_unresolved_lower"] = pd.to_datetime(b0[SITE].map(ambiguous["date_lower"]), errors="coerce")
    b0["targeted_unresolved_upper"] = pd.to_datetime(b0[SITE].map(ambiguous["date_upper"]), errors="coerce")
    b0["targeted_unresolved_candidate"] = b0[SITE].isin(ambiguous.index)
    b0["external_case_in_fixed_window"] = b0["external_first_lower"].gt(BASE) & b0["external_first_upper"].le(END)
    b0["external_case_window_boundary"] = (
        b0["external_first_lower"].le(END) & b0["external_first_upper"].gt(END)
        | b0["external_first_lower"].le(BASE) & b0["external_first_upper"].gt(BASE)
    )
    b0["evidence_screened_endpoint"] = b0["registry_endpoint"]
    eligible = b0["registry_incidence_eligible"]
    b0.loc[eligible & b0["external_case_in_fixed_window"], "evidence_screened_endpoint"] = "observed_operated_registry_event"
    outside = eligible & b0["external_first_lower"].gt(END) & event
    b0.loc[outside & b0["seen_2024-09"], "evidence_screened_endpoint"] = "seen_at_endpoint_no_qualifying_registry_event"
    b0.loc[outside & ~b0["seen_2024-09"], "evidence_screened_endpoint"] = "lost_identity_or_followup"
    unresolved = eligible & ~b0["external_case_in_fixed_window"] & (
        b0["external_case_window_boundary"]
        | (b0["targeted_unresolved_candidate"] & ~b0["targeted_unresolved_lower"].gt(END))
    )
    b0.loc[unresolved, "evidence_screened_endpoint"] = "external_cutoff_unresolved"
    # Confirmed post-cutoff operation is not an in-window event, even when the
    # registry lists an operated marker (e.g. a shared-project date attributed to
    # a co-supplier site whose own line completed after the follow-up window).
    post_cutoff = eligible & b0[SITE].isin(
        set(projects.loc[projects["evidence_status"].eq("confirmed_post_cutoff"), SITE])
    )
    b0.loc[post_cutoff & b0["seen_2024-09"], "evidence_screened_endpoint"] = "seen_at_endpoint_no_qualifying_registry_event"
    b0.loc[post_cutoff & ~b0["seen_2024-09"], "evidence_screened_endpoint"] = "lost_identity_or_followup"
    return b0


def add_distances(cohort):
    eia, member, projection = eia_arcs(EIA)
    mask = (
        cohort["state"].isin(CONUS) & cohort["lat"].between(24, 50)
        & cohort["lon"].between(-125, -66)
        & ~cohort[["conflicting_lat", "conflicting_lon", "conflicting_state"]].any(axis=1)
    )
    points = unit_vectors(cohort.loc[mask, "lon"].to_numpy(), cohort.loc[mask, "lat"].to_numpy())
    eia_dist, eia_qa = ArcIndex(eia).evaluate(points)
    hifld_dist, hifld_qa = ArcIndex(read_arcs(HIFLD.read_bytes(), mercator=True)).evaluate(points)
    cohort.loc[mask, "eia_2020_distance_km"] = eia_dist
    cohort.loc[mask, "hifld_later_at_2020_coords_distance_km"] = hifld_dist
    return {"eia_member": member, "eia_crs": projection, "eia": eia_qa, "hifld": hifld_qa}


def temporal_models(cohort):
    loc = cohort[
        cohort["eia_2020_distance_km"].gt(0) & cohort["hifld_later_at_2020_coords_distance_km"].gt(0)
    ].copy()
    spatial = SpatialWeights(loc)
    loc["actual_state"] = loc["state"]
    loc["state"] = loc["region"]  # broad fixed geographic adjustment with limited events
    loc["n"] = 1
    scale = loc["wip_tons_2020"].gt(0) & ~loc["wip_measurement_year"].gt(2020) & ~loc["conflicting_wip_tons_2020"]
    strict_scale = scale & loc["wip_measurement_year"].between(1900, 2020) & ~loc["conflicting_wip_measurement_year"]
    loc["log_waste"] = np.log(loc["wip_tons_2020"].where(scale))
    fits, pairs = [], []
    for endpoint in ("registry_endpoint", "evidence_screened_endpoint"):
        outcome = loc[endpoint].map({"observed_operated_registry_event": 1,
                                     "seen_at_endpoint_no_qualifying_registry_event": 0})
        for name, selection, controls in (
            ("distance_only", outcome.notna(), ("log_dist",)),
            ("baseline_wip", outcome.notna() & scale, ("log_dist", "log_waste")),
            ("dated_baseline_wip", outcome.notna() & strict_scale, ("log_dist", "log_waste")),
        ):
            chosen = loc[selection].copy()
            chosen["y"] = outcome[selection].astype(int)
            regional = chosen.groupby("state")["y"].agg(["sum", "size"])
            supported = regional.index[(regional["sum"] > 0) & (regional["sum"] < regional["size"])]
            for mode, group in (
                ("pooled_all_regions", chosen),
                ("region_adjusted_supported_only", chosen[chosen["state"].isin(supported)].copy()),
            ):
                fixed = mode == "region_adjusted_supported_only"
                regions = ";".join(sorted(group["state"].unique()))
                if group["y"].sum() < 10 or (fixed and len(supported) < 2):
                    fits.append({"endpoint": endpoint, "support": name, "geography": mode,
                                 "model_status": "insufficient_event_support", "included_regions": regions,
                                 "n_landfills": len(group), "n_events": int(group["y"].sum())})
                    continue
                results = {}
                for layer, column in (("EIA_Jan2020", "eia_2020_distance_km"),
                                      ("HIFLD_later", "hifld_later_at_2020_coords_distance_km")):
                    group["log_dist"] = np.log(group[column])
                    result = fit(group, spatial, state_fe=fixed, calendar=False, controls=controls, diagnose=True)
                    stats = result.stats.copy()
                    stats["n_regions"] = stats.pop("n_states")
                    stats["n_states"] = int(group["actual_state"].nunique())
                    stats.pop("risk_years")
                    fits.append({"endpoint": endpoint, "support": name, "layer": layer, "geography": mode,
                                 "included_regions": regions,
                                 "model_status": "fit_registry_endpoint_association", **stats})
                    results[layer] = result
                pairs.append({"endpoint": endpoint, "support": name, "geography": mode,
                              "contrast": "HIFLD_later minus EIA_Jan2020",
                              **paired_difference(results["EIA_Jan2020"], results["HIFLD_later"], spatial)})
    return pd.DataFrame(fits), pd.DataFrame(pairs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    out = fresh_dir(args.run, "temporal")
    tick = time.monotonic()
    started = datetime.now(timezone.utc)
    books, meta = snapshots()
    projects, _, _ = ledger(books["2024-09"])
    history = first_project_history(books)
    cohort = build_cohort(books, projects, history)
    geometry = add_distances(cohort)
    models, pairs = temporal_models(cohort)
    missing = lost_identity_candidates(cohort, books["2024-09"])
    assert cohort[SITE].is_unique
    assert len(cohort) == cohort["seen_2024-09"].sum() + len(missing)
    assert cohort["legacy_48_candidate"].sum() == 48
    csv(cohort, out, "landmark2020_cohort")
    csv(missing, out, "lost_ids")
    csv(history, out, "pipeline_snapshot_history")
    csv(models, out, "landmark2020_models")
    if len(pairs):
        csv(pairs, out, "landmark2020_layer_contrasts")
    write_json({
        "baseline_end": str(BASE.date()), "common_followup_end": str(END.date()), "snapshots": meta,
        "geometries": geometry, "baseline_sites": len(cohort), "last_snapshot_linked": int(cohort["seen_2024-09"].sum()),
        "last_snapshot_missing": len(missing), "baseline_prior_status": int(cohort["baseline_prior_operated_or_shutdown"].sum()),
        "preexisting_in_later_archive": int(cohort["preexisting_in_later_archive"].sum()),
        "registry_endpoint_counts": {k: int(v) for k, v in cohort["registry_endpoint"].value_counts().items()},
        "screened_endpoint_counts": {k: int(v) for k, v in cohort["evidence_screened_endpoint"].value_counts().items()},
        "external_case_in_window_in_registry_risk": int((cohort["external_case_in_fixed_window"] & cohort["registry_incidence_eligible"]).sum()),
        "energy_labels_baseline": {k: int(v) for k, v in cohort["baseline_electricity_direct_use_proxy"].value_counts().items()},
        "actual_negative_truth_validated": False,
    }, out, "temporal_diagnostics")
    run_provenance(out, started, time.monotonic() - tick, [LMOP, HISTORY, EIA, HIFLD, AUDIT30, AUDIT36, HIST_SCREEN,
                   REPO / "evidence/targeted_sources.csv", REPO / "evidence/targeted_adjudications.csv"])
    print(f"{out}: {time.monotonic() - tick:.2f} seconds")


if __name__ == "__main__":
    main()
