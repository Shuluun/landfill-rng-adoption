"""Row-level physical-identity residual: is recovered CH4 = flow x conc x const?

On the intersection sample (flow>0, 0<conc<=100, rec>0 all valid for the same
facility-year), define resid = log(rec) - log(flow) - log(conc). If the recovered
quantity is a deterministic multiple of flow x concentration, resid is constant and
its within-facility standard deviation is ~0; then any event-study on resid should be
~0 at every event time. A jump in resid at adoption would mean the recovered/flow/concentration
relationship itself breaks when RNG starts.

This removes the sample-mismatch confound in the separate-regression "identity gap":
all three logs come from the SAME row here.
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
NON_RNG_USE = {'Electricity', 'Direct'}


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


def run_models(panel, outcome, with_wet):
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    keep = panel.copy()
    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    base = (['wet'] if with_wet else []) + yr_dummies

    X_cols = base + ['post']
    d = demean(keep, X_cols + [outcome], 'facility_id')
    X = d[:, :len(X_cols)]; yw = d[:, len(X_cols)]
    beta = ols(X, yw); se = cluster_se(X, yw, beta, keep['facility_id'].to_numpy())
    tau = float(beta[X_cols.index('post')]); tau_se = float(se[X_cols.index('post')])
    tau_p = float(2 * (1 - norm_cdf(abs(tau / tau_se))))

    keep['ev'] = keep['event_time'].apply(ev_bin)
    for lv in EV_LEVELS:
        keep[f'ev_{lv}'] = ((keep['ev'] == lv) & (keep['treated'] == 1)).astype(int)
    ev_cols = [f'ev_{lv}' for lv in EV_LEVELS]
    cols2 = base + ev_cols
    d2 = demean(keep, cols2 + [outcome], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2); se2 = cluster_se(X2, yw2, beta2, keep['facility_id'].to_numpy())
    ev = {c: {'coef': float(beta2[cols2.index(c)]), 'se': float(se2[cols2.index(c)])} for c in ev_cols}

    cols3 = base + ['post']
    Z = residualize_slope(keep, cols3 + [outcome], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    beta3 = ols(X3, y3); se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[cols3.index('post')]); tau3_se = float(se3[cols3.index('post')])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))

    return {
        'n_treated_facilities': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
        'n_control_facilities': int(keep[keep['control'] == 1]['facility_id'].nunique()),
        'n_facility_years': int(len(keep)),
        'twfe_did': {'post_coef': tau, 'post_se_clustered': tau_se, 'post_p': tau_p},
        'twfe_did_trend_adjusted': {'post_coef': tau3, 'post_se_clustered': tau3_se, 'post_p': tau3_p},
        'event_study': ev,
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

    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['basis'] = basis_of(gh['ch4_conc_measured_wet_basis'])
    gh['wet'] = (gh['basis'] == 'wet').astype(int)
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

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

    lf_flag = {}
    for lid in pi_lf:
        rows = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = rows[rows['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = set(pi_rows['Current Project Status'].astype(str).str.strip())
        ever_op = bool(statuses & {'Operational', 'Shutdown'})
        other = rows[rows['Project Type Category'].isin(NON_RNG_USE)]
        other_years = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((other_years < adopt[lid]).any())
        lf_flag[lid] = {'ever_op': ever_op, 'prior_use': prior_use}

    def group_of(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        if not lids:
            return None
        ever_op = any(lf_flag[l]['ever_op'] for l in lids)
        prior_use = any(lf_flag[l]['prior_use'] for l in lids)
        if not ever_op:
            return 'excluded_status'
        return 'switch' if prior_use else 'new'

    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        grp = group_of(f) if is_treated else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year'])
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            conc = r['conc']; rec = r['rec']; flow = r['flow']
            c_ok = pd.notna(conc) and 0 < conc <= 100
            f_ok = pd.notna(flow) and flow > 0
            r_ok = pd.notna(rec) and rec > 0
            resid = float(np.log(rec) - np.log(flow) - np.log(conc)) if (c_ok and f_ok and r_ok) else np.nan
            rows.append({
                'facility_id': f, 'year': y,
                'resid': resid,
                'wet': int(r['wet']),
                'treated': int(is_treated), 'control': int(is_control),
                'group': grp,
                'Ti': Ti if is_treated else None, 'post': post,
                'event_time': (y - Ti) if (is_treated and Ti is not None) else None,
            })
    pan = pd.DataFrame(rows)

    # residual exactness
    r = pan['resid'].dropna()
    resid_stats = {
        'n': int(len(r)),
        'overall_mean': float(r.mean()),
        'overall_std': float(r.std()),
        'overall_p1': float(r.quantile(0.01)),
        'overall_p99': float(r.quantile(0.99)),
    }
    # within-facility (after demean) std: how much does the identity vary *inside* a facility
    pan_n = pan[pan['resid'].notna()].copy()
    pan_n['resid_dm'] = pan_n.groupby('facility_id')['resid'].transform(lambda s: s - s.mean())
    resid_stats['within_facility_std'] = float(pan_n['resid_dm'].std())
    resid_stats['within_facility_p1'] = float(pan_n['resid_dm'].quantile(0.01))
    resid_stats['within_facility_p99'] = float(pan_n['resid_dm'].quantile(0.99))

    # event study on resid (same row, no sample mismatch)
    def usable(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)

    def build_subset(pan_out, group_filter):
        treated_fac = set()
        for f, g in pan_out[pan_out['treated'] == 1].groupby('facility_id'):
            if usable(g) and group_filter(g):
                treated_fac.add(f)
        control_fac = set(pan_out.loc[pan_out['control'] == 1, 'facility_id'])
        return pan_out[pan_out['facility_id'].isin(treated_fac | control_fac)].copy()

    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }
    pan_res = pan[pan['resid'].notna()]
    resid_results = {}
    for gname, gfilter in groups.items():
        sub = build_subset(pan_res, gfilter)
        resid_results[gname] = run_models(sub, 'resid', with_wet=False)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'resid_definition': 'log(rec) - log(flow) - log(conc), on rows where flow>0 & 0<conc<=100 & rec>0',
        'resid_exactness': resid_stats,
        'resid_event_study': resid_results,
    }
    (out / 'additionality_identity_residual_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
