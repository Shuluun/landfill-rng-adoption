"""W2 four-way deployment comparison (deliverable #4).

Four event definitions, layered:
  orig    = LMOP raw Operational+Shutdown (ev_opshut_orig)
  status  = + 36-facility audit (add 13 real late adopters)  -> ev_opshut_corr
  date    = + 11 targeted adjudications on orig (remove 966/1465, re-date 1254->2021)
  both    = status + date (fully corrected final map)

Each variant is fit with the SAME calendar-group + state-FE specification on the
SAME common state support (states with 0 < events < size in every variant), so
the paired differences isolate the effect of the event-definition treatment.

Read-only. Writes deployment_comparisons.csv + summary JSON under
results/deployment_comparisons/run_001/.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_event_ledger import NEVER_OP, TARGETED, legacy_book, event_map, build_cohort  # noqa: E402
import model  # noqa: E402
from common import PERIODS, END, SITE, REPO  # noqa: E402

STATUSES = {"Operational", "Shutdown"}


def apply_36(em):
    d = dict(em)
    for lid, (cls, yr) in NEVER_OP.items():
        if cls == "real" and yr is not None and yr <= END:
            d[lid] = yr
    return d


def apply_targeted(em):
    d = dict(em)
    for lid, rule in TARGETED.items():
        if rule["action"] == "remove":
            d.pop(lid, None)
        elif rule["action"] in {"redate", "confirm"}:
            d[lid] = rule["year"]
    return d


def fit_variant(sites, spatial, em, common_states):
    risk = model.make_risk(sites, pd.Series(em), END, periods=PERIODS)
    risk = risk[risk["state"].isin(common_states)].reset_index(drop=True)
    f = model.fit(risk, spatial, state_fe=True, controls=("log_dist", "log_waste"),
                  calendar=True, diagnose=True, ridge=0)
    st = dict(f.stats)
    st["p_cluster"] = float(2 * (1 - norm.cdf(abs(st["ln_distance"] / st["cluster_se"]))))
    st["p_conley100"] = float(2 * (1 - norm.cdf(abs(st["ln_distance"] / st["conley100_se"]))))
    return st, f


def main():
    df = legacy_book()
    cohort, _ = build_cohort()
    cohort = cohort.copy()
    cohort["log_dist"] = np.log(cohort["nearest_pipeline_km_spherical"])
    cohort["log_waste"] = np.log(cohort["waste_tons"])
    sites = cohort[[SITE, "state", "lat", "lon", "entry", "log_dist", "log_waste"]].reset_index(drop=True)
    spatial = model.SpatialWeights(sites)

    ev_orig = {int(k): int(v) for k, v in event_map(df, STATUSES).items()}
    variants = {
        "orig": ev_orig,
        "status": apply_36(ev_orig),
        "date": apply_targeted(ev_orig),
        "both": apply_targeted(apply_36(ev_orig)),
    }

    # common state support: states with 0 < events < size in EVERY variant
    valid_states = None
    per_state = {}
    for name, em in variants.items():
        risk = model.make_risk(sites, pd.Series(em), END, periods=PERIODS)
        g = risk.groupby("state").agg(ev=("y", "sum"), size=("n", "sum"))
        ok = set(g[(g["ev"] > 0) & (g["ev"] < g["size"])].index)
        per_state[name] = {"n_events": int(g["ev"].sum()), "valid_states": sorted(ok)}
        valid_states = ok if valid_states is None else (valid_states & ok)
    common_states = sorted(valid_states)

    fits = {}
    rows = []
    for name, em in variants.items():
        st, f = fit_variant(sites, spatial, em, common_states)
        fits[name] = f
        rows.append({
            "variant": name,
            "n_events": st["n_events"],
            "risk_years": st["risk_years"],
            "n_landfills": st["n_landfills"],
            "n_states": st["n_states"],
            "ln_distance": st["ln_distance"],
            "cluster_se": st["cluster_se"],
            "p_cluster": st["p_cluster"],
            "conley100_se": st["conley100_se"],
            "p_conley100": st["p_conley100"],
            "doubling_or": st["doubling_or"],
            "separation": st["separation"],
            "info_condition": st["info_condition"],
        })

    comparison = pd.DataFrame(rows)

    # paired differences on the common support
    pairs = [("status", "orig"), ("date", "orig"), ("both", "status"), ("both", "orig")]
    paired = []
    for b, a in pairs:
        d = model.paired_difference(fits[a], fits[b], spatial)
        d["comparison"] = f"{b}_vs_{a}"
        paired.append(d)
    paired_df = pd.DataFrame(paired)

    out = REPO / "results" / "deployment_comparisons" / "run_001"
    out.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(out / "deployment_comparisons.csv", index=False, encoding="utf-8-sig")
    paired_df.to_csv(out / "deployment_comparisons_paired.csv", index=False, encoding="utf-8-sig")

    # support-set accounting: which events fall outside the common states
    dropped_events = {}
    for name, em in variants.items():
        risk = model.make_risk(sites, pd.Series(em), END, periods=PERIODS)
        events_out = risk[(risk["y"] == 1) & (~risk["state"].isin(common_states))]
        dropped_events[name] = sorted(events_out[SITE].unique().tolist())

    summary = {
        "common_states": common_states,
        "n_common_states": len(common_states),
        "per_variant_event_counts": {k: v["n_events"] for k, v in per_state.items()},
        "events_dropped_by_common_state": dropped_events,
        "variant_table": rows,
        "paired_differences": paired,
        "note": ("Calendar-group (6 periods) + state FE + log_dist/log_waste, common state support. "
                 "The legacy -0.1687 used year dummies; this calendar-group spec is the scope's "
                 "new comparison design."),
        "ca_note": ("CA has no in-window Operational/Shutdown RNG-PI event in the original map "
                    "(only 4 CA RNG-PI rows: Palos Verdes 1975 Shutdown, Forward 2024 Planned, "
                    "Keller Canyon 2024 Construction, Simi Valley 2025 Construction). Keller Canyon "
                    "(184) is added by the 36-facility audit and is CA's sole event, so it drops out "
                    "of the common-state support (CA zero-event in the original definition)."),
    }
    (out / "deployment_comparisons_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "per_variant_event_counts": summary["per_variant_event_counts"],
        "events_dropped_by_common_state": dropped_events,
        "variant_table": rows,
        "paired_differences": paired,
        "n_common_states": len(common_states),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
