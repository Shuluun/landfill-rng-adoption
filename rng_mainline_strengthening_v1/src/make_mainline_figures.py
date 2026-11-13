"""Render deployment figures and repair the archived GHGRP event-study key mapping."""

import argparse
from datetime import datetime, timezone
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import REPO, ROOT, csv, write_json
from run_main import fresh_dir, run_provenance

NAVY = "#135078"
TEAL = "#04766d"
RUST = "#bc5530"
GRAY = "#6a7077"
STRAT = ROOT / "outputs/2026-11-09_rng_additionality_stratified/run_001/additionality_stratified_summary.json"
FLOW = ROOT / "outputs/2026-11-08_rng_additionality_flow/run_001/additionality_flow_summary.json"
EVENT_KEYS = {
    -5: "pre_le_-5", -4: "k-4", -3: "k-3", -2: "k-2",
    0: "k0", 1: "k1", 2: "k2", 3: "k3", 4: "post_ge_4",
}


def save(fig, out, name):
    for suffix in ("png", "svg"):
        fig.savefig(out / f"{name}.{suffix}", dpi=260)
    plt.close(fig)


def annual(table, out):
    subset = table[table["frame"].eq("fixed_full_frame")]
    groups = [
        ("registered_broad", "Broad registry proxy", RUST, "--"),
        ("registered", "Operational / shutdown proxy", GRAY, ":"),
        ("reconciled", "Reconciled", NAVY, "-"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.1), layout="constrained")
    for label, caption, color, line in groups:
        rows = subset[subset["encoding"].eq(label)].sort_values("year")
        assert len(rows) == 30
        axes[0].plot(rows["year"], rows["annual_events"], label=caption, color=color, ls=line, lw=2)
        axes[1].step(rows["year"], rows["cumulative_events"], where="post", label=caption, color=color, ls=line, lw=2)
        last = rows.iloc[-1]
        for ax, column in zip(axes, ["annual_events", "cumulative_events"], strict=True):
            ax.scatter([2024], [last[column]], color=color, s=24, zorder=3)
            ax.annotate(str(last[column]), (2024, last[column]), xytext=(7, -1), textcoords="offset points", color=color)
    for ax, name in zip(axes, ["A  Annual first events", "B  Cumulative first events"], strict=True):
        ax.set_title(name, loc="left", weight="bold")
        ax.set(xlabel="Calendar year", ylabel="Landfills", xlim=(1994.5, 2027))
        ax.set_xticks([1995, 2000, 2005, 2010, 2015, 2020, 2024])
        ax.set_ylim(bottom=0)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncols=3, frameon=False)
    fig.suptitle("Reconciliation changes the timing and count of recorded deployments", fontsize=13)
    save(fig, out, "mainline_fig01_deployments")


def forest(data, out):
    order = [
        ("common_registered_broad", "Broad registry proxy", RUST),
        ("common_registered", "Operational / shutdown", GRAY),
        ("common_status_only", "Status reconciled, registry dates", GRAY),
        ("common_date_only", "Registry status, date review", GRAY),
        ("common_reconciled", "Status and date reconciled", NAVY),
        ("common_scenario_unknown_at_registered_year", "Unresolved cases at registry year", TEAL),
        ("own_state_support_reconciled", "Reconciled, expanded state support", TEAL),
    ]
    indexed = data.set_index("comparison")
    fig, ax = plt.subplots(figsize=(9.7, 4.8), layout="constrained")
    labels = []
    for pos, (key, label, color) in enumerate(order):
        row = indexed.loc[key]
        y = len(order) - pos - 1
        center, lo, hi = row[["doubling_or", "doubling_or_low", "doubling_or_high"]]
        ax.errorbar(center, y, xerr=[[center - lo], [hi - center]], fmt="o", color=color, capsize=3, lw=1.7)
        ax.text(1.041, y, f"{row.n_events:.0f} / {row.n_landfills:,.0f}", va="center", fontsize=9)
        labels.append(label)
    ax.text(1.041, len(order) - 0.3, "Events / sites", fontsize=9, weight="bold")
    ax.axvline(1, color=GRAY, ls="--", lw=1)
    ax.axhline(0.5, color="#cbd2d9", lw=0.8)
    ax.set_yticks(list(range(len(order) - 1, -1, -1)), labels=labels)
    ax.set(xlim=(0.77, 1.155), ylim=(-0.6, len(order)), xlabel="Annual odds ratio per doubling of mapped distance (95% spatial interval)")
    ax.set_title("Distance associations on common geographic support", loc="left", weight="bold")
    save(fig, out, "mainline_fig02_distance")


def landmark(data, out):
    subset = data[data["support"].eq("baseline_wip") & data["model_status"].eq("fit_registry_endpoint_association")]
    layers = [("EIA_Jan2020", "January 2020 EIA", NAVY, -0.12),
              ("HIFLD_later", "HIFLD archived in 2026", RUST, 0.12)]
    blocks = [
        ("registry_endpoint", "pooled_all_regions", "Registry endpoint, all regions"),
        ("registry_endpoint", "region_adjusted_supported_only", "Registry endpoint, supported regions"),
        ("evidence_screened_endpoint", "pooled_all_regions", "Evidence-screened endpoint, all regions"),
        ("evidence_screened_endpoint", "region_adjusted_supported_only", "Evidence-screened endpoint, supported regions"),
    ]
    fig, ax = plt.subplots(figsize=(10, 4.1), layout="constrained")
    labels = []
    for i, (endpoint, mode, text) in enumerate(blocks):
        rows = subset[subset["endpoint"].eq(endpoint) & subset["geography"].eq(mode)].set_index("layer")
        if set(rows.index) != {"EIA_Jan2020", "HIFLD_later"}:
            raise ValueError(f"Missing comparable exposure results for {endpoint} {mode}")
        y = len(blocks) - i - 1
        row = rows.iloc[0]
        labels.append(f"{text}\n{int(row.n_events)} events / {row.n_landfills:,.0f} sites")
        for layer, label, color, offset in layers:
            center, lo, hi = rows.loc[layer, ["doubling_or", "doubling_or_low", "doubling_or_high"]]
            ax.errorbar(center, y + offset, xerr=[[center - lo], [hi - center]], fmt="o",
                        color=color, capsize=3, lw=1.7, label=label if i == 0 else None)
    ax.axvline(1, color=GRAY, ls="--", lw=1)
    ax.set_yticks(list(range(len(blocks) - 1, -1, -1)), labels=labels)
    ax.set_ylim(-0.55, len(blocks) - 0.5)
    ax.set_xlabel("Fixed-endpoint odds ratio per distance doubling (95% spatial interval)")
    ax.set_title("Pipeline layers in the 2020 landmark cohort", loc="left", weight="bold")
    ax.legend(loc="best", frameon=False)
    save(fig, out, "mainline_fig03_landmark")


def reporting(out):
    strat = json.loads(STRAT.read_text(encoding="utf-8"))["results"]
    flow = json.loads(FLOW.read_text(encoding="utf-8"))["event_study"]
    panels = [
        ("Reported methane concentration (pp)", strat["conc__all_ever_operational"]["event_study"], NAVY),
        ("Reported gas flow (log)", flow, RUST),
        ("Reported methane recovery (log)", strat["rec__all_ever_operational"]["event_study"], TEAL),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 7.1), sharex=True, layout="constrained")
    records, old_points = [], []
    for ax, (label, source, color) in zip(axes, panels, strict=True):
        old_points.append(sum(k in source for k in EVENT_KEYS.values()))
        for year, bare in EVENT_KEYS.items():
            key = f"ev_{bare}"
            result = source[key]  # Fail on an absent key rather than render an empty panel.
            records.append({"outcome": label, "event_year": year, "source_key": key, **result})
        selected = pd.DataFrame(records[-len(EVENT_KEYS):])
        assert np.isfinite(selected[["coef", "se"]]).all().all()
        ax.axhline(0, color=GRAY, lw=0.8)
        ax.axvline(-0.5, color=GRAY, ls="--", lw=0.8)
        ax.errorbar(selected["event_year"], selected["coef"], yerr=1.96 * selected["se"],
                    color=color, fmt="o", lw=1.4, capsize=3)
        ax.set_title(label, loc="left")
    axes[-1].set_xticks(range(-5, 5), ["≤−5", "−4", "−3", "−2", "−1 (ref)", "0", "1", "2", "3", "≥4"])
    axes[-1].set_xlabel("Years from registered start")
    fig.suptitle("Supplement  Registry-timed event-study estimates")
    save(fig, out, "mainline_figS01_reported_outcomes")
    csv(pd.DataFrame(records), out, "ghgrp_figure_data")
    return {"legacy_matching_points_by_panel": old_points, "repaired_points_by_panel": [len(EVENT_KEYS)] * 3}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", required=True)
    parser.add_argument("--temporal", required=True)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    out = fresh_dir(args.run, "figures")
    tick = time.monotonic()
    started = datetime.now(timezone.utc)
    main_dir = REPO / "results/mainline" / args.main
    temp_dir = REPO / "results/temporal" / args.temporal
    annual_data = main_dir / "annual_deployments.csv"
    distance_data = main_dir / "deployment_comparisons.csv"
    landmark_data = temp_dir / "landmark2020_models.csv"
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e1e7ee", "grid.linewidth": 0.6,
                         "axes.axisbelow": True, "svg.fonttype": "none"})
    annual(pd.read_csv(annual_data), out)
    forest(pd.read_csv(distance_data), out)
    landmark(pd.read_csv(landmark_data), out)
    ghgrp = reporting(out)
    write_json({"main": args.main, "temporal": args.temporal, **ghgrp}, out, "figure_checks")
    run_provenance(out, started, time.monotonic() - tick, [annual_data, distance_data, landmark_data, STRAT, FLOW])
    print(f"{out}: {time.monotonic() - tick:.2f} seconds")


if __name__ == "__main__":
    main()
