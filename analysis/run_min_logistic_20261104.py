"""Week-2 minimal logistic regression for the RNG-adoption go/no-go (Direction 1).

Pre-stated question: among analyzable continental-US landfills, is distance to
the nearest natural-gas pipeline associated with pipeline-injection RNG adoption,
after controlling for landfill size (waste in place) and state fixed effects?

Outcome = pipeline-injection RNG adopted (Operational/Construction/Planned),
derived fresh from the registered Sep2024 LMOP workbook (NOT the all-RNG flag).

Nested specs:
  M1: log(nearest_pipeline_km)
  M2: log(nearest_pipeline_km) + log(waste_tons)
  M3: log(nearest_pipeline_km) + log(waste_tons) + state fixed effects   <- go/no-go
M3 is a fixed-effects (conditional) logit: states with no within-state variation
in the outcome (0 events, or all events) carry no information on the slopes and
are dropped before fitting -- the standard way to avoid quasi-complete separation
from zero-event state dummies. Standard errors are inverse-Hessian; a
cluster-by-state robust SE is added for M3 (full spatial diagnostics deferred).

Read-only inputs; new run dir each time; no randomness; no causal claim.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
DIST_CSV = ROOT / 'outputs/2026-11-04_rng_pipeline_distance/run_002/nearest_pipeline_distance.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
ADOPT_STATUS = {'Operational', 'Construction', 'Planned'}

CONTINENTAL = {
    'AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA',
    'ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND',
    'OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC',
}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _norm_cdf(x):
    from math import erf
    return 0.5 * (1 + erf(x / np.sqrt(2)))


def irls_logit(X, y, ridge=0.0, maxiter=200, tol=1e-10):
    """Binary logistic MLE via IRLS; returns beta, se, vcov, converged, iter."""
    n, p = X.shape
    beta = np.zeros(p)
    converged = False
    it = 0
    for it in range(1, maxiter + 1):
        eta = X @ beta
        mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
        W = mu * (1 - mu)
        z = eta + (y - mu) / W
        Xw = X * np.sqrt(W)[:, None]
        zw = z * np.sqrt(W)
        A = Xw.T @ Xw + ridge * np.eye(p)
        b = Xw.T @ zw
        try:
            beta_new = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            beta_new = np.linalg.lstsq(A, b, rcond=None)[0]
        if np.max(np.abs(beta_new - beta)) < tol:
            beta = beta_new
            converged = True
            break
        beta = beta_new
    eta = X @ beta
    mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
    W = mu * (1 - mu)
    H = X.T @ (X * W[:, None]) + ridge * np.eye(p)
    vcov = np.linalg.inv(H)
    se = np.sqrt(np.diag(vcov))
    return beta, se, vcov, converged, it


def cluster_robust(X, y, beta, clusters):
    """Cluster-robust (sandwich) SE of a fitted logit, clustered on `clusters`."""
    eta = X @ beta
    mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
    score = X * (y - mu)[:, None]
    W = mu * (1 - mu)
    H = X.T @ (X * W[:, None])
    meat = np.zeros_like(H)
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    vcov = np.linalg.inv(H) @ meat @ np.linalg.inv(H)
    return np.sqrt(np.diag(vcov))


def fit_spec(name, y, df, cols, clusters=None):
    X = np.column_stack([np.ones(len(df)), df[cols].to_numpy(dtype=float)])
    names = ['const'] + cols
    beta, se, vcov, conv, it = irls_logit(X, y, ridge=0.0)
    out = {
        'name': name, 'n': int(len(y)), 'n_events': int(y.sum()), 'converged': conv, 'iters': it,
        'coef': {}, 'se': {}, 'z': {}, 'p': {}, 'or': {},
        'pseudo_r2_mcfadden': None,
    }
    for j, c in enumerate(names):
        z = beta[j] / se[j] if se[j] > 0 else np.nan
        p = 2 * (1 - _norm_cdf(abs(z))) if np.isfinite(z) else np.nan
        out['coef'][c] = float(beta[j])
        out['se'][c] = float(se[j])
        out['z'][c] = float(z)
        out['p'][c] = float(p)
        out['or'][c] = float(np.exp(beta[j]))
    eta = X @ beta
    ll_full = float(np.sum(y * eta - np.logaddexp(0, eta)))
    p0 = y.mean()
    ll_null = float(np.sum(y * np.log(p0) + (1 - y) * np.log(1 - p0)))
    out['pseudo_r2_mcfadden'] = 1 - ll_full / ll_null
    if clusters is not None:
        cr = cluster_robust(X, y, beta, clusters)
        out['se_clustered'] = {c: float(cr[j]) for j, c in enumerate(names)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    started = dt.datetime.now(dt.timezone.utc).isoformat()

    df = pd.read_excel(LMOP, sheet_name='LMOP Database')

    # --- outcome: pipeline-injection RNG adopted, fresh from raw rows ---
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    adopted = df['Current Project Status'].isin(ADOPT_STATUS)
    pi_landfills = set(df.loc[is_rng & pi & adopted, 'Landfill ID'])
    all_rng_landfills = set(df.loc[is_rng & adopted, 'Landfill ID'])
    local_use_landfills = set(df.loc[is_rng & df['RNG Delivery Method'].eq('Local Use') & adopted, 'Landfill ID'])
    n_pi = len(pi_landfills)
    n_rng = len(all_rng_landfills)
    n_local = len(local_use_landfills)

    lf = pd.read_csv(LANDFILL_CSV)
    dist = pd.read_csv(DIST_CSV)

    m = lf.merge(dist[['Landfill ID', 'nearest_pipeline_km', 'pipeline_covered']], on='Landfill ID', how='left')
    m['y'] = m['Landfill ID'].isin(pi_landfills).astype(int)
    m['is_local_use_rng'] = m['Landfill ID'].isin(local_use_landfills).astype(bool)

    m['continental'] = m['state'].isin(CONTINENTAL)
    m['has_logdist'] = m['pipeline_covered'] == True  # noqa: E712
    m['has_waste'] = m['waste_tons'].notna() & (m['waste_tons'] > 0)

    sample = m[m['analyzable'] & m['has_coord'] & m['continental'] & m['has_logdist'] & m['has_waste']].copy()
    sample['log_dist'] = np.log(sample['nearest_pipeline_km'])
    sample['log_waste'] = np.log(sample['waste_tons'])

    # per-state event counts -> separation check for the FE model
    per_state = sample.groupby('state')['y'].agg(events='sum', n='size').reset_index()
    per_state['all_or_none'] = (per_state['events'] == 0) | (per_state['events'] == per_state['n'])
    drop_states = per_state.loc[per_state['all_or_none'], 'state'].tolist()

    # M1 / M2 on the full sample
    y_full = sample['y'].to_numpy()
    results = {}
    results['M1_logdist'] = fit_spec('M1_logdist', y_full, sample, ['log_dist'])
    results['M2_logdist_logwaste'] = fit_spec('M2_logdist_logwaste', y_full, sample, ['log_dist', 'log_waste'])

    # M3: fixed-effects (conditional) logit -- drop zero/all-event states first
    sample_fe = sample[~sample['state'].isin(drop_states)].copy()
    states_fe = sorted(sample_fe['state'].unique())
    ref = states_fe[0]
    for s in states_fe:
        if s != ref:
            sample_fe[f'st_{s}'] = (sample_fe['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states_fe if s != ref]
    y_fe = sample_fe['y'].to_numpy()
    results['M3_stateFE'] = fit_spec('M3_stateFE', y_fe, sample_fe,
                                     ['log_dist', 'log_waste'] + state_cols,
                                     clusters=sample_fe['state'].to_numpy())

    m3 = results['M3_stateFE']
    b = m3['coef']['log_dist']; se = m3['se']['log_dist']; p = m3['p']['log_dist']
    se_cl = m3.get('se_clustered', {}).get('log_dist')
    p_cl = float(2 * (1 - _norm_cdf(abs(b / se_cl)))) if se_cl else None
    n_sig_states = sum(1 for c in state_cols if m3['p'].get(c) is not None and m3['p'][c] < 0.05)

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas', 'scipy']},
        'lmop_path': str(LMOP), 'lmop_sha256': sha(LMOP),
        'landfill_csv': str(LANDFILL_CSV), 'dist_csv': str(DIST_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': True, 'synthetic_data_used': False,
        'outcome_definition': 'pipeline-injection RNG (Project Type Category==RNG OR Delivery Method in RNG_METHODS) AND Delivery Method==Pipeline Injection AND Current Project Status in Operational/Construction/Planned',
        'outcome_counts': {'pipeline_injection_rng_landfills': n_pi,
                           'all_rng_adopted_landfills': n_rng,
                           'local_use_rng_landfills': n_local},
        'sample': {
            'n_full': int(len(sample)), 'n_events_full': int(y_full.sum()),
            'event_rate_pct': round(100 * y_full.mean(), 2),
            'sample_gate': 'analyzable & has_coord & continental48+DC & pipeline_covered & waste>0',
            'fe_dropped_states': drop_states,
            'n_fe': int(len(sample_fe)), 'n_events_fe': int(y_fe.sum()),
            'fe_state_reference': ref, 'fe_n_state_dummies': len(state_cols),
            'fe_n_significant_states_p05': n_sig_states,
        },
        'models': results,
        'go_nogo': {
            'log_dist_coef': b, 'log_dist_se': se, 'log_dist_p': p,
            'log_dist_or_per_efold': float(np.exp(b)),
            'log_dist_or_per_10x': float(np.exp(b * np.log(10))),
            'log_dist_clustered_se': se_cl, 'log_dist_clustered_p': p_cl,
        },
    }

    (out / 'min_logistic_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')
    sample[['Landfill ID', 'state', 'y', 'log_dist', 'log_waste', 'nearest_pipeline_km', 'waste_tons']].to_csv(
        out / 'analysis_sample.csv', index=False, encoding='utf-8-sig')

    print('=' * 78)
    for name in ['M1_logdist', 'M2_logdist_logwaste', 'M3_stateFE']:
        r = results[name]
        print(f"\n{name}  (n={r['n']}, events={r['n_events']}, pseudo-R2={r['pseudo_r2_mcfadden']:.4f}, converged={r['converged']})")
        for c in ['const', 'log_dist', 'log_waste']:
            if c in r['coef']:
                print(f"  {c:<16} coef={r['coef'][c]:9.4f}  se={r['se'][c]:9.4f}  z={r['z'][c]:7.2f}  p={r['p'][c]:.4g}")
        if name == 'M3_stateFE':
            print(f"  ... {len(state_cols)} state FE (ref={ref}); {n_sig_states} significant at p<0.05")
    print('\n' + '=' * 78)
    print('M3 go/no-go on log_dist: coef=%+.4f  se=%.4f  p=%.4g  OR(e-fold)=%.3f  OR(10x)=%.3f  cluster-se=%.4f  cluster-p=%.4g' % (
        b, se, p, np.exp(b), np.exp(b * np.log(10)), se_cl, p_cl))
    print('dropped (zero/all-event) states for FE:', drop_states)
    print(json.dumps(summary['go_nogo'], ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
