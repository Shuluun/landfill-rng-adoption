"""Numeric sensitivity for the consequence (additionality) line.

The GHGRP numeric-reliability audit (item 2) found ~4.8% of recovered/flow
facility-year rows have a physically-impossible implied efficiency, dominated by
facility-level flow-unit errors (flow reported ~1e5x too small) plus 1 row of
implausible concentration (99%). This script checks whether DROPPING those rows
changes the consequence DiD conclusions.

Reuses the FINAL consequence spec (additionality_stratified_20261109.py):
  treated = ever-operational PI-RNG (Planned/Construction excluded), split new/switch;
  control = never-RNG; outcomes = concentration (%, level, wet-controlled) and
  log(recovered CH4); TWFE + trend-adjusted DiD, facility FE + year FE, SE clustered
  by facility. Adds log(flow) as a third outcome (the field that carries the unit
  errors) and a dirty-row flag from the numeric audit.

Three filters compared per outcome x group:
  baseline  = full sample (matches the final spec);
  loose     = drop 104 eff>10 rows + 1 conc>70% row (105 facility-years);
  tight     = drop all physically-impossible rows (eff>1 or eff<0.01 or conc>70%).

Read-only; deterministic; new run dir.
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
CH4_DENSITY_MT_PER_SCF = 2.03e-5


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


def run_did(panel, outcome, with_wet):
    """TWFE + trend-adjusted DiD on `panel` (facility_id, year, wet, treated, post, outcome)."""
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    keep = panel.dropna(subset=[outcome]).copy()
    if len(keep) == 0:
        return None
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

    cols3 = base + ['post']
    Z = residualize_slope(keep, cols3 + [outcome], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    beta3 = ols(X3, y3); se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[cols3.index('post')]); tau3_se = float(se3[cols3.index('post')])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))

    return {
        'n_treated': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
        'n_control': int(keep[keep['control'] == 1]['facility_id'].nunique()),
        'n_facility_years': int(len(keep)),
        'twfe': {'coef': tau, 'se': tau_se, 'p': tau_p},
        'trend_adjusted': {'coef': tau3, 'se': tau3_se, 'p': tau3_p},
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

    # ---- dirty-row flags (from the numeric audit) ----
    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    ok3 = (gh['conc'] > 0) & (gh['flow'] > 0) & (gh['rec'] > 0)
    eff = pd.Series(np.nan, index=gh.index)
    eff.loc[ok3] = gh.loc[ok3, 'rec'] / (gh.loc[ok3, 'flow'] * gh.loc[ok3, 'conc'] / 100 * CH4_DENSITY_MT_PER_SCF)
    gh['eff'] = eff
    gh['dirty_loose'] = (eff > 10) | (gh['conc'] > 70)
    gh['dirty_tight'] = (eff > 1) | (eff < 0.01) | (gh['conc'] > 70)
    loose_set = set(zip(gh.loc[gh['dirty_loose'].fillna(False), 'facility_id'].astype('Int64'),
                        gh.loc[gh['dirty_loose'].fillna(False), 'reporting_year'].astype(int)))
    tight_set = set(zip(gh.loc[gh['dirty_tight'].fillna(False), 'facility_id'].astype('Int64'),
                        gh.loc[gh['dirty_tight'].fillna(False), 'reporting_year'].astype(int)))

    # ---- treated/control classification (matches additionality_stratified) ----
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
            conc = r['conc']; rec = r['rec']; flow = r['flow']
            rows.append({
                'facility_id': f, 'year': y,
                'conc': float(conc) if (pd.notna(conc) and 0 < conc <= 100) else np.nan,
                'log_rec': float(np.log(rec)) if (pd.notna(rec) and rec > 0) else np.nan,
                'log_flow': float(np.log(flow)) if (pd.notna(flow) and flow > 0) else np.nan,
                'wet': int(r['wet']),
                'treated': int(is_treated), 'control': int(is_control),
                'group': grp,
                'Ti': Ti if is_treated else None, 'post': post,
                'event_time': (y - Ti) if (is_treated and Ti is not None) else None,
            })
    pan = pd.DataFrame(rows)

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

    # filter levels
    def apply_filter(p, level):
        if level == 'baseline':
            return p.copy()
        drop = loose_set if level == 'loose' else tight_set
        return p[~p.set_index(['facility_id', 'year']).index.isin(drop)].copy()

    outcomes = {'conc': True, 'log_rec': False, 'log_flow': False}
    results = {}
    for oname, with_wet in outcomes.items():
        pan_o = pan[pan[oname].notna()]
        for gname, gfilter in groups.items():
            for level in ['baseline', 'loose', 'tight']:
                sub = apply_filter(pan_o, level)
                sub = build_subset(sub, gfilter)
                results[f'{oname}__{gname}__{level}'] = run_did(sub, oname, with_wet)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'filters': {
            'baseline': 'full sample (matches additionality_stratified_20261109.py)',
            'loose': 'drop 104 eff>10 + 1 conc>70% facility-years (105 rows)',
            'tight': 'drop all physically-impossible (eff>1 or eff<0.01 or conc>70%) facility-years',
        },
        'n_dropped_loose': int(len(loose_set)),
        'n_dropped_tight': int(len(tight_set)),
        'results': results,
    }
    (out / 'additionality_numeric_sensitivity_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
