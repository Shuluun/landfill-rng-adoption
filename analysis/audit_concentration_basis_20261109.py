"""Falsification audit: is the RNG-adoption concentration jump a wet/dry-basis
reporting artifact?

Read-only. Reconstructs the treated (pipeline-injection RNG) facilities' concentration
panel and their CH4-concentration measurement-basis flag, then splits the within-facility
pre/post concentration jump by whether the basis flag ever changed (and by whether it
changed across the adoption boundary). If the jump survives among flag-stable facilities,
the jump is not a basis-reporting artifact.

Basis flag is coded THREE ways here (fixing the earlier bug that mapped missing -> dry):
  Y -> wet, N -> dry, NaN/blank -> missing.
"""
import argparse, datetime as dt, hashlib, json, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def basis_of(series):
    """Map the raw ch4_conc_measured_wet_basis column to {wet, dry, missing}."""
    s = series.astype(str).str.strip().str.upper()
    out = pd.Series('missing', index=s.index)
    out[s.eq('Y')] = 'wet'
    out[s.eq('N')] = 'dry'
    # pandas read NaN as 'nan' string via astype(str); treat as missing too
    out[s.isin(['NAN', 'NONE', 'NULL', '', '<NA>'])] = 'missing'
    return out


def summarize_jumps(df, label):
    if len(df) == 0:
        return {'n': 0}
    j = df['jump'].to_numpy(float)
    return {
        'n': int(len(df)),
        'mean_jump_pp': float(np.mean(j)),
        'median_jump_pp': float(np.median(j)),
        'frac_positive': float((j > 0).mean()),
        'min_jump_pp': float(np.min(j)),
        'max_jump_pp': float(np.max(j)),
    }


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
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))

    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))
    pi_lf = set(adopt.index.astype(int))
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['basis'] = basis_of(gh['ch4_conc_measured_wet_basis'])
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        if not is_treated:
            continue
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        if Ti is None:
            continue
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year']); conc = r['conc']
            if not (pd.notna(conc) and 0 < conc <= 100):
                continue
            rows.append({'facility_id': f, 'year': y, 'conc': float(conc),
                         'basis': r['basis'], 'Ti': Ti, 'event_time': y - Ti})
    pan = pd.DataFrame(rows)

    # per-facility pre/post jump, EXCLUDING the event year (event_time == 0)
    fac_rows = []
    for f, g in pan.groupby('facility_id'):
        pre = g[g['event_time'] < 0]
        post = g[g['event_time'] > 0]
        if len(pre) == 0 or len(post) == 0:
            continue
        pre_mean = float(pre['conc'].mean())
        post_mean = float(post['conc'].mean())
        basis_all = set(g['basis'])
        pre_basis = set(pre['basis'])
        post_basis = set(post['basis'])
        fac_rows.append({
            'facility_id': int(f),
            'Ti': int(g['Ti'].iloc[0]),
            'n_pre': int(len(pre)), 'n_post': int(len(post)),
            'pre_mean_conc': pre_mean, 'post_mean_conc': post_mean,
            'jump': post_mean - pre_mean,
            'basis_nunique': len(basis_all),
            'basis_ever_switched': len(basis_all) > 1,
            'basis_boundary_switched': pre_basis != post_basis,
            'pre_basis': ','.join(sorted(pre_basis)),
            'post_basis': ','.join(sorted(post_basis)),
            'basis_all': ','.join(sorted(basis_all)),
        })
    fac = pd.DataFrame(fac_rows)

    ever = fac['basis_ever_switched'].astype(bool)
    boundary = fac['basis_boundary_switched'].astype(bool)
    stable = ~ever

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': sys.platform,
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'note': 'jump = mean(post conc, event year excluded) - mean(pre conc); basis coded wet/dry/missing (3-way, fixes missing->dry bug)',
        'n_treated_facilities_with_pre_and_post': int(len(fac)),
        'jump_all': summarize_jumps(fac, 'all'),
        'by_basis_ever_switched': {
            'stable_basis_whole_window': summarize_jumps(fac[stable], 'stable'),
            'switched_basis_sometime': summarize_jumps(fac[ever], 'ever-switched'),
        },
        'by_basis_boundary_switched': {
            'same_basis_pre_and_post': summarize_jumps(fac[~boundary], 'same-pre-post'),
            'basis_changed_across_adoption': summarize_jumps(fac[boundary], 'boundary-switched'),
        },
    }
    (out / 'basis_falsification_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    fac.to_csv(out / 'per_facility_basis_jumps.csv', index=False, encoding='utf-8-sig')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
