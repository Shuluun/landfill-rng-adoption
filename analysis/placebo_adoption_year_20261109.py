"""Placebo adoption-year (Fisher) test for the concentration consequence DiD.

#3 of the inference-hardening plan. Question: is the ~+4pp concentration jump at
the actual RNG-PI adoption year larger than what a randomly re-assigned
(fake) adoption year would produce? If the true jump is extreme in this null,
the timing is informative rather than coincidental.

Design (Fisher randomization of treatment timing):
  - Hold the treated/control facility sets fixed (same sample as the final spec).
  - Permute the vector of adoption years across treated facilities (within each
    group: all_ever_operational / new_rng / use_switch), R=999 times.
  - For each permutation re-estimate the SAME TWFE DiD (wet + year FE + facility
    FE) post coefficient tau, and the trend-adjusted version tau3.
  - Null = R placebo values; report one/two-sided empirical p and standardized z.

Speed note: the fixed columns (wet, year dummies, outcome) are residualized once
per group; only the post column changes per permutation, so it is demeaned /
trend-residualized per rep with vectorized groupby transforms.

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

sys.path.insert(0, str(ROOT / 'scripts'))
import save_event_study_covariance_20261109 as cov_mod


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def demean_arr(col, grp):
    s = pd.Series(np.asarray(col, dtype=float), index=grp.index)
    return (s - s.groupby(grp).transform('mean')).to_numpy()


def trend_resid_arr(col, grp, td, den):
    """Vectorized facility linear-trend residualization of a single column.
    Equivalent to residualize_slope() applied to that column."""
    s = pd.Series(np.asarray(col, dtype=float), index=grp.index)
    cbar = s.groupby(grp).transform('mean').to_numpy()
    cd = s.to_numpy() - cbar
    num = pd.Series(cd * td, index=grp.index).groupby(grp).transform('sum').to_numpy()
    b = np.divide(num, den, out=np.zeros_like(num), where=den > 1e-12)
    return cd - b * td


def trend_resid_cols(df, cols, group, tcol):
    grp = df[group]
    t = df[tcol].to_numpy(float)
    tbar = df.groupby(group)[tcol].transform('mean').to_numpy()
    td = t - tbar
    den = pd.Series(td * td, index=df.index).groupby(grp).transform('sum').to_numpy()
    out = np.empty((len(df), len(cols)))
    for j, c in enumerate(cols):
        out[:, j] = trend_resid_arr(df[c].to_numpy(float), grp, td, den)
    return out


def pvals(null, true):
    null = np.asarray(null, dtype=float)
    null = null[np.isfinite(null)]
    if null.size == 0:
        return None, None, None, None
    up = float((null >= true).mean())
    lo = float((null <= true).mean())
    two = float(2 * min(up, lo))
    sd = float(null.std(ddof=0))
    z = float((true - null.mean()) / sd) if sd > 1e-12 else None
    return up, lo, two, z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--reps', type=int, default=999)
    ap.add_argument('--seed', type=int, default=12345)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    pan = cov_mod.build_panel()
    pan_conc = pan[pan['conc'].notna()].reset_index(drop=True)
    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }
    strat = json.loads(STRAT.read_text(encoding='utf-8'))
    rng = np.random.default_rng(args.seed)

    results = {}
    for gname, gfilter in groups.items():
        sub = cov_mod.build_subset(pan_conc, gfilter).reset_index(drop=True)
        years_sorted = sorted(sub['year'].unique())
        yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
        for t in years_sorted[1:]:
            sub[f'yr_{t}'] = (sub['year'] == t).astype(int)
        base_cols = ['wet'] + yr_dummies
        outcome = 'conc'

        grp = sub['facility_id']
        t = sub['year'].to_numpy(float)
        tbar = sub.groupby('facility_id')['year'].transform('mean').to_numpy()
        td = t - tbar
        den = pd.Series(td * td, index=sub.index).groupby(grp).transform('sum').to_numpy()

        Dbase = cov_mod.demean(sub, base_cols, 'facility_id')
        Dy = cov_mod.demean(sub, [outcome], 'facility_id')[:, 0]
        Zbase = trend_resid_cols(sub, base_cols, 'facility_id', 'year')
        Zy = trend_resid_cols(sub, [outcome], 'facility_id', 'year')[:, 0]

        treated = sub[sub['treated'] == 1]
        treated_fac = sorted(int(f) for f in treated['facility_id'].unique())
        Ti_true = {f: int(treated.loc[treated['facility_id'] == f, 'Ti'].iloc[0]) for f in treated_fac}
        fac = sub['facility_id'].to_numpy()
        yr = sub['year'].to_numpy()

        def build_post(ti_map):
            post = np.zeros(len(sub), dtype=float)
            for f in treated_fac:
                Ti = ti_map.get(f)
                if Ti is None:
                    continue
                m = fac == f
                post[m] = (yr[m] >= Ti).astype(float)
            return post

        def estimate(post):
            Dpost = demean_arr(post, grp)
            Zpost = trend_resid_arr(post, grp, td, den)
            beta = cov_mod.ols(np.column_stack([Dbase, Dpost]), Dy)
            tau = float(beta[-1])
            beta3 = cov_mod.ols(np.column_stack([Zbase, Zpost]), Zy)
            tau3 = float(beta3[-1])
            return tau, tau3

        tau_true, tau3_true = estimate(build_post(Ti_true))
        Ti_vals = [Ti_true[f] for f in treated_fac]
        null_tau, null_tau3 = [], []
        for _ in range(args.reps):
            perm = rng.permutation(len(treated_fac))
            ti_perm = {treated_fac[j]: Ti_vals[perm[j]] for j in range(len(treated_fac))}
            t1, t3 = estimate(build_post(ti_perm))
            null_tau.append(t1); null_tau3.append(t3)

        up, lo, two, z = pvals(null_tau, tau_true)
        up3, lo3, two3, z3 = pvals(null_tau3, tau3_true)
        results[gname] = {
            'n_treated': len(treated_fac),
            'n_control': int(sub[sub['control'] == 1]['facility_id'].nunique()),
            'true_post_coef_twfe': tau_true,
            'true_post_coef_trend_adjusted': tau3_true,
            'reference_stratified_twfe_post': strat['results'][f'conc__{gname}']['twfe_did']['post_coef'],
            'reference_stratified_trend_adj_post': strat['results'][f'conc__{gname}']['twfe_did_trend_adjusted']['post_coef'],
            'placebo_nulls': {
                'twfe': {'mean': float(np.mean(null_tau)), 'sd': float(np.std(null_tau)),
                         'p_upper': up, 'p_lower': lo, 'p_two_sided': two, 'z': z},
                'trend_adjusted': {'mean': float(np.mean(null_tau3)), 'sd': float(np.std(null_tau3)),
                                   'p_upper': up3, 'p_lower': lo3, 'p_two_sided': two3, 'z': z3},
            },
        }

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'stratified_summary_sha256': sha(STRAT), 'script_sha256': sha(__file__),
        'random_seed': args.seed, 'synthetic_data_used': False,
        'design': ('Fisher randomization of treatment timing: permute adoption years across '
                   'treated facilities within group, re-estimate TWFE DiD post coef and its '
                   'trend-adjusted version; null = R placebo draws.'),
        'reps': args.reps,
        'results': results,
    }
    (out / 'placebo_adoption_year_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
