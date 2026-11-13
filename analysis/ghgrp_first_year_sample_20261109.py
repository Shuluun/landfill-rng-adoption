"""Compute GHGRP Subpart HH first reporting year for the 30-facility validation sample.

Local-only signal for the external verification protocol step 3:
  - if a GHGRP facility_id has any rows across 2010-2023 -> first reporting year
  - if zero rows -> strong "never built / never collected gas" signal
Reads the yearly CSVs already staged under inputs/public/ghgrp_subpart_hh_gas_collection_20261106.
"""
import csv
import json
import os

BASE = r"<PROJECT_ROOT>"
GHGRP_DIR = os.path.join(BASE, "inputs/public/ghgrp_subpart_hh_gas_collection_20261106")
SAMPLE = os.path.join(BASE, "outputs/2026-11-09_rng_adoption_date_validation_sample/run_001/adoption_date_validation_sample.csv")

YEARS = list(range(2010, 2025))

# facility_id may be int or str; normalize.
def norm(v):
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

# load sample -> set of GHGRP IDs
sample_ids = {}
with open(SAMPLE, newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        gid = norm(row["GHGRP ID"])
        sample_ids[gid] = {
            "rank": row["sample_rank"],
            "name": row["Landfill Name"],
            "state": row["State"],
            "ti": row["Ti"],
            "era": row["era"],
            "type": row["type"],
        }

first_year = {gid: None for gid in sample_ids}
n_rows = {gid: 0 for gid in sample_ids}

for y in YEARS:
    path = os.path.join(GHGRP_DIR, f"year_{y}.csv")
    if not os.path.exists(path):
        continue
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            fid = norm(row.get("facility_id", ""))
            if fid in sample_ids:
                n_rows[fid] += 1
                if first_year[fid] is None or y < first_year[fid]:
                    first_year[fid] = y

out_rows = []
for gid, meta in sample_ids.items():
    fy = first_year[gid]
    out_rows.append({
        "rank": meta["rank"],
        "ghgrp_id": gid,
        "name": meta["name"],
        "state": meta["state"],
        "ti": meta["ti"],
        "era": meta["era"],
        "type": meta["type"],
        "ghgrp_first_year": "" if fy is None else fy,
        "ghgrp_n_rows": n_rows[gid],
        "ghgrp_signal": "NO_ROWS" if fy is None else "has_rows",
    })

out_rows.sort(key=lambda r: int(r["rank"]))

out_path = os.path.join(BASE, "outputs/2026-11-09_rng_adoption_date_validation_sample/run_001/ghgrp_first_year_sample.csv")
with open(out_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
    w.writeheader()
    w.writerows(out_rows)

for r in out_rows:
    print(f"{r['rank']:>2} {r['ghgrp_id']:>8} {r['type']:<18} {r['ghgrp_signal']:<10} first_year={r['ghgrp_first_year']:<5} nrows={r['ghgrp_n_rows']:>3}  {r['name'][:40]}")

print("\nWROTE", out_path)
