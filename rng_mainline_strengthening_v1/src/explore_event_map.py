"""Explore the current event maps vs the 11 targeted adjudications + 30/36 audits."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import LMOP, SITE, read_book  # noqa: E402

RNG_CATEGORY = "Renewable Natural Gas"
RNG_METHODS = {"Pipeline Injection", "Local Use"}
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

TARGETED = {
    966: "prewindow", 1465: "prewindow", 838: "unknown_cutoff", 12144: "unknown_cutoff",
    1539: "unknown_cutoff", 2001: "unknown_cutoff", 1606: "confirmed_year_2010",
    516: "retain_registry_2015", 1150: "unknown_cutoff", 1254: "confirmed_year_2021",
    1256: "confirmed_year_2021",
}


def main():
    df = read_book(LMOP)
    is_rng = df["Project Type Category"].eq(RNG_CATEGORY) | df["RNG Delivery Method"].isin(RNG_METHODS)
    pi = df["RNG Delivery Method"].eq("Pipeline Injection")
    rng_pi = df[is_rng & pi].copy()
    rng_pi["sy"] = pd.to_datetime(rng_pi["Project Start Date"], errors="coerce").dt.year
    rng_pi["status"] = rng_pi["Current Project Status"].astype(str).str.strip()

    def ev_year(statuses):
        sub = rng_pi[rng_pi["status"].isin(statuses)]
        sub = sub[(sub["sy"] >= ERA_START) & (sub["sy"] <= CENSOR_YEAR)]
        return sub.groupby(SITE)["sy"].min()

    ev_opshut = ev_year({"Operational", "Shutdown"})
    ev_all = ev_year({"Operational", "Shutdown", "Planned", "Construction"})

    def correct(em, for_evall):
        d = {int(k): int(v) for k, v in em.items()}
        for lid, (cls, yr) in NEVER_OP.items():
            if cls == "real" and yr is not None and yr <= CENSOR_YEAR:
                d[lid] = yr
            elif for_evall:
                d.pop(lid, None)
        return d

    ev_os_orig = {int(k): int(v) for k, v in ev_opshut.items()}
    ev_os_corr = correct(ev_opshut, False)
    ev_all_corr = correct(ev_all, True)

    print(f"ev_opshut_orig events = {len(ev_os_orig)}")
    print(f"ev_opshut_corr events = {len(ev_os_corr)}")
    print(f"ev_all_corr events    = {len(ev_all_corr)}")
    print()

    # --- targeted 11: current year in each map + their LMOP RNG-PI rows ---
    print("=== 11 targeted adjudications: current state + LMOP RNG-PI rows ===")
    for lid in sorted(TARGETED):
        rows = rng_pi[rng_pi[SITE].eq(lid)].sort_values("Project Start Date")
        print(f"\n--- {lid} (decision={TARGETED[lid]}) ---")
        print(f"  ev_opshut_orig={ev_os_orig.get(lid)}  ev_opshut_corr={ev_os_corr.get(lid)}  "
              f"ev_all_corr={ev_all_corr.get(lid)}")
        if rows.empty:
            print("  (no RNG-PI rows in LMOP)")
            continue
        for _, r in rows.iterrows():
            print(f"  PID={r['Project ID']} status={r['status']} start={r['Project Start Date']} "
                  f"sy={r['sy']} delivery={r['RNG Delivery Method']} excel_row={r['excel_row']}")

    # --- 30-sample + 36 sites: final event-year status in corrected maps ---
    audit30 = pd.read_csv(Path(LMOP).parents[3] / "outputs/2026-11-09_rng_adoption_date_validation_sample/run_001/full_verification_30.csv")
    print("\n=== 30-sample audit: current event year in corrected map ===")
    for _, r in audit30.iterrows():
        lid = int(r["Landfill ID"])
        print(f"  {lid:>6} Ti={r['Ti']} ext_year={r['ext_first_gas_year']} verdict={r['ext_verdict']} "
              f"-> ev_os_corr={ev_os_corr.get(lid)}")

    print("\n=== 36-facility audit: current event year in corrected map ===")
    for lid in sorted(NEVER_OP):
        cls, yr = NEVER_OP[lid]
        print(f"  {lid:>6} class={cls:<9} corrected_year={yr} -> ev_os_corr={ev_os_corr.get(lid)}")

    # overlap of the three groups
    t = set(TARGETED)
    a30 = set(audit30["Landfill ID"].astype(int))
    a36 = set(NEVER_OP)
    print(f"\n=== overlaps: targeted={len(t)}  audit30={len(a30)}  audit36={len(a36)} ===")
    print(f"  targeted ∩ audit30 = {sorted(t & a30)}")
    print(f"  targeted ∩ audit36 = {sorted(t & a36)}")
    print(f"  audit30 ∩ audit36   = {sorted(a30 & a36)}")


if __name__ == "__main__":
    main()
