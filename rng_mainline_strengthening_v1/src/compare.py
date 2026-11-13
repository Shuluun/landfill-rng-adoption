"""Compare status, dates, follow-up and geographic support in the 1995–2024 panel."""

import math

import numpy as np
import pandas as pd

from common import EARLY, END, SITE, csv, write_json
from model import CUTOFFS, SpatialWeights, fit, make_risk, paired_difference, support

FACTORIAL = ("registered", "status_only", "date_only", "reconciled")


def compare(sites, all_sites, projects, maps, legacy_trace, out):
    row_states = []
    pre_entry = pd.DataFrame({
        label: sites[SITE].map(years).lt(sites["entry"]) for label, years in maps.items()
    })
    # An event before the recorded opening indicates an eligibility/date conflict.
    # Use a common exclusion rather than treat that site as event-free in one model.
    eligible = sites.loc[~pre_entry.any(axis=1)].copy()
    conflicts = sites.loc[pre_entry.any(axis=1), [SITE, "entry"]].join(pre_entry)
    states = {label: support(eligible, years, END) for label, years in maps.items()}
    common_states = set.intersection(*(states[k] for k in ("registered_broad", *FACTORIAL)))
    common = eligible[eligible["state"].isin(common_states)]
    legacy_frame = all_sites[all_sites["legacy_eligible"]].copy()
    legacy_frame["entry"] = legacy_frame["entry"].astype(int)
    spatial = SpatialWeights(legacy_frame)
    fits = {}
    summaries = []

    def add(name, endpoint, frame, end=END, state_fe=True, diagnose=False,
            controls=("log_dist", "log_waste"), years=None):
        years = maps[endpoint] if years is None else years
        risk = make_risk(frame, years, end)
        model = fit(risk, spatial, state_fe=state_fe, diagnose=diagnose, controls=controls)
        row = {"comparison": name, "encoding": endpoint, "end_year": end, **model.stats}
        fits[name] = model
        summaries.append(row)
        if len(frame) != row["n_landfills"]:
            raise AssertionError(f"Site selection changed after building risk years for {name}")
        return row

    for label in ("registered_broad", *FACTORIAL):
        add(f"common_{label}", label, common, diagnose=True)
    for label in ("registered_broad", "registered", "reconciled"):
        add(f"own_state_support_{label}", label, eligible[eligible["state"].isin(states[label])], diagnose=True)
    add("common_reconciled_no_snapshot_wip", "reconciled", common, controls=("log_dist",), diagnose=True)
    legacy_map = maps["registered"].copy()
    legacy_additions = legacy_trace.set_index(SITE)["ev_opshut_corr"].dropna()
    legacy_map = pd.concat([legacy_map[~legacy_map.index.isin(legacy_additions.index)], legacy_additions])
    legacy_states = support(legacy_frame, legacy_map, END)
    bridge = add("bridge_legacy_labels_fixed_calendar", "legacy_reconciled",
                 legacy_frame[legacy_frame["state"].isin(legacy_states)], years=legacy_map, diagnose=True)
    assert (bridge["n_landfills"], bridge["risk_years"], bridge["n_events"]) == (1502, 43593, 121)
    add("bridge_legacy_labels_fixed_calendar_exclude_prewindow", "legacy_reconciled",
        eligible[eligible["state"].isin(legacy_states)], years=legacy_map, diagnose=True)
    for label in ("registered", "reconciled"):
        add(f"all_geography_pooled_{label}", label, eligible, state_fe=False)
        add(f"common_geography_pooled_{label}", label, common, state_fe=False)
    for label in maps:
        if label.startswith("scenario_"):
            add(f"common_{label}", label, common)

    # Trim to a complete calendar year before the last September snapshot.
    early_states = set.intersection(*(support(common, maps[k], 2023) for k in ("registered", "reconciled")))
    early_common = common[common["state"].isin(early_states) & common["entry"].le(2023)]
    for label in ("registered", "reconciled"):
        add(f"matched_window_through2023_{label}", label, early_common, end=2023)
        add(f"matched_window_through2024_{label}", label, early_common, end=2024)

    pairs = [
        ("state_stage_at_registry_dates", "common_registered", "common_status_only"),
        ("date_stage_at_registry_status", "common_registered", "common_date_only"),
        ("date_stage_after_status", "common_status_only", "common_reconciled"),
        ("status_stage_after_date", "common_date_only", "common_reconciled"),
        ("joint_vs_registry_strict", "common_registered", "common_reconciled"),
        ("joint_vs_registry_broad", "common_registered_broad", "common_reconciled"),
        ("joint_change_when_expanding_state_support", "common_reconciled", "own_state_support_reconciled"),
        ("broad_change_when_expanding_state_support", "common_registered_broad", "own_state_support_registered_broad"),
        ("bridge_exclude_prewindow", "bridge_legacy_labels_fixed_calendar",
         "bridge_legacy_labels_fixed_calendar_exclude_prewindow"),
        ("bridge_cutoff_and_event_updates", "bridge_legacy_labels_fixed_calendar_exclude_prewindow",
         "own_state_support_reconciled"),
        ("alliance_assai_2021_as_first", "common_reconciled", "common_scenario_later_milestone"),
    ]
    differences = pd.DataFrame([
        {"contrast": label, "from": a, "to": b, **paired_difference(fits[a], fits[b], spatial)}
        for label, a, b in pairs
    ])
    for state, frame in eligible.groupby("state"):
        row = {"state": state, "eligible_landfills": len(frame), "in_common_support": state in common_states}
        for label in ("registered_broad", *FACTORIAL):
            year = frame[SITE].map(maps[label])
            row[label + "_events"] = int(year.between(frame["entry"], END).sum())
            row[label + "_state_supported"] = state in states[label]
        row_states.append(row)
    state_table = pd.DataFrame(row_states)

    detailed = all_sites[[SITE, "state", "county", "lat", "lon", "opened", "entry", "waste_tons", "waste_year",
                          "nearest_pipeline_km_spherical", "eligibility", "legacy_eligible"]].copy()
    detailed["in_fixed_eligible_frame"] = detailed[SITE].isin(eligible[SITE])
    detailed["in_common_support"] = detailed[SITE].isin(common[SITE])
    for label, years in maps.items():
        candidate = detailed[SITE].map(years)
        detailed[label + "_candidate_year"] = candidate.astype("Int64")
        event = candidate.where(
            detailed["in_fixed_eligible_frame"] & candidate.between(detailed["entry"], END)
        )
        detailed[label + "_event"] = event.astype("Int64")
        detailed[label + "_exit"] = event.fillna(END).where(detailed["in_fixed_eligible_frame"]).astype("Int64")
    detail_cols = ["landfill_name", SITE, "source_ids", "project_id"]
    index = projects[detail_cols].groupby(SITE).agg({
        "landfill_name": "first",
        "source_ids": lambda c: ";".join(dict.fromkeys(s for t in c for s in t.split(";") if s)),
        "project_id": lambda c: ";".join(dict.fromkeys(c.dropna())),
    }).rename(columns={"project_id": "project_ids"})
    detailed = detailed.merge(index, on=SITE, how="left", validate="one_to_one")
    changed = detailed[
        detailed["registered_broad_event"].fillna(-1).ne(detailed["reconciled_event"].fillna(-1))
        | detailed["registered_event"].fillna(-1).ne(detailed["reconciled_event"].fillna(-1))
        | detailed["eligibility"].eq("verified_pre1995_operation")
        | detailed[SITE].isin(conflicts[SITE])
    ].copy()
    changed["adjudications"] = changed[SITE].map(
        projects.groupby(SITE)["evidence_status"].agg(lambda c: ";".join(dict.fromkeys(c)))
    )

    year_rows = []
    for frame_name, frame in (
        ("fixed_full_frame", detailed[detailed["in_fixed_eligible_frame"]]),
        ("fixed_common_state_frame", detailed[detailed["in_common_support"]]),
    ):
        for label in ("registered_broad", *FACTORIAL, "scenario_unknown_at_registered_year"):
            counts = frame[label + "_event"].value_counts().reindex(range(EARLY, END + 1), fill_value=0)
            for year, n, cumul in zip(counts.index, counts, counts.cumsum(), strict=True):
                year_rows.append({"frame": frame_name, "encoding": label, "year": year,
                                  "annual_events": int(n), "cumulative_events": int(cumul)})

    main = fits["common_reconciled"]
    system_meta = projects.loc[projects["linked_parent"] | projects["physical_system_id"].ne(""),
                               [SITE, "parent_project_id", "physical_system_id", "system_relationship"]].drop_duplicates()
    groups = system_meta.groupby("parent_project_id")[SITE].agg(lambda s: sorted(set(s)))
    linked = set(system_meta[SITE])
    shared_rows = []
    for parent, members in groups.items():
        kept = sorted(set(members) & set(common[SITE]))
        row = {"parent_project_id": parent, "registry_member_ids": ";".join(map(str, members)),
               "common_support_members": ";".join(map(str, kept)), "n_members_in_common": len(kept)}
        if len(kept) >= 2:
            alt = common[~common[SITE].isin(kept)]
            if support(alt, maps["reconciled"], END) == common_states:
                model = add(f"omit_linked_parent_{parent}", "reconciled", alt)
                row["ln_distance_after_omitting_group"] = model["ln_distance"]
        shared_rows.append(row)
    without_linked = common[~common[SITE].isin(linked)]
    if support(without_linked, maps["reconciled"], END) == common_states:
        add("omit_all_shared_parent_candidates", "reconciled", without_linked, diagnose=True)

    # Examine the largest site score influences, including non-events.
    ordered = main.influence.abs().nlargest(8)
    influence_rows = []
    for lid in ordered.index:
        alt = common[common[SITE].ne(lid)]
        state_supported = support(alt, maps["reconciled"], END) == common_states
        if state_supported:
            row = add(f"omit_landfill_{lid}", "reconciled", alt)
        else:
            # Explicitly disclose if a state loses its only event.
            alt = alt[alt["state"].isin(support(alt, maps["reconciled"], END))]
            row = add(f"omit_landfill_{lid}_and_lost_state", "reconciled", alt)
        influence_rows.append({SITE: lid, "score_influence": main.influence[lid],
                               "common_states_retained": state_supported, **row})
    largest_state = state_table.loc[state_table["in_common_support"]].sort_values(
        ["reconciled_events", "state"], ascending=[False, True]).iloc[0]["state"]
    add(f"omit_highest_event_state_{largest_state}", "reconciled", common[common["state"].ne(largest_state)])

    # Make known or possible linked-parent contributions fully correlated within
    # their group by using a representative centroid, as a sensitivity.
    membership = {lid: str(lid) for lid in common[SITE]}
    for parent, members in groups.items():
        for lid in set(members) & set(membership):
            if membership[lid] != str(lid):
                raise ValueError("Overlapping shared parent groups require an explicit system crosswalk")
            membership[lid] = f"linked-{parent}"
    grouped = common.assign(group=common[SITE].map(membership)).groupby("group", as_index=False)[["lat", "lon"]].mean()
    grouped = grouped.rename(columns={"group": SITE})
    grouped_score = main.influence.groupby(main.influence.index.map(membership)).sum()
    grouped_spatial = SpatialWeights(grouped)
    sensitivity = pd.DataFrame([
        {"cutoff_km": cutoff, "conley_se_site_scores": math.sqrt(spatial.variance(main.influence, cutoff)),
         "conley_se_shared_parent_scores": math.sqrt(grouped_spatial.variance(grouped_score, cutoff))}
        for cutoff in CUTOFFS
    ])
    out_frame = pd.DataFrame(summaries)
    assert out_frame["comparison"].is_unique
    for label in ("registered_broad", *FACTORIAL):
        row = out_frame.set_index("comparison").loc[f"common_{label}"]
        expected = detailed.loc[detailed["in_common_support"], label + "_event"].notna().sum()
        assert row["n_events"] == expected
    csv(out_frame, out, "deployment_comparisons")
    csv(differences, out, "paired_deployment_differences")
    csv(pd.DataFrame(year_rows), out, "annual_deployments")
    csv(state_table, out, "state_support")
    csv(detailed, out, "site_risk_ledger")
    csv(changed, out, "changed_landfill_events")
    csv(pd.DataFrame(shared_rows), out, "shared_parent_sensitivity")
    csv(pd.DataFrame(influence_rows), out, "site_influence")
    csv(sensitivity, out, "spatial_sensitivity")
    wip = common["waste_year"]
    events = common[SITE].map(maps["reconciled"])
    observed = events.between(common["entry"], END)
    def integer_or_none(value):
        return int(value) if pd.notna(value) else None
    write_json({
        "eligible_before_opening_conflict_check": len(sites),
        "preopening_conflicts": conflicts[SITE].astype(int).tolist(),
        "fixed_eligible_sites": len(eligible), "fixed_common_sites": len(common),
        "common_states": sorted(common_states),
        "full_frame_states": sorted(eligible["state"].unique()),
        "wip_year_min": integer_or_none(wip.min()), "wip_year_max": integer_or_none(wip.max()),
        "wip_year_missing": int(wip.isna().sum()),
        "reconciled_events_with_wip_year_after_event": int((observed & wip.gt(events)).sum()),
        "reconciled_events_missing_wip_year": int((observed & wip.isna()).sum()),
        "largest_event_state": largest_state,
        "ambiguous_date_scenarios_are_hypotheses": True,
        "shared_parent_is_candidate_group_except_documented_links": True,
    }, out, "deployment_diagnostics")
