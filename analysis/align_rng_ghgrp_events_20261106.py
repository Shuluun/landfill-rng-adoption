"""Event alignment: does each matched pipeline-injection RNG adopter have usable
pre- AND post-adoption gas-collection records in GHGRP Subpart HH?

Read-only (LMOP xlsx + downloaded GHGRP CSV). No network. The decisive question for
the additionality second stage (DiD / event study / IV) is how many adopters have
>=1 pre-adoption and >=1 post-adoption "active" (positive recovered-CH4) year.
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

    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')

    # pipeline-injection adoption year per landfill: min PI RNG start year in [1995, 2024]
    # (same window as the survival model; excludes inherited pre-1995 bad dates and
    #  future-only 2025-2027 Construction/Planned rows)
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid_pi = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid_pi.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))
    all_pi_landfills = set(df.loc[is_rng & is_pi, 'Landfill ID'].astype(int))
    n_excluded_no_valid_window = len(all_pi_landfills - set(adopt.index.astype(int)))

    # landfill -> GHGRP facility id(s) via LMOP 'GHGRP ID'
    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))

    # GHGRP: numeric outcomes + active (positive recovered CH4) years per facility
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    all_years = gh.groupby('fac')['year'].agg(lambda s: sorted(set(s)))
    active_years = gh[gh['rec'] > 0].groupby('fac')['year'].agg(lambda s: sorted(set(s)))
    flow_years = gh[gh['flow'] > 0].groupby('fac')['year'].agg(lambda s: sorted(set(s)))

    # overall GHGRP activity summary
    n_fac = int(gh['fac'].nunique())
    n_fac_active_any = int(active_years.shape[0])
    n_fy = int(len(gh))
    n_fy_active = int((gh['rec'] > 0).sum())
    n_fy_flow = int((gh['flow'] > 0).sum())

    # iterate matched PI adopters
    rows = []
    for lid, ay in sorted(adopt.items()):
        lid = int(lid)
        facs = lf2fac.get(lid)
        if not facs:
            rows.append({'landfill_id': lid, 'adoption_year': ay, 'ghgrp_facility_id': None,
                         'n_facility': 0, 'n_pre': 0, 'n_post': 0, 'n_post_strict': 0,
                         'usable': False, 'loss_reason': 'no_ghgrp_id'})
            continue
        # merge years across all facilities mapped to this landfill
        yrs = set()
        for f in facs:
            yrs |= set(all_years.get(f, []))
        yrs = sorted(yrs)
        pre = [y for y in yrs if y < ay]
        post = [y for y in yrs if y >= ay]
        post_strict = [y for y in yrs if y > ay]
        usable = len(pre) >= 1 and len(post) >= 1
        if not yrs:
            loss = 'no_ghgrp_rows'
        elif not pre:
            loss = 'no_pre_data'
        elif not post:
            loss = 'no_post_data'
        else:
            loss = ''
        rows.append({'landfill_id': lid, 'adoption_year': ay,
                     'ghgrp_facility_id': facs[0] if len(facs) == 1 else facs,
                     'n_facility': len(facs), 'n_pre': len(pre), 'n_post': len(post),
                     'n_post_strict': len(post_strict), 'n_years': len(yrs),
                     'first_year': yrs[0] if yrs else None, 'last_year': yrs[-1] if yrs else None,
                     'usable': bool(usable), 'loss_reason': loss})

    al = pd.DataFrame(rows)
    n_total = len(al)
    n_usable = int(al['usable'].sum())
    n_no_pre = int((al['loss_reason'] == 'no_pre_data').sum())
    n_no_post = int((al['loss_reason'] == 'no_post_data').sum())
    n_no_ghgrp_id = int((al['loss_reason'] == 'no_ghgrp_id').sum())
    n_no_rows = int((al['loss_reason'] == 'no_ghgrp_rows').sum())

    # distribution of pre/post year counts among usable
    usable = al[al['usable']]
    def q(s, p): return float(np.percentile(s, p)) if len(s) else None

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'ghgrp_activity': {
            'n_facilities': n_fac, 'n_facilities_with_positive_rec_any_year': n_fac_active_any,
            'n_facility_years': n_fy, 'n_facility_years_positive_rec': n_fy_active,
            'n_facility_years_positive_flow': n_fy_flow,
        },
        'event_alignment': {
            'n_matched_pi_adopters': n_total,
            'n_pi_adopters_excluded_no_valid_window': n_excluded_no_valid_window,
            'n_usable_pre_post': n_usable,
            'n_lost_no_pre': n_no_pre, 'n_lost_no_post': n_no_post,
            'n_lost_no_ghgrp_id': n_no_ghgrp_id, 'n_lost_no_ghgrp_rows': n_no_rows,
            'usable_rate': round(n_usable / n_total, 4) if n_total else None,
            'adoption_year_range': [int(al['adoption_year'].min()), int(al['adoption_year'].max())],
            'usable_n_pre': {'min': int(usable['n_pre'].min()) if n_usable else None,
                             'median': q(usable['n_pre'], 50),
                             'max': int(usable['n_pre'].max()) if n_usable else None},
            'usable_n_post': {'min': int(usable['n_post'].min()) if n_usable else None,
                              'median': q(usable['n_post'], 50),
                              'max': int(usable['n_post'].max()) if n_usable else None},
            'adoption_year_distribution': {int(y): int(c) for y, c in al['adoption_year'].value_counts().sort_index().items()},
        },
    }
    (out / 'event_alignment_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    al.to_csv(out / 'event_alignment_per_adopter.csv', index=False, encoding='utf-8-sig')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
