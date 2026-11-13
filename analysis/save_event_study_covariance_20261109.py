"""Save full event-study coefficient vector beta and cluster-robust covariance (Sigma-hat).

#0 of the inference-hardening plan. The final-spec scripts
(additionality_stratified_20261109.py for TWFE, additionality_cs_did_20261109.py
for Callaway-Sant'Anna) kept only point estimates + diagonal SEs / bootstrap
percentile CIs, discarding the full covariance matrix. HonestDiD/Rambachan-Roth
(#2), Romano-Wolf (#5) and the placebo test (#3) all need the full Sigma-hat.
This script re-runs the exact same headline models and saves beta + Sigma to disk.

Saved (new run dir, no overwrite):
  twfe_event_study: per group (all_ever_operational / new_rng / use_switch) for
      concentration (%, level, wet-controlled): beta (9), cov (9x9), and the
      pre-trend sub-vector (4) + sub-covariance (4x4) for HonestDiD/RR.
  cs_event_study:    per group: ATT(e) vector (9), 999 bootstrap draws (999x9),
      and the bootstrap covariance (9x9). NOTE: the e=-1 column is normalised to
      0 by construction, so its row/column is identically zero.

Read-only (LMOP + GHGRP). Association, not causal.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'
STRAT = ROOT / 'outputs/2026-11-09_rng_additionality_stratified/run_001/additionality_stratified_summary.json'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
NON_RNG_USE = {'Electricity', 'Direct'}

EV_LEVELS = ['pre_le_-5', 'k-4', 'k-3', 'k-2', 'k0', 'k1', 'k2', 'k3', 'post_ge_4']
PRE_LEVELS = ['pre_le_-5', 'k-4', 'k-3', 'k-2']
EVENTS = [-4, -3, -2, -1, 0, 1, 2, 3, 4]

# Import the CS module for exact reproduction of build_panel / cs_core / bootstrap_cs.
sys.path.insert(0, str(ROOT / 'scripts'))
import additionality_cs_did_20261109 as cs_mod


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def demean(df, cols, group):
    g = df.groupby(group)[cols].transform('mean')
    return df[cols].to_numpy(float) - g.to_numpy(float)


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_vcov(X, y, beta, clusters, g=1.0):
    """Full facility-clustered covariance. Same math as cluster_se() in the
    stratified script, but returns the whole matrix (v * dof)."""
    e = y - X @ beta
    score = X * e[:, None]
    H = X.T @ X
    meat = np.zeros((X.shape[1], X.shape[1]))
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    Hinv = np.linalg.pinv(H)
    v = Hinv @ meat @ Hinv
    ncl = len(np.unique(clusters))
    dof = (ncl / (ncl - 1.0)) * g
    return v * dof, ncl


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


def _json_safe(x):
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, np.ndarray):
        return _json_safe(x.tolist())
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if (f != f or f in (float('inf'), float('-inf'))) else f
    if isinstance(x, (np.integer, int)):
        return int(x)
    return x


def build_panel():
    """Identical to additionality_stratified_20261109.py main() panel build."""
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

    lf_flag = {}
    for lid in pi_lf:
        rows = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = rows[rows['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = set(pi_rows['Current Project Status'].astype(str).str.strip())
        ever_op = bool(statuses & {'Operational', 'Shutdown'})
        other = rows[rows['Project Type Category'].isin(NON_RNG_USE)]
        other_years = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((other_years < adopt[lid]).any())
        lf_flag[lid] = {'ever_op': ever_op, 'prior_use': prior_use, 'statuses': sorted(statuses)}

    def group_of(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        if not lids:
            return None
        ever_op = any(lf_flag[l]['ever_op'] for l in lids)
        prior_use = any(lf_flag[l]['prior_use'] for l in lids)
        if not ever_op:
            return 'excluded_status'
        return 'switch' if prior_use else 'new'

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
        grp = group_of(f) if is_treated else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year'])
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            conc = r['conc']
            row = {
                'facility_id': f, 'year': y,
                'conc': float(conc) if (pd.notna(conc) and 0 < conc <= 100) else np.nan,
                'wet': int(r['wet']),
                'treated': int(is_treated), 'control': int(is_control),
                'group': grp, 'Ti': Ti if is_treated else None, 'post': post,
                'event_time': (y - Ti) if (is_treated and Ti is not None) else None,
            }
            rows.append(row)
    return pd.DataFrame(rows)


def build_subset(pan, group_filter):
    treated_fac = set()
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        if (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1) and group_filter(g):
            treated_fac.add(f)
    control_fac = set(pan.loc[pan['control'] == 1, 'facility_id'])
    return pan[pan['facility_id'].isin(treated_fac | control_fac)].copy()


def event_study_full(panel, outcome, with_wet):
    keep = panel.copy()
    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    base = (['wet'] if with_wet else []) + yr_dummies
    keep['ev'] = keep['event_time'].apply(ev_bin)
    for lv in EV_LEVELS:
        keep[f'ev_{lv}'] = ((keep['ev'] == lv) & (keep['treated'] == 1)).astype(int)
    ev_cols = [f'ev_{lv}' for lv in EV_LEVELS]
    cols2 = base + ev_cols
    d2 = demean(keep, cols2 + [outcome], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2)
    V, ncl = cluster_vcov(X2, yw2, beta2, keep['facility_id'].to_numpy())
    idx = {c: cols2.index(c) for c in ev_cols}
    ixs = [idx[c] for c in ev_cols]
    beta_ev = np.array([beta2[i] for i in ixs], dtype=float)
    cov_ev = V[np.ix_(ixs, ixs)]
    pre_i = [ev_cols.index(f'ev_{c}') for c in PRE_LEVELS]
    return {
        'event_levels': ev_cols,
        'beta': beta_ev,
        'cov': cov_ev,
        'pre_trend_levels': PRE_LEVELS,
        'pre_trend_beta': beta_ev[pre_i],
        'pre_trend_cov': cov_ev[np.ix_(pre_i, pre_i)],
        'n_clusters': int(ncl),
        'n_facility_years': int(len(keep)),
        'n_treated': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
        'n_control': int(keep[keep['control'] == 1]['facility_id'].nunique()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--bootstrap', type=int, default=999)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    pan = build_panel()
    pan_conc = pan[pan['conc'].notna()]
    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }

    twfe = {}
    for gname, gfilter in groups.items():
        sub = build_subset(pan_conc, gfilter)
        twfe[gname] = event_study_full(sub, 'conc', with_wet=True)

    # CS: reuse exact build_panel/cs_core/bootstrap_cs from the CS script.
    treated_rows, control_rows = cs_mod.build_panel()

    def run_cs(rows):
        att, n_obs, overall = cs_mod.cs_core(rows, control_rows)
        atts_boot, overalls_boot = cs_mod.bootstrap_cs(rows, control_rows, n_rep=args.bootstrap)
        draws = np.array([atts_boot[e] for e in EVENTS], dtype=float).T  # (n_rep x 9)
        att_vec = np.array([att[e] for e in EVENTS], dtype=float)
        return {
            'events': EVENTS,
            'att': att_vec,
            'overall_att': overall,
            'bootstrap_draws': draws,
            'bootstrap_cov': np.cov(draws, rowvar=False),
            'bootstrap_mean': draws.mean(axis=0),
        }

    cs = {
        'all_ever_operational': run_cs(treated_rows),
        'new_rng': run_cs([r for r in treated_rows if r[2] == 'new']),
        'use_switch': run_cs([r for r in treated_rows if r[2] == 'switch']),
    }

    # Sanity: TWFE event-study beta must reproduce the final-spec stratified summary.
    strat = json.loads(STRAT.read_text(encoding='utf-8'))
    ref_ev = strat['results']['conc__all_ever_operational']['event_study']
    ref_beta = np.array([ref_ev[f'ev_{lv}']['coef'] for lv in EV_LEVELS], dtype=float)
    max_diff = float(np.nanmax(np.abs(twfe['all_ever_operational']['beta'] - ref_beta)))

    summary = _json_safe({
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'stratified_summary_sha256': sha(STRAT),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'estimator': {
            'twfe': 'within (facility FE) + year FE + wet dummy; event study over relative time, base k=-1',
            'cs': 'Callaway-Sant\'Anna never-treated; group-time ATT base g-1; facility block bootstrap',
        },
        'event_levels': EV_LEVELS, 'pre_trend_levels': PRE_LEVELS,
        'bootstrap_reps': args.bootstrap, 'bootstrap_seed': 12345,
        'note_cs_minus1': 'CS e=-1 column is normalised to 0 by construction; its covariance row/col is zero.',
        'sanity_reproduces_final_spec': {
            'ok': bool(max_diff < 1e-9),
            'max_abs_diff_vs_stratified_event_study': max_diff,
        },
        'twfe_event_study': twfe,
        'cs_event_study': cs,
    })
    (out / 'event_study_covariance_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'sanity_reproduces_final_spec': summary['sanity_reproduces_final_spec'],
                      'twfe_n_treated': summary['twfe_event_study']['all_ever_operational']['n_treated'],
                      'twfe_n_control': summary['twfe_event_study']['all_ever_operational']['n_control']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
