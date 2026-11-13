"""Additionality IV / reduced form: pipeline distance as instrument for RNG adoption,
concentration as outcome.

Chain: log(pipeline distance) [Z] -> RNG adoption [D] -> methane concentration [Y].
Cross-sectional Wald IV at the facility level, using the within-facility concentration
long-difference (2018-2023 minus 2010-2017, split at median adoption year) as the outcome.

First stage (LPM): treated ~ log_dist + log_waste (+ state FE).
Reduced form (ITT): dConc ~ log_dist + log_waste (+ state FE).
Wald IV = reduced/log_dist / firststage/log_dist (delta-method SE, independence approx).

Read-only. Association/causal under IV assumptions; exclusion restriction (distance
affects concentration only via adoption) is a stated limitation.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from math import erf
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'
DIST = ROOT / 'outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_se(X, y, beta, clusters):
    e = y - X @ beta
    score = X * e[:, None]
    H = X.T @ X
    meat = np.zeros((X.shape[1], X.shape[1]))
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    Hinv = np.linalg.pinv(H)
    v = Hinv @ meat @ Hinv
    dof = len(np.unique(clusters)) / (len(np.unique(clusters)) - 1.0)
    return np.sqrt(np.clip(np.diag(v) * dof, 0, None))


def norm_cdf(x): return 0.5 * (1 + erf(x / np.sqrt(2)))


def design(df, base_cols, state_fe=True):
    cols = list(base_cols)
    X = df[cols].to_numpy(float)
    if state_fe:
        dummies = pd.get_dummies(df['state'], prefix='st').astype(int)
        X = np.column_stack([X, dummies.to_numpy(float)])
        cols += list(dummies.columns)
    return X, cols


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
    dist = pd.read_csv(DIST)

    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))
    pi_lf = set(adopt.index.astype(int))
    rng_any_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))

    # facility -> landfill(s)
    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    # landfill -> (distance, waste, state)
    lf_meta = {}
    for _, r in df.iterrows():
        lid = r['Landfill ID']
        if lid not in lf_meta:
            lf_meta[lid] = {'waste': pd.to_numeric(r['Waste in Place (tons)'], errors='coerce'),
                            'state': r['State']}
    dmap = dict(zip(dist['Landfill ID'], dist['nearest_pipeline_km_spherical']))

    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        if not (is_treated or is_control):
            continue
        # distance = min over facility's landfills
        ds = [dmap[l] for l in lids if l in dmap and dmap[l] > 0]
        if not ds:
            continue
        dist_km = min(ds)
        waste = min((lf_meta[l]['waste'] for l in lids if pd.notna(lf_meta[l]['waste'])), default=np.nan)
        state = next((lf_meta[l]['state'] for l in lids if isinstance(lf_meta[l]['state'], str)), None)
        sub = gh[gh['fac'] == f]
        early = sub[sub['year'] < 2018]['conc']
        late = sub[sub['year'] >= 2018]['conc']
        early = early[early > 0]; late = late[late > 0]
        if len(early) < 1 or len(late) < 1 or pd.isna(waste):
            continue
        rows.append({'facility_id': f, 'treated': int(is_treated),
                     'dConc': float(late.mean() - early.mean()),
                     'log_dist': float(np.log(dist_km)),
                     'log_waste': float(np.log(waste)), 'state': state})
    fdf = pd.DataFrame(rows)

    def fit(base_cols, ycol, tag):
        X, cols = design(fdf, base_cols, state_fe=True)
        y = fdf[ycol].to_numpy(float)
        beta = ols(X, y)
        se = cluster_se(X, y, beta, fdf['state'].to_numpy())
        i_dist = cols.index('log_dist')
        res = {'coef': float(beta[i_dist]), 'se': float(se[i_dist]),
               'n': int(len(y))}
        res['p'] = float(2 * (1 - norm_cdf(abs(res['coef'] / res['se']))))
        return res

    fs = fit(['log_dist', 'log_waste'], 'treated', 'first_stage')
    rf = fit(['log_dist', 'log_waste'], 'dConc', 'reduced_form')
    # also no-state-FE for transparency
    def fit_nofe(base_cols, ycol):
        X = fdf[base_cols].to_numpy(float); y = fdf[ycol].to_numpy(float)
        beta = ols(X, y); se = cluster_se(X, y, beta, fdf['state'].to_numpy())
        i = base_cols.index('log_dist')
        return {'coef': float(beta[i]), 'se': float(se[i]),
                'p': float(2 * (1 - norm_cdf(abs(beta[i] / se[i]))))}
    fs_nofe = fit_nofe(['log_dist', 'log_waste'], 'treated')
    rf_nofe = fit_nofe(['log_dist', 'log_waste'], 'dConc')

    iv = rf['coef'] / fs['coef'] if fs['coef'] != 0 else np.nan
    # delta-method SE, independence approx
    iv_se = np.sqrt((rf['se']**2) / (fs['coef']**2) + (rf['coef']**2 * fs['se']**2) / (fs['coef']**4))

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP), 'dist_sha256': sha(DIST),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'sample': {
            'n_facilities': int(len(fdf)), 'n_treated': int(fdf['treated'].sum()),
            'n_control': int(len(fdf) - fdf['treated'].sum()),
            'outcome': 'within-facility concentration long-difference (2018-2023 minus 2010-2017, %-points)',
            'instrument': 'log(nearest pipeline km, spherical)',
        },
        'first_stage_stateFE': fs, 'first_stage_nofe': fs_nofe,
        'reduced_form_stateFE': rf, 'reduced_form_nofe': rf_nofe,
        'wald_iv': {'iv_pp_per_adoption': float(iv), 'iv_se_delta': float(iv_se),
                    'note': 'Wald = reduced_form/log_dist / first_stage/log_dist; delta-method SE assumes independence (approx)'},
        'descriptive': {
            'corr_logdist_dconc': float(fdf['log_dist'].corr(fdf['dConc'])),
            'mean_dconc_treated': float(fdf.loc[fdf['treated'] == 1, 'dConc'].mean()),
            'mean_dconc_control': float(fdf.loc[fdf['treated'] == 0, 'dConc'].mean()),
        },
    }
    (out / 'additionality_iv_concentration_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    fdf.to_csv(out / 'facility_level_iv.csv', index=False, encoding='utf-8-sig')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
