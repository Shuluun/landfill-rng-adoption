"""Join registered pipeline projects to the two audits and targeted public evidence."""

import numpy as np
import pandas as pd

from common import AUDIT30, AUDIT36, BROAD, CONUS, DISTANCES, EARLY, END, LANDFILLS, LMOP, OP, REPO, ROOT, SITE
from common import pipeline_rows


def evidence_tables():
    rows = [{
        "source_id": "LMOP_2024", "landfill_id": "", "source_url": "https://www.epa.gov/system/files/documents/2024-09/lmopdata.xlsx",
        "publication_date": "", "locator": "LMOP Database sheet; exact Excel row in event ledger",
        "local_record": LMOP.relative_to(ROOT).as_posix(), "kind": "federal_registry",
        "audit_design": "September 2024 composite snapshot", "review": "frozen_registry_not_event_validation",
    }]
    audits = {}
    for label, path, design in (
        ("A30", AUDIT30, "stratified_draw_from_145"),
        ("A36", AUDIT36, "targeted_planned_or_construction"),
    ):
        table = pd.read_csv(path, dtype={"ext_first_gas_year": "string", "ext_first_gas_date": "string"})
        audits[label] = table
        for i, row in table.iterrows():
            lid = int(row[SITE])
            rows.append({
                "source_id": f"{label}_{lid}", "landfill_id": str(lid),
                "source_url": row["ext_source_url"], "publication_date": "",
                "locator": f"CSV line {i + 2}",
                "local_record": path.relative_to(ROOT).as_posix(),
                "paraphrase": row["ext_notes"],
                "kind": row["ext_source_type"], "audit_design": design,
                "review": "inherited_audit_independent_human_review_unrecorded",
            })
    targeted = pd.read_csv(REPO / "evidence/targeted_sources.csv", dtype=str)
    targeted["local_record"] = "evidence/targeted_sources.csv"
    targeted["audit_design"] = "new_targeted_public_source"
    targeted["review"] = "assistant_read_independent_human_review_pending"
    targeted["retrieved_date"] = "2026-11-10"
    return pd.concat([pd.DataFrame(rows), targeted], ignore_index=True), audits


def ledger(book):
    sources, audits = evidence_tables()
    decisions = pd.read_csv(REPO / "evidence/targeted_adjudications.csv",
                            dtype={"parent_project_id": "string"}).set_index("landfill_id")
    p = pipeline_rows(book)
    p = p.rename(columns={
        "Landfill Name": "landfill_name", "State": "state", "Project ID": "project_id",
        "GHGRP ID": "ghgrp_id", "Project Name": "project_name",
        "Project Start Date": "registered_date", "Project Shutdown Date": "registered_shutdown",
        "Current Project Status": "registry_status", "RNG Delivery Method": "delivery",
        "Project Type Category": "project_category",
    })
    p = p[[SITE, "landfill_name", "state", "ghgrp_id", "project_id", "parent_project_id",
           "project_name", "registered_date", "registered_shutdown", "registry_status",
           "delivery", "project_category", "excel_row"]].copy()
    p["snapshot_month"] = "2024-09"
    p["registry_source_id"] = "LMOP_2024"
    p["registered_year"] = p["registered_date"].dt.year.astype("Int64")
    p["raw_status_qualified"] = p["registry_status"].isin(OP)
    p["updated_status_qualified"] = p["raw_status_qualified"]
    p["revised_year"] = p["registered_year"].where(p["raw_status_qualified"])
    p["year_min"] = pd.array([None] * len(p), dtype="Int64")
    p["year_max"] = pd.array([None] * len(p), dtype="Int64")
    p["alternative_year"] = pd.array([None] * len(p), dtype="Int64")
    p["date_lower"] = ""
    p["date_upper"] = ""
    p["date_precision"] = "registration_only"
    p["evidence_status"] = np.where(p["raw_status_qualified"], "registry_operated", "registry_nonoperating_stage")
    p["source_ids"] = ""
    p["adjudication"] = "Retain the registered stage and date as registry information."
    p["human_review"] = "not_independently_recorded"
    parent_counts = p.groupby("parent_project_id")[SITE].nunique()
    p["linked_parent"] = p["parent_project_id"].isin(parent_counts[parent_counts.gt(1)].index)
    p["physical_system_id"] = ""
    p["system_relationship"] = np.where(p["linked_parent"], "shared_parent_possible_dependency", "physical_link_unresolved")
    expansion = p["project_name"].str.contains(r"\b(?:De-)?Expansion\b", case=False, na=False)
    aggregate_original = p["project_name"].str.contains(r"\&\s*Expansion", case=False, na=False)
    earlier_parent = p.loc[p["raw_status_qualified"] & ~expansion].groupby(
        [SITE, "parent_project_id"]
    )["registered_date"].min()
    p["milestone"] = "registered_pipeline_project"
    p.loc[~p["raw_status_qualified"], "milestone"] = "plan_or_construction_or_unknown"
    p.loc[expansion & ~aggregate_original, "milestone"] = "registered_expansion_or_supplier_addition"
    for idx in p.index[expansion & ~aggregate_original]:
        row = p.loc[idx]
        prior = earlier_parent.get((row[SITE], row["parent_project_id"]), pd.NaT)
        if pd.notna(prior) and prior < row["registered_date"]:
            p.loc[idx, "milestone"] = "same_landfill_follow_on_expansion"
    earlier_shutdown = p.loc[p["registry_status"].eq("Shutdown")].groupby(
        [SITE, "parent_project_id"]
    )["registered_shutdown"].min()
    for idx in p.index[p["raw_status_qualified"] & ~expansion]:
        row = p.loc[idx]
        prior_end = earlier_shutdown.get((row[SITE], row["parent_project_id"]), pd.NaT)
        if pd.notna(prior_end) and prior_end < row["registered_date"]:
            p.at[idx, "milestone"] = "same_landfill_possible_restart_or_later_unit"
    p["can_be_first"] = ~p["milestone"].isin({
        "same_landfill_follow_on_expansion", "same_landfill_possible_restart_or_later_unit",
    })
    first_registered_operating = p.loc[p["raw_status_qualified"]].groupby(SITE)["registered_date"].min()
    already_served_in_registry = p["registered_date"].gt(p[SITE].map(first_registered_operating))
    p["registry_role_at_landfill"] = np.select([
        already_served_in_registry & p["raw_status_qualified"],
        p["raw_status_qualified"],
    ], ["later_facility_or_project_at_previously_served_landfill", "earliest_or_undated_registered_operated_record"],
        default="not_registered_as_operated")

    for label, table in audits.items():
        for audit in table.to_dict("records"):
            lid = int(audit[SITE])
            options = p[p[SITE].eq(lid) & p["registered_year"].eq(audit["Ti"])]
            if label == "A36":
                options = options[~options["raw_status_qualified"]]
            else:
                options = options[options["registry_status"].isin(BROAD)]
            if options.empty:
                raise ValueError(f"No original year/project match for {label} {lid}")
            if options["parent_project_id"].nunique() != 1:
                raise ValueError(f"Ambiguous parent project match for {label} {lid}")
            idx = options.sort_values("excel_row").index[0]
            p.at[idx, "source_ids"] = ";".join(filter(None, (p.at[idx, "source_ids"], f"{label}_{lid}")))
            year = pd.to_numeric(audit["ext_first_gas_year"], errors="coerce")
            if label == "A30":
                if (audit["ext_verdict"] == "clean" and p.at[idx, "raw_status_qualified"]
                        and pd.notna(year) and year == audit["Ti"]):
                    p.at[idx, "evidence_status"] = "registry_year_corroborated_inherited"
                    set_date(p, idx, int(year))
                elif audit["ext_verdict"] == "uncertain":
                    p.at[idx, "evidence_status"] = "registry_conflict_retained"
                    p.at[idx, "adjudication"] = "Inherited external conflict. No alternative sustained injection date established."
                elif pd.notna(year) and p.at[idx, "raw_status_qualified"] and year != audit["Ti"]:
                    p.at[idx, "evidence_status"] = "milestone_or_year_discrepancy"
                    p.at[idx, "alternative_year"] = int(year)
                continue

            verdict = audit["class"]
            p.at[idx, "adjudication"] = audit["ext_notes"]
            if verdict == "real_late_adoption" and pd.notna(year):
                p.at[idx, "updated_status_qualified"] = int(year) <= END
                p.at[idx, "revised_year"] = int(year)
                p.at[idx, "evidence_status"] = "dated_operating_evidence_inherited"
                p.at[idx, "milestone"] = "commercial_operation_or_injection_inherited"
                set_date(p, idx, int(year))
            elif verdict == "false_adoption":
                p.at[idx, "evidence_status"] = "no_eligible_event_supported_in_inherited_audit"
                if lid in {495, 705, 10407, 2424}:
                    p.at[idx, "evidence_status"] = "no_confirmed_date_evidence_incomplete"
                    p.at[idx, "alternative_year"] = int(audit["Ti"])
            else:
                p.at[idx, "evidence_status"] = "unknown_cutoff"
                p.at[idx, "alternative_year"] = int(audit["Ti"])

    for lid, d in decisions.iterrows():
        mask = p[SITE].eq(lid)
        if pd.notna(d["parent_project_id"]):
            mask &= p["parent_project_id"].eq(d["parent_project_id"])
        selected = p[mask].sort_values(["registered_date", "excel_row"])
        if selected.empty:
            raise ValueError(f"No registry project matches targeted review {lid}")
        idx = selected.index[0]
        ids = str(d["source_ids"]).split(";")
        if not set(ids).issubset(set(sources["source_id"])):
            raise ValueError(f"Missing source for adjudication {lid}")
        p.at[idx, "source_ids"] = ";".join(filter(None, (p.at[idx, "source_ids"], *ids)))
        p.at[idx, "adjudication"] = d["reason"]
        p.at[idx, "human_review"] = "assistant_read_pending_independent_human_review"
        p.at[idx, "evidence_status"] = d["decision"]
        p.at[idx, "date_lower"] = d["date_lower"] if pd.notna(d["date_lower"]) else ""
        p.at[idx, "date_upper"] = d["date_upper"] if pd.notna(d["date_upper"]) else ""
        p.at[idx, "year_min"] = int(str(d["date_lower"])[:4]) if pd.notna(d["date_lower"]) else pd.NA
        p.at[idx, "year_max"] = int(str(d["date_upper"])[:4]) if pd.notna(d["date_upper"]) else pd.NA
        if pd.notna(d["date_lower"]) and d["date_lower"] == d["date_upper"]:
            p.at[idx, "date_precision"] = "day"
        else:
            p.at[idx, "date_precision"] = {
                966: "year", 1465: "year", 1606: "month", 1808: "month", 11862: "month",
            }.get(int(lid), "bounded_or_open_interval")
        p.at[idx, "alternative_year"] = int(d["scenario_year"]) if pd.notna(d["scenario_year"]) else pd.NA
        if d["decision"] in {"confirmed_year", "prewindow"}:
            p.at[idx, "revised_year"] = int(d["year"])
            p.at[idx, "updated_status_qualified"] = True
            p.at[idx, "milestone"] = "documented_commercial_operation_or_sustained_supply"
        elif d["decision"] == "unknown_cutoff":
            p.at[idx, "revised_year"] = pd.NA
            p.at[idx, "updated_status_qualified"] = False
            p.at[idx, "milestone"] = "first_supply_date_unresolved"
        elif d["decision"] == "confirmed_post_cutoff":
            p.at[idx, "revised_year"] = pd.NA
            p.at[idx, "updated_status_qualified"] = False
            p.at[idx, "milestone"] = "documented_post_cutoff_operation"
        if pd.notna(d["physical_system_id"]):
            p.at[idx, "physical_system_id"] = d["physical_system_id"]
            p.at[idx, "system_relationship"] = "documented_shared_system"

    # Legacy registration uses all rows. Corrected first-event dates cannot
    # originate solely from a known same-site follow-on expansion.
    p["raw_broad_date"] = p["registered_year"].where(p["registry_status"].isin(BROAD))
    p["raw_strict_date"] = p["registered_year"].where(p["raw_status_qualified"])
    p["status_only_date_proxy"] = p["registered_year"].where(p["updated_status_qualified"] & p["can_be_first"])
    p["date_only_year"] = p["revised_year"].fillna(p["registered_year"]).where(
        p["raw_status_qualified"] & p["can_be_first"]
    )
    p["joint_year"] = p["revised_year"].where(p["updated_status_qualified"] & p["can_be_first"])
    p["any_ambiguous_event_scenario"] = p["joint_year"]
    ambiguous = p["evidence_status"].isin({"unknown_cutoff", "no_confirmed_date_evidence_incomplete"})
    p.loc[ambiguous, "any_ambiguous_event_scenario"] = p.loc[ambiguous, "alternative_year"]
    p["earlier_milestone_scenario"] = p["joint_year"]
    earlier = p["alternative_year"].lt(p["joint_year"]).fillna(False)
    p.loc[earlier, "earlier_milestone_scenario"] = p.loc[earlier, "alternative_year"]
    p["later_milestone_scenario"] = p["joint_year"]
    later = p["alternative_year"].gt(p["joint_year"]).fillna(False)
    p.loc[later, "later_milestone_scenario"] = p.loc[later, "alternative_year"]
    p["conflict_exclusion_scenario"] = p["joint_year"].where(p["evidence_status"].ne("registry_conflict_retained"))
    p["event_key"] = p[SITE].astype(str) + "/" + p["project_id"].fillna("no-project") + "/" + p["excel_row"].astype(str)
    return p.sort_values([SITE, "registered_date", "excel_row"]), sources, audits


def set_date(frame, idx, year):
    frame.loc[idx, ["year_min", "year_max"]] = year
    frame.loc[idx, ["date_lower", "date_upper", "date_precision"]] = [f"{year}-01-01", f"{year}-12-31", "year"]


def get_maps(projects):
    fields = {
        "registered_broad": "raw_broad_date", "registered": "raw_strict_date",
        "status_only": "status_only_date_proxy", "date_only": "date_only_year",
        "reconciled": "joint_year", "scenario_unknown_at_registered_year": "any_ambiguous_event_scenario",
        "scenario_early_milestones": "earlier_milestone_scenario",
        "scenario_later_milestone": "later_milestone_scenario",
        "scenario_omit_registry_conflict": "conflict_exclusion_scenario",
    }
    return {
        name: projects.loc[projects[column].ge(EARLY), [SITE, column]].groupby(SITE)[column].min().astype(float)
        for name, column in fields.items()
    }


def sites_and_exclusions(projects):
    sites = pd.read_csv(LANDFILLS)
    dist = pd.read_csv(DISTANCES)[[SITE, "nearest_pipeline_km_spherical", "pipeline_covered"]]
    sites = sites.merge(dist, on=SITE, validate="one_to_one", how="left")
    dated = projects.dropna(subset=["registered_year"])
    early_only = set(dated.groupby(SITE)["registered_year"].max().loc[lambda s: s.lt(EARLY)].index)
    prewindow = set(projects.loc[projects["evidence_status"].eq("prewindow"), SITE])
    sites["entry"] = sites["opened"].clip(lower=EARLY)
    sites["log_dist"] = np.log(sites["nearest_pipeline_km_spherical"].where(sites["nearest_pipeline_km_spherical"].gt(0)))
    sites["log_waste"] = np.log(sites["waste_tons"].where(sites["waste_tons"].gt(0)))
    sites["eligibility"] = np.select([
        ~sites["state"].isin(CONUS),
        ~sites["has_coord"] | ~sites["pipeline_covered"].eq(True) | sites["log_dist"].isna(),
        ~sites["analyzable"] | sites["log_waste"].isna(),
        ~sites["opened"].between(1, END),
        sites[SITE].isin(early_only),
        sites[SITE].isin(prewindow),
    ], ["outside_CONUS", "missing_coordinate_or_distance", "missing_scale_or_denominator",
        "invalid_opening_year", "legacy_early_only", "verified_pre1995_operation"], default="eligible")
    sites["legacy_eligible"] = sites["eligibility"].isin(["eligible", "verified_pre1995_operation"])
    eligible = sites[sites["eligibility"].eq("eligible")].copy()
    eligible["entry"] = eligible["entry"].astype(int)
    return eligible, sites
