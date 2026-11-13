"""Build the full event ledger + source ledger (deliverable #3).

Event provenance is layered, in application order:
  L0  LMOP raw           -> ev_opshut_orig  (Operational+Shutdown, min start year in [1995,2024])
  L1  36-facility audit  -> add 13 real late adopters (ev_opshut_corr)
  L2  11 targeted adjudications -> remove 966/1465 (prewindow), re-date 1254 -> 2021,
                                  confirm 1256/1606/516, flag 838/12144/2001 unknown-cutoff.

The fitted driver model counts only sites in the analyzable CONUS cohort with
entry <= event year, so the map size (122 after L1) differs from the fitted
event count (121). The ledger records every final event with its cohort flag.

Read-only. Writes event_ledger.csv + source_ledger.csv + summary JSON under
results/event_ledger/run_001/.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, ROOT, LMOP, LANDFILLS, DISTANCES, AUDIT30, AUDIT36  # noqa: E402

RNG_CATEGORY = "Renewable Natural Gas"
RNG_METHODS = {"Pipeline Injection", "Local Use"}
CONTINENTAL = set(
    "AL AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
ERA_START, CENSOR_YEAR = 1995, 2024

NEVER_OP = {
    9: ("real", 2025), 20: ("real", 2025), 184: ("real", 2024),
    460: ("false", None), 495: ("false", None), 554: ("real", 2024),
    559: ("real", 2023), 679: ("real", 2024), 688: ("real", 2024),
    705: ("false", None), 816: ("false", None), 829: ("real", 2025),
    838: ("real", 2024), 945: ("false", None), 1080: ("uncertain", None),
    1150: ("uncertain", None), 1223: ("false", None), 1238: ("false", None),
    1415: ("real", 2025), 1539: ("uncertain", None), 1624: ("real", 2024),
    1819: ("false", None), 2001: ("real", 2024), 2048: ("real", 2024),
    2068: ("real", 2025), 2165: ("real", 2025), 2323: ("real", 2024),
    2336: ("real", 2024), 2424: ("false", None), 2429: ("real", 2024),
    10407: ("false", None), 10520: ("real", 2026), 10620: ("real", 2025),
    11120: ("false", None), 12144: ("real", 2024), 21203: ("real", 2025),
}

# 11 targeted adjudications, encoded as rules (from evidence/targeted_adjudications.csv).
TARGETED = {
    966:  dict(action="remove", sources="FRESH_NYC;FRESH_EPA",
              reason="prewindow: first high-Btu pipeline LFG 1982 (<1995); 1037-1..5 are expansions/de-expansions"),
    1465: dict(action="remove", sources="MCCARTY_SEC;MCCARTY_2021",
              reason="prewindow: commercial 1986 (<1995); 2021 facility is separately numbered, not a landfill first"),
    1254: dict(action="redate", year=2021, sources="ASSAI_2021;ASSAI_PA",
              reason="confirmed co-supplier to shared Assai plant (2021-12-30); supersedes 1998 'Other' row"),
    1256: dict(action="confirm", year=2021, sources="ASSAI_2021;ASSAI_PA",
              reason="confirmed co-supplier/site of shared Assai plant (2021-12-30)"),
    1606: dict(action="confirm", year=2010, sources="CEDAR_2010",
              reason="documented full operation Oct 2010; 2009 first sales are a milestone sensitivity"),
    516:  dict(action="confirm", year=2015, sources="MILAM_WM",
              reason="retain registry date; 2014 release announces expected, not completed, injection"),
    838:  dict(action="flag_uncertain", year=2024, sources="LEMONS_PSC;LEMONS_NOV",
              reason="unknown cutoff: Nov 2024 ceremony preceded actual ops; dated filing after 2024 cutoff"),
    12144: dict(action="flag_uncertain", year=2024, sources="QUAD_PINE;QUAD_AVISTA",
              reason="unknown cutoff: current injection documented; forecast/undated operation straddle cutoff"),
    1539: dict(action="flag_uncertain", year=None, sources="BAY_PINE;BAY_AVISTA",
              reason="unknown cutoff: identity/eventual injection supported; early-2024 production forecast not observed"),
    2001: dict(action="flag_uncertain", year=2024, sources="NCES_SEC;NCES_OFFTAKE",
              reason="unknown cutoff: operator filing uses future construction; offtake describes future supply"),
    1150: dict(action="flag_uncertain", year=None, sources="WAYNE_NCDEQ",
              reason="unknown cutoff: existing electricity + prospective RNG conversion; operation date unresolved"),
}


def legacy_book():
    df = pd.read_excel(LMOP, sheet_name="LMOP Database")
    df["excel_row"] = df.index + 2
    df["Project Start Date"] = pd.to_datetime(df["Project Start Date"], errors="coerce")
    df["status"] = df["Current Project Status"].astype(str).str.strip()
    return df


def event_map(df, statuses):
    is_rng = df["Project Type Category"].eq(RNG_CATEGORY) | df["RNG Delivery Method"].isin(RNG_METHODS)
    pi = df["RNG Delivery Method"].eq("Pipeline Injection")
    rp = df[is_rng & pi].copy()
    rp["sy"] = pd.to_datetime(rp["Project Start Date"], errors="coerce").dt.year
    rp = rp[rp["status"].isin(statuses)]
    rp = rp[(rp["sy"] >= ERA_START) & (rp["sy"] <= CENSOR_YEAR)]
    return rp.groupby("Landfill ID")["sy"].min()


def supporting_rows(df, lid, statuses):
    is_rng = df["Project Type Category"].eq(RNG_CATEGORY) | df["RNG Delivery Method"].isin(RNG_METHODS)
    pi = df["RNG Delivery Method"].eq("Pipeline Injection")
    rp = df[is_rng & pi]
    rp = rp[(rp["Landfill ID"] == lid) & (rp["status"].isin(statuses))]
    rp = rp[pd.to_datetime(rp["Project Start Date"], errors="coerce").dt.year.between(ERA_START, CENSOR_YEAR)]
    return rp


def build_cohort():
    lf = pd.read_csv(LANDFILLS)
    dist = pd.read_csv(DISTANCES)[["Landfill ID", "nearest_pipeline_km_spherical", "pipeline_covered"]]
    m = lf.merge(dist, on="Landfill ID", how="left")
    m["has_open"] = m["opened"].notna() & (m["opened"] > 0)
    m["continental"] = m["state"].isin(CONTINENTAL)
    m["has_waste"] = m["waste_tons"].notna() & (m["waste_tons"] > 0)

    df = legacy_book()
    is_rng = df["Project Type Category"].eq(RNG_CATEGORY) | df["RNG Delivery Method"].isin(RNG_METHODS)
    pi = df["RNG Delivery Method"].eq("Pipeline Injection")
    rng_pi = df[is_rng & pi].copy()
    rng_pi["sy"] = pd.to_datetime(rng_pi["Project Start Date"], errors="coerce").dt.year
    all_pi = rng_pi.dropna(subset=["sy"]).groupby("Landfill ID")["sy"].agg(lambda s: sorted(set(s)))
    bad_date_only = set(all_pi[all_pi.apply(lambda yrs: all(y < ERA_START for y in yrs))].index.tolist())

    cohort = m[m["analyzable"] & m["has_coord"] & m["continental"] & (m["pipeline_covered"] == True)
               & m["has_waste"] & m["has_open"] & ~m["Landfill ID"].isin(bad_date_only)].copy()
    cohort["entry"] = np.maximum(cohort["opened"].astype(int), ERA_START)
    return cohort, set(cohort["Landfill ID"].astype(int))


def main():
    df = legacy_book()
    lf_attrs = df.groupby("Landfill ID").agg(
        landfill_name=("Landfill Name", "first"),
        ghgrp_id=("GHGRP ID", "first"),
        state=("State", "first"),
    )
    cohort, cohort_ids = build_cohort()
    county_map = pd.read_csv(LANDFILLS).set_index("Landfill ID")["county"].to_dict()

    statuses = {"Operational", "Shutdown"}
    ev_orig = {int(k): int(v) for k, v in event_map(df, statuses).items()}

    # L1: 36-facility correction
    ev_36 = dict(ev_orig)
    for lid, (cls, yr) in NEVER_OP.items():
        if cls == "real" and yr is not None and yr <= CENSOR_YEAR:
            ev_36[lid] = yr

    # L2: 11 targeted adjudications
    ev_final = dict(ev_36)
    for lid, rule in TARGETED.items():
        if rule["action"] == "remove":
            ev_final.pop(lid, None)
        elif rule["action"] in {"redate", "confirm"}:
            ev_final[lid] = rule["year"]
        # flag_uncertain leaves the map value unchanged; recorded as a flag below

    # ---- build ledger rows over every site touched by any layer ----
    touched = set(ev_orig) | set(ev_36) | set(TARGETED)
    rows = []
    for lid in sorted(touched):
        orig = ev_orig.get(lid)
        after36 = ev_36.get(lid)
        final = ev_final.get(lid)
        rule = TARGETED.get(lid)

        # correction path (cumulative, in application order)
        steps = []
        final_status = "event"
        if lid in ev_orig:
            steps.append("lmop")
        if lid in NEVER_OP and NEVER_OP[lid][0] == "real" and NEVER_OP[lid][1] is not None and NEVER_OP[lid][1] <= CENSOR_YEAR:
            steps.append("audit36_added")
        if rule:
            if rule["action"] == "remove":
                steps.append("targeted_removed"); final_status = "removed_prewindow"
            elif rule["action"] in {"redate", "confirm"}:
                steps.append("targeted_" + rule["action"]); final_status = "event"
            elif rule["action"] == "flag_uncertain":
                steps.append("targeted_flag_uncertain")
                final_status = "event_uncertain_cutoff" if rule.get("year") is not None else "uncertain_no_event"
        path = "->".join(steps) if steps else "lmop_direct"

        # supporting LMOP rows for the *final* year (or the orig year if removed)
        sup = supporting_rows(df, lid, statuses)
        sup = sup.sort_values("Project Start Date")
        if final is not None:
            sup_year = sup[pd.to_datetime(sup["Project Start Date"], errors="coerce").dt.year == final]
            if sup_year.empty:  # e.g. re-dated event: keep the row(s) matching the adjudicated year
                sup_year = sup[pd.to_datetime(sup["Project Start Date"], errors="coerce").dt.year == final]
        else:
            sup_year = sup

        if not sup_year.empty:
            pids = ";".join(str(x) for x in sup_year["Project ID"].astype(str).tolist())
            sts = ";".join(str(x) for x in sup_year["status"].tolist())
            dates = ";".join(str(x.date()) if pd.notna(x) else "" for x in sup_year["Project Start Date"].tolist())
        else:
            pids = sts = dates = ""

        in_cohort = lid in cohort_ids
        entry = cohort.loc[cohort["Landfill ID"].astype(int) == lid, "entry"]
        entry = int(entry.iloc[0]) if len(entry) else None
        counted = bool(final is not None and in_cohort and entry is not None and entry <= final)

        rows.append({
            "landfill_id": lid,
            "landfill_name": lf_attrs.loc[lid, "landfill_name"] if lid in lf_attrs.index else "",
            "ghgrp_id": lf_attrs.loc[lid, "ghgrp_id"] if lid in lf_attrs.index else "",
            "state": lf_attrs.loc[lid, "state"] if lid in lf_attrs.index else "",
            "county": county_map.get(lid, ""),
            "final_status": final_status,
            "event_year_final": final if pd.notna(final) else "",
            "event_year_orig": orig if pd.notna(orig) else "",
            "event_year_after36": after36 if pd.notna(after36) else "",
            "supporting_project_ids": pids,
            "supporting_statuses": sts,
            "supporting_start_dates": dates,
            "correction_path": path,
            "correction_note": rule["reason"] if rule else "",
            "source_ids": rule["sources"] if rule else "",
            "in_driver_cohort": in_cohort,
            "counted_in_fitted_model": counted,
        })

    ledger = pd.DataFrame(rows)

    # ---- source ledger: targeted + audit30 + audit36 ----
    cols = ["source_set", "source_id", "landfill_id", "ghgrp_id", "source_url",
            "publication_date", "locator", "paraphrase", "kind"]

    tsrc = pd.read_csv(REPO / "evidence" / "targeted_sources.csv")
    trows = pd.DataFrame({
        "source_set": "targeted",
        "source_id": tsrc["source_id"],
        "landfill_id": tsrc["landfill_id"].astype(str),
        "ghgrp_id": "",
        "source_url": tsrc["source_url"],
        "publication_date": tsrc["publication_date"].fillna(""),
        "locator": tsrc["locator"].fillna(""),
        "paraphrase": tsrc["paraphrase"].fillna(""),
        "kind": tsrc["kind"].fillna(""),
    })

    a30 = pd.read_csv(AUDIT30)
    a30rows = pd.DataFrame({
        "source_set": "audit30",
        "source_id": "A30_" + a30["sample_rank"].astype(str),
        "landfill_id": a30["Landfill ID"].astype(str),
        "ghgrp_id": a30["GHGRP ID"].astype(str),
        "source_url": a30["ext_source_url"].fillna(""),
        "publication_date": "",
        "locator": a30["ext_verdict"].fillna(""),
        "paraphrase": a30["ext_notes"].fillna(""),
        "kind": a30["ext_source_type"].fillna(""),
    })

    a36 = pd.read_csv(AUDIT36)
    a36rows = pd.DataFrame({
        "source_set": "audit36",
        "source_id": "A36_" + a36["Landfill ID"].astype(str),
        "landfill_id": a36["Landfill ID"].astype(str),
        "ghgrp_id": a36["GHGRP ID"].astype(str),
        "source_url": a36["ext_source_url"].fillna(""),
        "publication_date": "",
        "locator": a36["class"].fillna(""),
        "paraphrase": a36["ext_notes"].fillna(""),
        "kind": a36["ext_source_type"].fillna(""),
    })

    src_ledger = pd.concat([trows, a30rows, a36rows], ignore_index=True)[cols]
    src_ledger = src_ledger[src_ledger["source_url"].astype(str).str.strip() != ""].reset_index(drop=True)

    # ---- summary + write ----
    out = REPO / "results" / "event_ledger" / "run_001"
    out.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(out / "event_ledger.csv", index=False, encoding="utf-8-sig")
    src_ledger.to_csv(out / "source_ledger.csv", index=False, encoding="utf-8-sig")

    n_final_events = int(ledger["final_status"].isin(["event", "event_uncertain_cutoff"]).sum())
    n_counted = int(ledger["counted_in_fitted_model"].sum())
    n_flagged = int((ledger["final_status"] == "event_uncertain_cutoff").sum())
    n_removed = int((ledger["final_status"] == "removed_prewindow").sum())
    n_uncertain = int((ledger["final_status"] == "uncertain_no_event").sum())
    summary = {
        "event_map_counts": {
            "ev_opshut_orig_map": len(ev_orig),
            "ev_opshut_corr_map_after36": len(ev_36),
            "ev_opshut_final_map_after11": len(ev_final),
            "final_events_in_map": n_final_events,
            "final_event_uncertain_cutoff": n_flagged,
            "final_uncertain_no_event": n_uncertain,
            "final_removed_prewindow": n_removed,
            "counted_in_fitted_driver_model": n_counted,
        },
        "redated": {1254: {"from": ev_orig.get(1254), "to": ev_final.get(1254)}},
        "removed": {966: ev_orig.get(966), 1465: ev_orig.get(1465)},
        "note": ("Map size != fitted count: the driver model counts only analyzable CONUS "
                 "cohort sites with entry <= event year."),
    }
    (out / "event_ledger_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n--- ledger shape:", ledger.shape, "| source ledger shape:", src_ledger.shape)


if __name__ == "__main__":
    main()
