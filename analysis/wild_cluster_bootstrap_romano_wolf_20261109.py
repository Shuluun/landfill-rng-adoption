"""Wild cluster bootstrap (#4) and Romano-Wolf stepdown (#5) for the consequence line.

#4 WCB: Rademacher wild cluster bootstrap (facility cluster) for the TWFE DiD
post coefficient on concentration, in BOTH the raw spec and the trend-adjusted
spec, per group (all/new/switch). Gives few-cluster-robust p-values and 95% CIs
to cross-check the asymptotic cluster-robust SEs.

#5 Romano-Wolf: stepdown FWER control across the 3 outcomes
(concentration / log recovered CH4 / log landfill-gas flow) for the
all-ever-operational group, using the TREND-ADJUSTED statistic (the headline
specification). Raw TWFE is NOT used for rec/flow because their raw positive
association reflects sector-wide rising trends, not an adoption jump; the
"量无/气量无" conclusion is a trend-adjusted null.

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


def trend_resid_arr(col, grp, td, den):
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


def build_panel3():
    pan = cov_mod.build_panel()
    gh = pd.read_csv(GHGRP, dtype={'facility_id': 'Int64'})
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')
    m = pan.merge(gh[['fac', 'year', 'rec', 'flow']].rename(columns={'fac': 'facility_id'}),
                  on=['facility_id', 'year'], how='left')
    m['log_rec'] = np.log(np.where(m['rec'] > 0, m['rec'], np.nan))
    m['log_flow'] = np.log(np.where(m['flow'] > 0, m['flow'], np.nan))
    return m


def _add_year_dummies(keep):
    years_sorted = sorted(keep['year'].unique())
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    return [f'yr_{t}' for t in years_sorted[1:]]


def make_design(sub, outcome, with_wet, trend_adjusted):
    keep = sub.copy()
    yr_dummies = _add_year_dummies(keep)
    base = (['wet'] if with_wet else []) + yr_dummies
    cols = base + ['post']
    clusters = keep['facility_id'].to_numpy()
    if trend_adjusted:
        Z = trend_resid_cols(keep, cols + [outcome], 'facility_id', 'year')
        X = Z[:, :len(cols)]; y = Z[:, len(cols)]
    else:
        d = cov_mod.demean(keep, cols + [outcome], 'facility_id')
        X = d[:, :len(cols)]; y = d[:, len(cols)]
    return X, y, clusters, len(base)


def rademacher_weights(clusters, rng):
    ucl = np.unique(clusters)
    w = rng.choice(np.array([-1.0, 1.0]), size=len(ucl))
    wmap = dict(zip(ucl, w))
    return np.array([wmap[c] for c in clusters])


def wcb(X, y, clusters, post_idx, B, seed):
    beta = cov_mod.ols(X, y)
    resid = y - X @ beta
    V, _ = cov_mod.cluster_vcov(X, y, beta, clusters)
    se = float(np.sqrt(max(V[post_idx, post_idx], 0.0)))
    tau = float(beta[post_idx])
    t_obs = tau / se if se > 1e-12 else np.inf

    cols_r = [j for j in range(X.shape[1]) if j != post_idx]
    Xr = X[:, cols_r]
    beta_r = cov_mod.ols(Xr, y)
    e_r = y - Xr @ beta_r

    rng = np.random.default_rng(seed)
    t_boot = np.empty(B); tau_ci = np.empty(B)
    for b in range(B):
        wv = rademacher_weights(clusters, rng)
        y_star_r = Xr @ beta_r + e_r * wv
        beta_b = cov_mod.ols(X, y_star_r)
        tau_b = float(beta_b[post_idx])
        Vb, _ = cov_mod.cluster_vcov(X, y_star_r, beta_b, clusters)
        se_b = float(np.sqrt(max(Vb[post_idx, post_idx], 1e-12)))
        t_boot[b] = tau_b / se_b
        y_star_u = X @ beta + resid * wv
        tau_ci[b] = float(cov_mod.ols(X, y_star_u)[post_idx])

    p_restricted = float((np.abs(t_boot) >= np.abs(t_obs)).mean())
    ci = (float(np.percentile(tau_ci, 2.5)), float(np.percentile(tau_ci, 97.5)))
    return {
        'tau': tau, 'se': se, 't': t_obs, 'p_wcb_restricted': p_restricted,
        'ci95_unrestricted': list(ci),
        'boot_mean_restricted': float(np.mean(t_boot)), 'boot_sd_restricted': float(np.std(t_boot)),
    }


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
    B, seed = args.reps, args.seed

    pan = build_panel3()
    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }

    # ---- #4 WCB on concentration, raw + trend-adjusted, three groups ----
    pan_conc = pan[pan['conc'].notna()].reset_index(drop=True)
    wcb_results = {}
    for gname, gfilter in groups.items():
        sub = cov_mod.build_subset(pan_conc, gfilter).reset_index(drop=True)
        entry = {'n_clusters': int(sub['facility_id'].nunique()),
                 'n_treated': int(sub[sub['treated'] == 1]['facility_id'].nunique())}
        for spec, trend in [('raw_twfe', False), ('trend_adjusted', True)]:
            X, y, clusters, post_idx = make_design(sub, 'conc', True, trend)
            entry[spec] = wcb(X, y, clusters, post_idx, B, seed)
        wcb_results[gname] = entry

    # ---- #5 Romano-Wolf stepdown (TREND-ADJUSTED), 3 outcomes, all group ----
    outcomes = [('conc', True), ('log_rec', False), ('log_flow', False)]
    designs = {}
    t_obs = {}
    all_fac = set()
    for oname, with_wet in outcomes:
        sub_all = cov_mod.build_subset(pan[pan[oname].notna()].reset_index(drop=True),
                                       groups['all_ever_operational']).reset_index(drop=True)
        X, y, clusters, post_idx = make_design(sub_all, oname, with_wet=with_wet, trend_adjusted=True)
        beta = cov_mod.ols(X, y)
        V, _ = cov_mod.cluster_vcov(X, y, beta, clusters)
        se = float(np.sqrt(max(V[post_idx, post_idx], 0.0)))
        t_obs[oname] = float(beta[post_idx]) / se if se > 1e-12 else np.inf
        cols_r = [j for j in range(X.shape[1]) if j != post_idx]
        Xr = X[:, cols_r]
        beta_r = cov_mod.ols(Xr, y)
        designs[oname] = {'X': X, 'y': y, 'clusters': clusters, 'post_idx': post_idx,
                          'Xr': Xr, 'beta_r': beta_r, 'e_r': y - Xr @ beta_r,
                          'tau': float(beta[post_idx])}
        all_fac |= set(np.unique(clusters))

    K = len(outcomes)
    onames = [o for o, _ in outcomes]
    rng = np.random.default_rng(seed)
    t_star = np.zeros((B, K))
    for b in range(B):
        uf = np.array(sorted(all_fac))
        w = rng.choice(np.array([-1.0, 1.0]), size=len(uf))
        wmap = dict(zip(uf, w))
        for oi, oname in enumerate(onames):
            d = designs[oname]
            wv = np.array([wmap[c] for c in d['clusters']])
            y_star = d['Xr'] @ d['beta_r'] + d['e_r'] * wv
            beta_b = cov_mod.ols(d['X'], y_star)
            Vb, _ = cov_mod.cluster_vcov(d['X'], y_star, beta_b, d['clusters'])
            se_b = float(np.sqrt(max(Vb[d['post_idx'], d['post_idx']], 1e-12)))
            t_star[b, oi] = abs(float(beta_b[d['post_idx']]) / se_b)

    obs_abs = np.array([abs(t_obs[o]) for o in onames])
    order = list(np.argsort(-obs_abs))
    rw_adj = {}
    for j in range(K):
        family = order[j:]
        m_b = t_star[:, family].max(axis=1)
        rw_adj[onames[order[j]]] = float((m_b >= obs_abs[order[j]]).mean())

    from math import erf
    norm = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    asym_p = {o: float(2 * (1 - norm(abs(t_obs[o])))) for o in onames}
    sp = sorted([(asym_p[o], o) for o in onames])
    holm = {}
    for r, (_, o) in enumerate(sp):
        holm[o] = float(min(1.0, asym_p[o] * (K - r)))

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'stratified_summary_sha256': sha(STRAT), 'script_sha256': sha(__file__),
        'random_seed': seed, 'synthetic_data_used': False, 'reps': B,
        'wcb_concentration': wcb_results,
        'romano_wolf': {
            'note': 'Romano-Wolf uses the TREND-ADJUSTED DiD statistic (headline spec); '
                    'raw TWFE is not used for rec/flow because their raw positive association '
                    'reflects sector-wide rising trends, not an adoption jump.',
            'outcomes': onames,
            'trend_adjusted_coefs': {o: designs[o]['tau'] for o in onames},
            'observed_abs_t_trend_adjusted': {o: abs(t_obs[o]) for o in onames},
            'asymptotic_p_two_sided_trend_adjusted': asym_p,
            'holm_bonferroni_p': holm,
            'romano_wolf_stepdown_p': rw_adj,
        },
    }
    (out / 'wild_cluster_bootstrap_romano_wolf_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'wcb_concentration': wcb_results, 'romano_wolf': summary['romano_wolf']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
