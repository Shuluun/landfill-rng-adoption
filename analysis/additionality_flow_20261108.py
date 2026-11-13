"""Additionality second stage — tertiary outcome: landfill gas FLOW (log).

Does pipeline-injection RNG adoption change annual landfill gas flow? Completes the
three-outcome picture: recovered CH4 (mass) ~ flow x concentration. Outcome =
log(annual_landfill_gas_flow); wet/dry flow basis controlled; facility FE + year FE,
facility-clustered SE, plus facility-specific linear-trend DiD.

Read-only. Association, not causal.
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

    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['wet'] = gh['lndfil_gas_flow_mesr_wet_basis'].astype(str).str.strip().str.upper().eq('Y').astype(int)
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
            y = int(r['year']); flow = r['flow']
            if not (pd.notna(flow) and flow > 0):
                continue
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            rows.append({'facility_id': f, 'year': y, 'log_flow': float(np.log(flow)),
                         'wet': int(r['wet']), 'treated': int(is_treated),
                         'control': int(is_control), 'Ti': Ti if is_treated else None,
                         'post': post, 'event_time': (y - Ti) if (is_treated and Ti is not None) else None})
    pan = pd.DataFrame(rows)

    def usable_treated(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)
    usable_fac = set()
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        if usable_treated(g):
            usable_fac.add(f)
    control_fac = set(pan.loc[pan['control'] == 1, 'facility_id'])
    keep = pan[pan['facility_id'].isin(usable_fac | control_fac)].copy()

    tr_pre = keep[(keep['treated'] == 1) & (keep['post'] == 0)]['log_flow'].mean()
    tr_post = keep[(keep['treated'] == 1) & (keep['post'] == 1)]['log_flow'].mean()
    med_T = np.median([t for t in keep.loc[keep['treated'] == 1, 'Ti'].unique()])
    ctrl_early = keep[(keep['control'] == 1) & (keep['year'] < med_T)]['log_flow'].mean()
    ctrl_late = keep[(keep['control'] == 1) & (keep['year'] >= med_T)]['log_flow'].mean()
    did_means = (tr_post - tr_pre) - (ctrl_late - ctrl_early)

    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)

    X_cols = ['wet'] + yr_dummies + ['post']
    d = demean(keep, X_cols + ['log_flow'], 'facility_id')
    X = d[:, :len(X_cols)]; yw = d[:, len(X_cols)]
    beta = ols(X, yw)
    se = cluster_se(X, yw, beta, keep['facility_id'].to_numpy())
    tau = float(beta[X_cols.index('post')]); tau_se = float(se[X_cols.index('post')])
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    tau_p = float(2 * (1 - norm_cdf(abs(tau / tau_se))))

    def ev_bin(k):
        if k is None or (isinstance(k, float) and np.isnan(k)):
            return None
        k = int(k)
        if k <= -5: return 'pre_le_-5'
        if k == -1: return 'ref'
        if k >= 4: return 'post_ge_4'
        return f'k{k}'
    keep['ev'] = keep['event_time'].apply(ev_bin)
    ev_levels = ['pre_le_-5', 'k-4', 'k-3', 'k-2', 'k0', 'k1', 'k2', 'k3', 'post_ge_4']
    for lv in ev_levels:
        keep[f'ev_{lv}'] = ((keep['ev'] == lv) & (keep['treated'] == 1)).astype(int)
    ev_cols = [f'ev_{lv}' for lv in ev_levels]
    cols2 = ['wet'] + yr_dummies + ev_cols
    d2 = demean(keep, cols2 + ['log_flow'], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2)
    se2 = cluster_se(X2, yw2, beta2, keep['facility_id'].to_numpy())
    ev_coefs = {c: {'coef': float(beta2[cols2.index(c)]), 'se': float(se2[cols2.index(c)])} for c in ev_cols}

    cols3 = ['wet'] + yr_dummies + ['post']
    Z = residualize_slope(keep, cols3 + ['log_flow'], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    beta3 = ols(X3, y3)
    se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[cols3.index('post')]); tau3_se = float(se3[cols3.index('post')])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'sample': {
            'n_treated_facilities': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
            'n_control_facilities': int(keep[keep['control'] == 1]['facility_id'].nunique()),
            'n_facility_years': int(len(keep)),
            'outcome': 'log(annual_landfill_gas_flow)',
            'wet_basis_control': True, 'median_adoption_year': float(med_T),
        },
        'descriptive': {
            'treated_pre_mean_logflow': float(tr_pre), 'treated_post_mean_logflow': float(tr_post),
            'control_early_mean_logflow': float(ctrl_early), 'control_late_mean_logflow': float(ctrl_late),
            'did_in_means_logflow': float(did_means),
        },
        'twfe_did': {
            'post_coef': tau, 'post_se_clustered': tau_se, 'post_p': tau_p,
            'pct_effect': float((np.exp(tau) - 1) * 100),
            'n_obs': int(len(yw)), 'n_clusters_facility': int(keep['facility_id'].nunique()),
        },
        'twfe_did_trend_adjusted': {
            'post_coef': tau3, 'post_se_clustered': tau3_se, 'post_p': tau3_p,
            'pct_effect': float((np.exp(tau3) - 1) * 100),
            'note': 'facility-specific linear time trend absorbed',
        },
        'event_study': ev_coefs,
    }
    (out / 'additionality_flow_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    keep.to_csv(out / 'panel_flow.csv', index=False, encoding='utf-8-sig')
    evdf = pd.DataFrame([{'event': c, **ev_coefs[c]} for c in ev_cols])
    evdf.to_csv(out / 'event_study_flow.csv', index=False, encoding='utf-8-sig')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
