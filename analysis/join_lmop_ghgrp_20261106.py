"""Step 1 of the JOIN gate: characterize LMOP's GHGRP ID linkage field and
measure the direct match against GHGRP Subpart HH facility_ids.

Read-only: LMOP xlsx + already-downloaded GHGRP CSV in inputs/public/. No network.
Answers three questions:
  1. What does the LMOP 'GHGRP ID' field look like (format, coverage, uniqueness)?
  2. How non-unique is it — does one GHGRP ID map to multiple landfills, or one
     landfill to multiple GHGRP IDs?
  3. How many of the 1,040 GHGRP facility_ids match LMOP, and of the matched set,
     how many are RNG adopters vs non-adopters (the control-group question)?
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
ADOPT_STATUS = {'Operational', 'Construction', 'Planned'}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    gh = pd.read_csv(GHGRP, dtype={'facility_id': 'Int64'})
    gh_fac = set(gh['facility_id'].dropna().astype(int).unique())

    # ---- 1. LMOP GHGRP ID field characterization ----
    g = df['GHGRP ID']
    nn = g.dropna()
    # normalize floats to int (values are 7-digit ints stored as float64)
    lmop_int = nn.astype('int64')
    n_nonnull = int(nn.shape[0])
    n_unique = int(lmop_int.nunique())

    # uniqueness structure at the landfill level (aggregate project rows by Landfill ID)
    lf2gh = {}
    for lid, sub in df[df['GHGRP ID'].notna()].groupby('Landfill ID'):
        ids = set(sub['GHGRP ID'].astype('int64'))
        lf2gh[int(lid)] = ids
    gh2lf = {}
    for lid, ids in lf2gh.items():
        for gi in ids:
            gh2lf.setdefault(gi, set()).add(lid)

    n_landfills_with_ghgrp = len(lf2gh)
    multi_ghgrp_landfills = {lid: sorted(ids) for lid, ids in lf2gh.items() if len(ids) > 1}
    multi_lf_ghgrp_ids = {gi: sorted(lids) for gi, lids in gh2lf.items() if len(lids) > 1}

    # ---- 2. direct match against GHGRP facility_ids ----
    lmop_unique_set = set(lf2gh.keys())  # no: this is landfill ids; we need GHGRP ids
    lmop_ghgrp_ids = set(gh2lf.keys())
    matched_ghgrp = lmop_ghgrp_ids & gh_fac
    matched_ghgrp_lmop_only = lmop_ghgrp_ids - gh_fac
    ghgrp_not_in_lmop = gh_fac - lmop_ghgrp_ids

    # ---- 3. adopter/control split among MATCHED GHGRP facilities ----
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    is_local = df['RNG Delivery Method'].eq('Local Use')
    adopted_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))
    pi_adopted_lf = set(df.loc[is_rng & is_pi, 'Landfill ID'].astype(int))
    local_lf = set(df.loc[is_rng & is_local, 'Landfill ID'].astype(int))

    # for each matched GHGRP facility, find its landfills and classify
    matched_rows = []
    for gi in sorted(matched_ghgrp):
        lids = gh2lf[gi]
        lf_adopted = [l for l in lids if l in adopted_lf]
        lf_control = [l for l in lids if l not in adopted_lf]
        matched_rows.append({
            'ghgrp_facility_id': gi, 'n_landfills': len(lids),
            'n_adopted_landfills': len(lf_adopted), 'n_control_landfills': len(lf_control),
            'adopter_any': len(lf_adopted) > 0, 'control_any': len(lf_control) > 0,
            'pi_adopted': any(l in pi_adopted_lf for l in lids),
            'local': any(l in local_lf for l in lids),
        })
    m = pd.DataFrame(matched_rows)
    n_matched_ghgrp_fac = len(matched_ghgrp)
    n_matched_fac_with_control = int(m['control_any'].sum()) if len(m) else 0
    n_matched_fac_with_adopter = int(m['adopter_any'].sum()) if len(m) else 0
    # unique matched landfills
    matched_landfills = set()
    for gi in matched_ghgrp:
        matched_landfills |= gh2lf[gi]
    matched_control_lf = matched_landfills - adopted_lf
    matched_adopter_lf = matched_landfills & adopted_lf

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'lmop_ghgrp_id_field': {
            'non_null_rows': n_nonnull, 'total_rows': int(len(df)),
            'unique_values': n_unique, 'format': '7-digit integer stored as float64',
            'n_landfills_with_ghgrp_id': n_landfills_with_ghgrp,
            'n_landfills_with_multiple_ghgrp_ids': len(multi_ghgrp_landfills),
            'n_ghgrp_ids_mapping_to_multiple_landfills': len(multi_lf_ghgrp_ids),
            'example_multi_ghgrp_landfills': dict(list(multi_ghgrp_landfills.items())[:10]),
            'example_multi_landfill_ghgrp_ids': dict(list(multi_lf_ghgrp_ids.items())[:10]),
        },
        'ghgrp_data': {'n_rows': int(len(gh)), 'unique_facility_id': int(len(gh_fac)),
                       'years': sorted(int(y) for y in gh['reporting_year'].dropna().unique())},
        'direct_match': {
            'lmop_unique_ghgrp_ids': int(len(lmop_ghgrp_ids)),
            'matched_in_ghgrp': int(len(matched_ghgrp)),
            'lmop_only_not_in_ghgrp': int(len(matched_ghgrp_lmop_only)),
            'ghgrp_not_in_lmop': int(len(ghgrp_not_in_lmop)),
            'match_rate_of_ghgrp_1040': round(len(matched_ghgrp) / len(gh_fac), 4) if gh_fac else None,
        },
        'matched_adopter_control_split': {
            'n_matched_ghgrp_facilities': n_matched_ghgrp_fac,
            'n_matched_facilities_with_adopter': n_matched_fac_with_adopter,
            'n_matched_facilities_with_control': n_matched_fac_with_control,
            'n_matched_landfills': len(matched_landfills),
            'n_matched_control_landfills': len(matched_control_lf),
            'n_matched_adopter_landfills': len(matched_adopter_lf),
        },
    }
    (out / 'join_lmop_ghgrp_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    if len(m):
        m.to_csv(out / 'matched_facility_level.csv', index=False, encoding='utf-8-sig')
    # landfill-level match dump
    lf_rows = []
    for gi in sorted(matched_ghgrp):
        for l in sorted(gh2lf[gi]):
            lf_rows.append({'landfill_id': l, 'ghgrp_facility_id': gi,
                            'adopter': l in adopted_lf, 'pi': l in pi_adopted_lf, 'local': l in local_lf})
    pd.DataFrame(lf_rows).to_csv(out / 'matched_landfill_level.csv', index=False, encoding='utf-8-sig')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
