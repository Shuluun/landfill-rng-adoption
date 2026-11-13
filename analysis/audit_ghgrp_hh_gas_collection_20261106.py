"""GHGRP Subpart HH gas collection system details — data gate audit.

Reads inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv
and reports the go/no-go funnel facts: field completeness, wet/dry basis,
facility count, year coverage, and (the decisive one) whether a non-adopter
control group could exist. Stdlib only.
"""
import csv
import collections
import sys

PATH = r"<PROJECT_ROOT>/inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv"

KEY = [
    "annl_avg_methane_concentration",
    "annual_landfill_gas_flow",
    "annual_qty_recoverd_ch4_eq_hh4",
]


def is_nonempty(v):
    if v is None:
        return False
    s = str(v).strip()
    if s == "":
        return False
    return True


def is_positive(v):
    if not is_nonempty(v):
        return False
    try:
        return float(v) > 0
    except ValueError:
        return False


def main():
    rows = []
    with open(PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames
        for r in reader:
            rows.append(r)

    n = len(rows)
    print("TOTAL rows:", n)
    print("COLUMNS:", len(cols))
    print("reported-year values found:", sorted({r.get("reporting_year") for r in rows}))

    # L1 field completeness
    print("\n--- L1 field completeness (non-empty / positive) ---")
    for k in KEY:
        ne = sum(1 for r in rows if is_nonempty(r.get(k)))
        pos = sum(1 for r in rows if is_positive(r.get(k)))
        print(f"  {k}: non-empty {ne} ({100*ne/n:.1f}%), positive {pos} ({100*pos/n:.1f}%)")

    three_ne = sum(1 for r in rows if all(is_nonempty(r.get(k)) for k in KEY))
    three_pos = sum(1 for r in rows if all(is_positive(r.get(k)) for k in KEY))
    print(f"  all three non-empty: {three_ne} ({100*three_ne/n:.1f}%)")
    print(f"  all three positive : {three_pos} ({100*three_pos/n:.1f}%)")

    # facility count / year coverage
    fac = {r.get("facility_id") for r in rows}
    fac_year = {(r.get("facility_id"), r.get("reporting_year")) for r in rows}
    print(f"\nunique facility_id: {len(fac)}")
    print(f"unique facility-year: {len(fac_year)}  (dup rows if != total: {n - len(fac_year)})")

    years_per_fac = collections.Counter(r.get("facility_id") for r in rows)
    ge2 = sum(1 for f, c in years_per_fac.items() if c >= 2)
    ge5 = sum(1 for f, c in years_per_fac.items() if c >= 5)
    print(f"facilities with >=2 years of data: {ge2}")
    print(f"facilities with >=5 years of data: {ge5}")

    # L2 wet/dry basis flags
    print("\n--- L2 wet/dry basis flags ---")
    for k in ["ch4_conc_measured_wet_basis", "lndfil_gas_flow_mesr_wet_basis"]:
        c = collections.Counter((r.get(k) or "NULL") for r in rows)
        print(f"  {k}: {dict(c)}")

    # does any facility ever switch wet/dry basis across years?
    def basis_seq(r):
        return r.get("ch4_conc_measured_wet_basis")

    by_fac = collections.defaultdict(set)
    for r in rows:
        by_fac[r.get("facility_id")].add(basis_seq(r))
    switchers = sum(1 for f, s in by_fac.items() if len(s) > 1)
    print(f"  facilities whose conc wet-basis flag changes across years: {switchers}")

    # facility-year with any gas flow: potential 'collecting' population
    flow_pos = sum(1 for r in rows if is_positive(r.get("annual_landfill_gas_flow")))
    print(f"\nfacility-years with positive gas flow (active collection): {flow_pos} ({100*flow_pos/n:.1f}%)")

    # distribution of concentration among positive ones (sanity: %, so ~40-60 typical)
    concs = [float(r["annl_avg_methane_concentration"]) for r in rows
             if is_positive(r.get("annl_avg_methane_concentration"))]
    if concs:
        concs.sort()
        import statistics
        print(f"\nconcentration (positive only) n={len(concs)}: "
              f"min={concs[0]:.1f} p10={concs[len(concs)//10]:.1f} "
              f"median={statistics.median(concs):.1f} max={concs[-1]:.1f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
