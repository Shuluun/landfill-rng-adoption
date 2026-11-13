"""Shutdown sensitivity for the concentration (quality) additionality.

Decision #1 on the treated definition: how to treat RNG-PI projects whose current
status is 'Shutdown' (RNG no longer operating, e.g. Seminole Road). The baseline keeps
ever-operational (Operational OR Shutdown). This script re-runs the concentration and
recovered-CH4 event studies with treated = Operational-only, dropping facilities whose
RNG is Shutdown-only (no current Operational project), to check whether the +4pp
concentration jump depends on Shutdown facilities.

Same tightened new/switch split as additionality_stratified_20261109.py.
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


def run_models(panel, outcome, with_wet, wet_col='wet'):
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    keep = panel.copy()
    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    base = ([wet_col] if with_wet else []) + yr_dummies

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
        has_op = 'Operational' in statuses
        has_shutdown = 'Shutdown' in statuses
        other = rows[rows['Project Type Category'].isin(NON_RNG_USE)]
        other_years = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((other_years < adopt[lid]).any())
        lf_flag[lid] = {'ever_op': ever_op, 'has_op': has_op, 'has_shutdown': has_shutdown,
                        'prior_use': prior_use, 'statuses': sorted(statuses)}

    def group_of(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        if not lids:
            return None
        ever_op = any(lf_flag[l]['ever_op'] for l in lids)
        prior_use = any(lf_flag[l]['prior_use'] for l in lids)
        if not ever_op:
            return 'excluded_status'
        return 'switch' if prior_use else 'new'

    def fac_has_op(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        return any(lf_flag[l]['has_op'] for l in lids)

    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        grp = group_of(f) if is_treated else None
        has_op = int(fac_has_op(f)) if is_treated else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year'])
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            conc = r['conc']; rec = r['rec']
            rows.append({
                'facility_id': f, 'year': y,
                'conc': float(conc) if (pd.notna(conc) and 0 < conc <= 100) else np.nan,
                'log_rec': float(np.log(rec)) if (pd.notna(rec) and rec > 0) else np.nan,
                'wet': int(r['wet']),
                'treated': int(is_treated), 'control': int(is_control),
                'group': grp, 'has_op': has_op,
                'Ti': Ti if is_treated else None, 'post': post,
                'event_time': (y - Ti) if (is_treated and Ti is not None) else None,
            })
    pan = pd.DataFrame(rows)

    # classification counts over ever-operational treated facilities
    class_counts = {'new': 0, 'switch': 0, 'excluded_status': 0}
    op_counts = {'new_op_only': 0, 'switch_op_only': 0, 'new_has_shutdown': 0, 'switch_has_shutdown': 0}
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        grp = g['group'].iloc[0]
        class_counts[grp] = class_counts.get(grp, 0) + 1
        ho = bool(g['has_op'].iloc[0])
        if grp in ('new', 'switch'):
            key = f'{grp}_op_only' if ho else f'{grp}_has_shutdown'
            op_counts[key] = op_counts.get(key, 0) + 1

    def usable(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)

    def build_subset(pan_out, group_filter, op_only=False):
        treated_fac = set()
        for f, g in pan_out[pan_out['treated'] == 1].groupby('facility_id'):
            ok = usable(g) and group_filter(g)
            if op_only:
                ok = ok and bool(g['has_op'].iloc[0])
            if ok:
                treated_fac.add(f)
        control_fac = set(pan_out.loc[pan_out['control'] == 1, 'facility_id'])
        return pan_out[pan_out['facility_id'].isin(treated_fac | control_fac)].copy()

    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }

    results = {}
    pan_conc = pan[pan['conc'].notna()]
    pan_rec = pan[pan['log_rec'].notna()]
    for op_only in (False, True):
        tag = 'operational_only' if op_only else 'ever_operational'
        for gname, gfilter in groups.items():
            sub_c = build_subset(pan_conc, gfilter, op_only=op_only)
            results[f'conc__{tag}__{gname}'] = run_models(sub_c, 'conc', with_wet=True)
            sub_r = build_subset(pan_rec, gfilter, op_only=op_only)
            results[f'rec__{tag}__{gname}'] = run_models(sub_r, 'log_rec', with_wet=False)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'treatment_rule': {
            'ever_operational': 'Operational OR Shutdown (baseline)',
            'operational_only': 'Operational only (drops Shutdown-only facilities)',
        },
        'treated_classification_counts': class_counts,
        'operational_split_counts': op_counts,
        'results': results,
    }
    (out / 'additionality_shutdown_sensitivity_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
