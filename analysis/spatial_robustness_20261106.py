"""Week-3 spatial robustness: distance-method invariance + spatial autocorrelation.

(1) Re-fit the go/no-go logistic with the exact spherical great-circle distance
    (from verify_distance_geodesic_20261106.py) instead of the Week-1 local
    equirectangular distance, to show the result is invariant to the distance
    method.
(2) Moran's I on the M2 (distance + size) Pearson residuals, kNN weights, with a
    permutation p-value -- a direct test of residual spatial autocorrelation.
(3) Cluster-robust standard errors for the state-FE model clustered by STATE and
    by (state, county), to see whether finer spatial clustering erodes the
    pipeline-distance effect.

Read-only inputs; no randomness in the models (permutation test uses a fixed seed
and is reported as a diagnostic, not a fitted result); new run dir each time.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
DIST_CSV = ROOT / 'outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv'

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


def irls_logit(X, y, maxiter=200, tol=1e-10):
    n, p = X.shape
    beta = np.zeros(p)
    for _ in range(maxiter):
        eta = X @ beta
        mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
        W = mu * (1 - mu)
        z = eta + (y - mu) / W
        Xw = X * np.sqrt(W)[:, None]; zw = z * np.sqrt(W)
        A = Xw.T @ Xw; b = Xw.T @ zw
        try:
            bn = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            bn = np.linalg.lstsq(A, b, rcond=None)[0]
        if np.max(np.abs(bn - beta)) < tol:
            beta = bn; break
        beta = bn
    eta = X @ beta
    mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
    W = mu * (1 - mu)
    vcov = np.linalg.inv(X.T @ (X * W[:, None]))
    return beta, np.sqrt(np.diag(vcov))


def cluster_robust(X, y, beta, clusters):
    eta = X @ beta
    mu = np.clip(1.0 / (1.0 + np.exp(-eta)), 1e-10, 1 - 1e-10)
    score = X * (y - mu)[:, None]
    W = mu * (1 - mu)
    H = X.T @ (X * W[:, None])
    meat = np.zeros_like(H)
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    return np.sqrt(np.diag(np.linalg.inv(H) @ meat @ np.linalg.inv(H)))


def fit_logit(X, y, names, clusters=None):
    beta, se = irls_logit(X, y)
    out = {'coef': {c: float(beta[j]) for j, c in enumerate(names)},
           'se': {c: float(se[j]) for j, c in enumerate(names)}}
    for j, c in enumerate(names):
        out['coef'][c] = float(beta[j]); out['se'][c] = float(se[j])
        out.setdefault('z', {})[c] = float(beta[j] / se[j])
        out.setdefault('p', {})[c] = float(2 * (1 - _norm_cdf(abs(beta[j] / se[j]))))
    if clusters is not None:
        cr = cluster_robust(X, y, beta, clusters)
        out['se_clustered'] = {c: float(cr[j]) for j, c in enumerate(names)}
        out['p_clustered'] = {c: float(2 * (1 - _norm_cdf(abs(beta[j] / cr[j])))) for j, c in enumerate(names)}
    return out


def moran_i(e, neigh, nperm=999, seed=0):
    e = e - e.mean()
    We = e[neigh].mean(axis=1)
    I_obs = float((e @ We) / (e @ e))
    rng = np.random.default_rng(seed)
    null = np.empty(nperm)
    for p in range(nperm):
        ep = e[rng.permutation(len(e))]
        null[p] = float((ep @ (ep[neigh].mean(axis=1))) / (ep @ ep))
    p_gt = (np.sum(null >= I_obs) + 1) / (nperm + 1)
    p_two = float(min(1.0, 2 * min(p_gt, 1 - p_gt)))
    return {'I_obs': I_obs, 'E_I': -1.0 / (len(e) - 1), 'null_mean': float(null.mean()),
            'null_std': float(null.std()), 'z': float((I_obs - null.mean()) / null.std()),
            'p_upper': float(p_gt), 'p_two_sided': p_two, 'n_perm': nperm}


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
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    adopted = df['Current Project Status'].isin(ADOPT_STATUS)
    pi_landfills = set(df.loc[is_rng & pi & adopted, 'Landfill ID'])

    lf = pd.read_csv(LANDFILL_CSV)
    dist = pd.read_csv(DIST_CSV)[['Landfill ID', 'nearest_pipeline_km_spherical', 'nearest_pipeline_km_equirect', 'pipeline_covered']]
    m = lf.merge(dist, on='Landfill ID', how='left')
    m['y'] = m['Landfill ID'].isin(pi_landfills).astype(int)
    m['continental'] = m['state'].isin(CONTINENTAL)
    m['has_waste'] = m['waste_tons'].notna() & (m['waste_tons'] > 0)

    sample = m[m['analyzable'] & m['has_coord'] & m['continental'] & (m['pipeline_covered'] == True) & m['has_waste']].copy()
    sample['log_dist_sph'] = np.log(sample['nearest_pipeline_km_spherical'])
    sample['log_dist_equi'] = np.log(sample['nearest_pipeline_km_equirect'])
    sample['log_waste'] = np.log(sample['waste_tons'])
    sample['cluster_state'] = sample['state']
    sample['cluster_county'] = sample['state'].astype(str) + '|' + sample['county'].fillna('').astype(str)

    y = sample['y'].to_numpy()
    n = len(sample)

    # state FE: drop zero/all-event states (conditional-logit semantics)
    per_state = sample.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    fe = sample[~sample['state'].isin(drop)].copy()
    states_fe = sorted(fe['state'].unique()); ref = states_fe[0]
    for s in states_fe:
        if s != ref:
            fe[f'st_{s}'] = (fe['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states_fe if s != ref]
    y_fe = fe['y'].to_numpy()

    results = {}
    # M2: distance+size, full sample
    for tag, dcol in [('equi', 'log_dist_equi'), ('sph', 'log_dist_sph')]:
        X = np.column_stack([np.ones(n), sample[dcol].to_numpy(), sample['log_waste'].to_numpy()])
        results[f'M2_{tag}'] = fit_logit(X, y, ['const', 'log_dist', 'log_waste'])
    # M3: state FE, FE-drop sample
    for tag, dcol in [('equi', 'log_dist_equi'), ('sph', 'log_dist_sph')]:
        X = np.column_stack([np.ones(len(fe)), fe[dcol].to_numpy(), fe['log_waste'].to_numpy()] +
                            [fe[c].to_numpy() for c in state_cols])
        results[f'M3_{tag}'] = fit_logit(X, y_fe, ['const', 'log_dist', 'log_waste'] + state_cols,
                                         clusters=fe['cluster_county'].to_numpy())
        # state-cluster SE for comparison
        cr_state = cluster_robust(X, y_fe, irls_logit(X, y_fe)[0], fe['cluster_state'].to_numpy())
        results[f'M3_{tag}']['se_clustered_state'] = {'log_dist': float(cr_state[1])}

    # Moran's I on M2 (spherical) Pearson residuals, kNN k=8
    dcol = 'log_dist_sph'
    X2 = np.column_stack([np.ones(n), sample[dcol].to_numpy(), sample['log_waste'].to_numpy()])
    beta2, _ = irls_logit(X2, y)
    phat = 1.0 / (1.0 + np.exp(-(X2 @ beta2)))
    pearson = (y - phat) / np.sqrt(phat * (1 - phat))

    lonr = np.radians(sample['lon'].to_numpy()); latr = np.radians(sample['lat'].to_numpy())
    X3 = np.stack([np.cos(latr) * np.cos(lonr), np.cos(latr) * np.sin(lonr), np.sin(latr)], axis=1)
    tree = cKDTree(X3)
    k = 8
    _, idx = tree.query(X3, k=k + 1)
    neigh = idx[:, 1:]

    moran_resid = moran_i(pearson, neigh, seed=0)
    moran_y = moran_i(y.astype(float), neigh, seed=1)

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas', 'scipy']},
        'lmop_sha256': sha(LMOP), 'landfill_csv': str(LANDFILL_CSV), 'dist_csv': str(DIST_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': 'models: none (MLE); Moran permutation: fixed seeds 0/1', 'model_run': True, 'synthetic_data_used': False,
        'sample': {'n': n, 'n_events': int(y.sum()), 'event_rate_pct': round(100 * y.mean(), 2),
                   'fe_dropped_states': drop, 'n_fe': int(len(fe)), 'fe_ref': ref},
        'distance_method_invariance': {
            'M2_log_dist_coef': {'equi': results['M2_equi']['coef']['log_dist'], 'sph': results['M2_sph']['coef']['log_dist']},
            'M2_log_dist_p': {'equi': results['M2_equi']['p']['log_dist'], 'sph': results['M2_sph']['p']['log_dist']},
            'M3_log_dist_coef': {'equi': results['M3_equi']['coef']['log_dist'], 'sph': results['M3_sph']['coef']['log_dist']},
            'M3_log_dist_p': {'equi': results['M3_equi']['p']['log_dist'], 'sph': results['M3_sph']['p']['log_dist']},
        },
        'moran': {
            'knn_k': k,
            'm2_pearson_residuals': moran_resid,
            'raw_outcome_y': moran_y,
        },
        'clustered_se_log_dist': {
            'M3_sph_standard_se': results['M3_sph']['se']['log_dist'],
            'M3_sph_standard_p': results['M3_sph']['p']['log_dist'],
            'M3_sph_state_clustered_se': results['M3_sph']['se_clustered_state']['log_dist'],
            'M3_sph_county_clustered_se': results['M3_sph']['se_clustered']['log_dist'],
            'M3_sph_county_clustered_p': results['M3_sph']['p_clustered']['log_dist'],
            'n_county_clusters': int(fe['cluster_county'].nunique()),
            'n_state_clusters': int(fe['cluster_state'].nunique()),
        },
    }

    (out / 'spatial_robustness_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
