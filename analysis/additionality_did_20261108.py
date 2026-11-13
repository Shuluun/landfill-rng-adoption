"""Additionality second stage: TWFE difference-in-differences / event study of
pipeline-injection RNG adoption on recovered methane.

Does RNG adoption increase recovered CH4 (annual_qty_recoverd_ch4_eq_hh4) relative to
non-adopter controls? Facility-year panel, log(recovered CH4) outcome, facility FE
(within transformation) + calendar-year FE, SE clustered by facility.

Read-only (LMOP + downloaded GHGRP). No network. Association only, not causal —
the pipeline-distance IV (first stage) is wired up separately; this is the reduced
second stage.
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
    """Group-demean (absorb group FE), then remove group-specific linear slope in time_col."""
    df = df.reset_index(drop=True)
    out = demean(df, cols, group)  # n x len(cols)
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
    is_local = df['RNG Delivery Method'].eq('Local Use')

    # PI adoption year per landfill (valid window [1995, 2024])
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))

    # landfill -> GHGRP facility id(s)
    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))

    # classify landfills: treated (PI with valid adoption year), control (never-RNG)
    rng_any_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))
    pi_lf = set(adopt.index.astype(int))

    # build facility-level treatment map
    # facility -> landfill(s)
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    # GHGRP panel
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    # assign treatment status to each facility
    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        # adoption year = min over landfills' adoption years (should be single, except exception)
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year']); rec = r['rec']
            if not (rec and rec > 0):
                continue
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            rows.append({'facility_id': f, 'year': y, 'rec': float(rec),
                         'conc': float(r['conc']) if pd.notna(r['conc']) else np.nan,
                         'treated': int(is_treated), 'control': int(is_control),
                         'Ti': Ti if is_treated else None, 'post': post,
                         'event_time': (y - Ti) if (is_treated and Ti is not None) else None})
    pan = pd.DataFrame(rows)
    pan['log_rec'] = np.log(pan['rec'])

    # usable treated: pre>=1 and post>=1; controls: control==1
    def usable_treated(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)
    usable_fac = set()
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        if usable_treated(g):
            usable_fac.add(f)
    control_fac = set(pan.loc[pan['control'] == 1, 'facility_id'])
    keep = pan[pan['facility_id'].isin(usable_fac | control_fac)].copy()

    # descriptive DiD-in-means
    tr_pre = keep[(keep['treated'] == 1) & (keep['post'] == 0)]['log_rec'].mean()
    tr_post = keep[(keep['treated'] == 1) & (keep['post'] == 1)]['log_rec'].mean()
    # controls: no post; use a reference split at median treated adoption year
    med_T = np.median([t for t in keep.loc[keep['treated'] == 1, 'Ti'].unique()])
    ctrl_early = keep[(keep['control'] == 1) & (keep['year'] < med_T)]['log_rec'].mean()
    ctrl_late = keep[(keep['control'] == 1) & (keep['year'] >= med_T)]['log_rec'].mean()
    did_means = (tr_post - tr_pre) - (ctrl_late - ctrl_early)

    # TWFE DiD: within (facility) demean, year dummies + post
    y = keep['log_rec'].to_numpy(float)
    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]  # drop earliest year as reference
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    X_cols = yr_dummies + ['post']
    cols_demean = X_cols + ['log_rec']
    d = demean(keep, cols_demean, 'facility_id')
    X = d[:, :len(X_cols)]; yw = d[:, len(X_cols)]
    beta = ols(X, yw)
    names = X_cols
    se = cluster_se(X, yw, beta, keep['facility_id'].to_numpy())
    tau_idx = names.index('post')
    tau = float(beta[tau_idx]); tau_se = float(se[tau_idx])
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    tau_p = float(2 * (1 - norm_cdf(abs(tau / tau_se))))

    # event study: relative-time dummies (omit k=-1)
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
    cols2 = yr_dummies + ev_cols
    d2 = demean(keep, cols2 + ['log_rec'], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2)
    # diagnostic: rank / collinearity of event-study design
    rk2 = np.linalg.matrix_rank(X2)
    _, Rd = np.linalg.qr(X2)
    tol = 1e-9 * max(X2.shape)
    dep_cols = [cols2[i] for i in range(X2.shape[1]) if abs(Rd[i, i]) < tol]
    print(f'[diag] event-study X2: shape={X2.shape} rank={rk2} ncol={len(cols2)} dependent={dep_cols}')
    se2 = cluster_se(X2, yw2, beta2, keep['facility_id'].to_numpy())
    ev_coefs = {c: {'coef': float(beta2[cols2.index(c)]), 'se': float(se2[cols2.index(c)])} for c in ev_cols}

    # M3: facility-specific linear-trend DiD (absorb each facility's own growth)
    cols3 = yr_dummies + ['post']
    Z = residualize_slope(keep, cols3 + ['log_rec'], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    rk3 = np.linalg.matrix_rank(X3)
    beta3 = ols(X3, y3)
    se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[len(yr_dummies)]); tau3_se = float(se3[len(yr_dummies)])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))
    print(f'[diag] trend-adjusted X3: rank={rk3} ncol={len(cols3)}')

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
            'outcome': 'log(annual_qty_recoverd_ch4_eq_hh4)',
            'median_adoption_year': float(med_T),
        },
        'descriptive': {
            'treated_pre_mean_logrec': float(tr_pre), 'treated_post_mean_logrec': float(tr_post),
            'control_early_mean_logrec': float(ctrl_early), 'control_late_mean_logrec': float(ctrl_late),
            'did_in_means_logrec': float(did_means),
        },
        'twfe_did': {
            'post_coef': tau, 'post_se_clustered': tau_se, 'post_p': tau_p,
            'pct_effect': float((np.exp(tau) - 1) * 100),
            'n_obs': int(len(y)), 'n_clusters_facility': int(keep['facility_id'].nunique()),
        },
        'twfe_did_trend_adjusted': {
            'post_coef': tau3, 'post_se_clustered': tau3_se, 'post_p': tau3_p,
            'pct_effect': float((np.exp(tau3) - 1) * 100),
            'note': 'facility-specific linear time trend absorbed (removes each facility own growth)',
        },
        'event_study': ev_coefs,
    }
    (out / 'additionality_did_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    keep.to_csv(out / 'panel.csv', index=False, encoding='utf-8-sig')
    evdf = pd.DataFrame([{'event': c, **ev_coefs[c]} for c in ev_cols])
    evdf.to_csv(out / 'event_study_coefficients.csv', index=False, encoding='utf-8-sig')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
