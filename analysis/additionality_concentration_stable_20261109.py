"""Concentration outcome, citable event study on the BASIS-STABLE treated subset.

Reproduces the full-sample TWFE/event-study/trend-adjusted DiD (with a 3-way wet/dry/
missing basis coding, fixing the earlier missing->dry bug) AND reruns the same three
models restricting treated facilities to those whose CH4-concentration measurement basis
never changed across their observed window. If the jump survives in the basis-stable
subset, it is not a wet/dry reporting artifact.

Read-only (LMOP + GHGRP). Association, not causal.
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


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def demean(df, cols, group):
    g = df.groupby(group)[cols].transform('mean')
    return df[cols].to_numpy(float) - g.to_numpy(float)


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_se(X, y, beta, clusters, g=1.0):
    e = y - X @ beta
    score = X * e[:, None]
    H = X.T @ X
    meat = np.zeros((X.shape[1], X.shape[1]))
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    Hinv = np.linalg.pinv(H)
    v = Hinv @ meat @ Hinv
    dof = (len(np.unique(clusters)) / (len(np.unique(clusters)) - 1.0)) * g
    return np.sqrt(np.clip(np.diag(v) * dof, 0, None))


def residualize_slope(df, cols, group, time_col):
    df = df.reset_index(drop=True)
    out = demean(df, cols, group)
    t = df[time_col].to_numpy(float)
    res = np.zeros_like(out)
    dfd = df.copy()
    for c in cols:
        dfd[c] = out[:, cols.index(c)]
    for name, g in dfd.groupby(group):
        idx = g.index.to_numpy()
        tg = t[idx] - t[idx].mean()
        tt = float((tg * tg).sum())
        if tt <= 1e-12:
            res[idx, :] = g[cols].to_numpy(float)
            continue
        for j, c in enumerate(cols):
            col = g[c].to_numpy(float)
            b = float(col @ tg) / tt
            res[idx, j] = col - b * tg
    return res


def basis_of(s):
    s = s.astype(str).str.strip().str.upper()
    out = pd.Series('missing', index=s.index)
    out[s.eq('Y')] = 'wet'
    out[s.eq('N')] = 'dry'
    out[s.isin(['NAN', 'NONE', 'NULL', '', '<NA>'])] = 'missing'
    return out


def ev_bin(k):
    if k is None or (isinstance(k, float) and np.isnan(k)):
        return None
    k = int(k)
    if k <= -5: return 'pre_le_-5'
    if k == -1: return 'ref'
    if k >= 4: return 'post_ge_4'
    return f'k{k}'


EV_LEVELS = ['pre_le_-5', 'k-4', 'k-3', 'k-2', 'k0', 'k1', 'k2', 'k3', 'post_ge_4']


def run_models(keep, label):
    """TWFE DiD + event study + trend-adjusted DiD on the panel `keep` (conc, wet, year, event_time, treated, post, facility_id)."""
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))

    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)

    # M1 TWFE
    X_cols = ['wet'] + yr_dummies + ['post']
    d = demean(keep, X_cols + ['conc'], 'facility_id')
    X = d[:, :len(X_cols)]; yw = d[:, len(X_cols)]
    beta = ols(X, yw); se = cluster_se(X, yw, beta, keep['facility_id'].to_numpy())
    tau = float(beta[X_cols.index('post')]); tau_se = float(se[X_cols.index('post')])
    tau_p = float(2 * (1 - norm_cdf(abs(tau / tau_se))))

    # M2 event study
    keep['ev'] = keep['event_time'].apply(ev_bin)
    for lv in EV_LEVELS:
        keep[f'ev_{lv}'] = ((keep['ev'] == lv) & (keep['treated'] == 1)).astype(int)
    ev_cols = [f'ev_{lv}' for lv in EV_LEVELS]
    cols2 = ['wet'] + yr_dummies + ev_cols
    d2 = demean(keep, cols2 + ['conc'], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2); se2 = cluster_se(X2, yw2, beta2, keep['facility_id'].to_numpy())
    ev_coefs = {c: {'coef': float(beta2[cols2.index(c)]), 'se': float(se2[cols2.index(c)])} for c in ev_cols}

    # M3 trend-adjusted
    cols3 = ['wet'] + yr_dummies + ['post']
    Z = residualize_slope(keep, cols3 + ['conc'], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    beta3 = ols(X3, y3); se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[cols3.index('post')]); tau3_se = float(se3[cols3.index('post')])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))

    return {
        'label': label,
        'n_treated_facilities': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
        'n_control_facilities': int(keep[keep['control'] == 1]['facility_id'].nunique()),
        'n_facility_years': int(len(keep)),
        'twfe_did': {'post_coef_pp': tau, 'post_se_clustered': tau_se, 'post_p': tau_p},
        'twfe_did_trend_adjusted': {'post_coef_pp': tau3, 'post_se_clustered': tau3_se, 'post_p': tau3_p},
        'event_study': ev_coefs,
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
    rng_any_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))
    pi_lf = set(adopt.index.astype(int))
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['basis'] = basis_of(gh['ch4_conc_measured_wet_basis'])
    gh['wet'] = (gh['basis'] == 'wet').astype(int)
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year']); conc = r['conc']
            if not (pd.notna(conc) and 0 < conc <= 100):
                continue
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            rows.append({'facility_id': f, 'year': y, 'conc': float(conc),
                         'wet': int(r['wet']), 'basis': r['basis'],
                         'treated': int(is_treated), 'control': int(is_control),
                         'Ti': Ti if is_treated else None, 'post': post,
                         'event_time': (y - Ti) if (is_treated and Ti is not None) else None})
    pan = pd.DataFrame(rows)

    def usable_treated(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)
    usable_fac = set()
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        if usable_treated(g):
            usable_fac.add(f)
    control_fac = set(pan.loc[pan['control'] == 1, 'facility_id'])

    # basis-stable treated: measurement basis never changes across the facility's window
    basis_stable_fac = set()
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        if g['basis'].nunique() == 1:
            basis_stable_fac.add(f)

    full_keep = pan[pan['facility_id'].isin(usable_fac | control_fac)].copy()
    stable_keep = pan[pan['facility_id'].isin((usable_fac & basis_stable_fac) | control_fac)].copy()

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'note': 'basis coded wet/dry/missing (3-way); basis-stable = facility basis never changes across observed window; outcome annl_avg_methane_concentration (%, level)',
        'n_basis_stable_treated': int(len(usable_fac & basis_stable_fac)),
        'full_sample': run_models(full_keep.copy(), 'all usable treated'),
        'basis_stable_sample': run_models(stable_keep.copy(), 'basis-stable treated'),
    }
    (out / 'additionality_concentration_stable_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
