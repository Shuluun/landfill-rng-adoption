"""GHGRP Subpart HH first reporting year for the 26 never_operational facilities to verify.

Local-only signal: zero rows across 2010-2023 -> strong "never built / never collected
gas" signal; a late first year (>=2023) may indicate a new gas-collection install.
Reads yearly CSVs staged under inputs/public/ghgrp_subpart_hh_gas_collection_20261106.
"""
import csv, json, os

BASE = r"<PROJECT_ROOT>"
GHGRP_DIR = os.path.join(BASE, "inputs/public/ghgrp_subpart_hh_gas_collection_20261106")
LIST_CSV = os.path.join(BASE, "outputs/2026-11-09_rng_never_operational_verify/run_002/never_operational_to_verify_26.csv")

YEARS = list(range(2010, 2025))


def norm(v):
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


ids = {}
with open(LIST_CSV, newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        gid = norm(row["GHGRP ID"])
        ids[gid] = {
            "lid": row["Landfill ID"],
            "name": row["Landfill Name"],
            "state": row["State"],
            "status": row["rng_pi_statuses"],
        }

first_year = {g: None for g in ids}
n_rows = {g: 0 for g in ids}

for y in YEARS:
    path = os.path.join(GHGRP_DIR, f"year_{y}.csv")
    if not os.path.exists(path):
        continue
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            fid = norm(row.get("facility_id", ""))
            if fid in ids:
                n_rows[fid] += 1
                if first_year[fid] is None or y < first_year[fid]:
                    first_year[fid] = y

out_rows = []
for gid, meta in ids.items():
    fy = first_year[gid]
    out_rows.append({
        "landfill_id": meta["lid"],
        "ghgrp_id": gid,
        "name": meta["name"],
        "state": meta["state"],
        "lmop_status": meta["status"],
        "ghgrp_first_year": "" if fy is None else fy,
        "ghgrp_n_rows": n_rows[gid],
        "ghgrp_signal": "NO_ROWS" if fy is None else "has_rows",
    })

out_rows.sort(key=lambda r: int(r["landfill_id"]))

out_path = os.path.join(BASE, "outputs/2026-11-09_rng_never_operational_verify/run_002/ghgrp_first_year_26.csv")
with open(out_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    w.writerows(out_rows)

for r in out_rows:
    print(f"LF{r['landfill_id']:>6} {r['ghgrp_id']:>8} {r['ghgrp_signal']:<10} first_year={r['ghgrp_first_year']:<5} nrows={r['ghgrp_n_rows']:>4}  {r['name'][:42]}")

print("\nWROTE", out_path)
