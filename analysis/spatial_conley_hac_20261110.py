"""Spatial Conley HAC standard errors for the corrected driver hazard model.

The driver's last hard flaw is residual spatial autocorrelation (Moran's I on the
cross-sectional logit residuals, p=0.004), which threatens the distance effect's
inference because spatially-correlated errors shrink the effective sample.

The standard fix is Conley (1999) spatial-HAC standard errors: a sandwich variance
whose meat is the sum over landfill PAIRS of score outer-products, weighted by a
distance kernel (Bartlett: w = 1 - d/cutoff for d<cutoff, else 0). At cutoff -> 0
this reduces to the landfill-clustered SE already reported; at larger cutoffs it
additionally admits spatial dependence that decays with distance.

This runs it on the MAIN result (ev_opshut, corrected by the 36-facility audit)
and on the pre-correction ev_opshut, across a grid of distance cutoffs, on the
T2 (year + state FE) specification.

Read-only inputs; deterministic; new run dir.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
DIST_CSV = ROOT / 'outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
CONTINENTAL = {
    'AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA',
    'ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND',
    'OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC',
}
ERA_START = 1995
CENSOR_YEAR = 2024
R_EARTH_KM = 6371.0

NEVER_OP = {
    9:    ('real', 2025), 20:   ('real', 2025), 184:  ('real', 2024),
    460:  ('false', None), 495:  ('false', None), 554:  ('real', 2024),
    559:  ('real', 2023), 679:  ('real', 2024), 688:  ('real', 2024),
    705:  ('false', None), 816:  ('false', None), 829:  ('real', 2025),
    838:  ('real', 2024), 945:  ('false', None), 1080: ('uncertain', None),
    1150: ('uncertain', None), 1223: ('false', None), 1238: ('false', None),
    1415: ('real', 2025), 1539: ('uncertain', None), 1624: ('real', 2024),
    1819: ('false', None), 2001: ('real', 2024), 2048: ('real', 2024),
    2068: ('real', 2025), 2165: ('real', 2025), 2323: ('real', 2024),
    2336: ('real', 2024), 2424: ('false', None), 2429: ('real', 2024),
    10407: ('false', None), 10520: ('real', 2026), 10620: ('real', 2025),
    11120: ('false', None), 12144: ('real', 2024), 21203: ('real', 2025),
}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _norm_cdf(x):
    from math import erf
    return 0.5 * (1 + erf(x / np.sqrt(2)))


def _sigmoid(eta):
    return 1.0 / (1.0 + np.exp(-np.clip(eta, -40, 40)))


def irls_logit(X, y, maxiter=300, tol=1e-10, ridge=1e-6):
    n, p = X.shape
    beta = np.zeros(p)
    for _ in range(maxiter):
        eta = X @ beta
        mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
        W = mu * (1 - mu)
        z = eta + (y - mu) / W
        Xw = X * np.sqrt(W)[:, None]; zw = z * np.sqrt(W)
        A = Xw.T @ Xw + ridge * np.eye(p); b = Xw.T @ zw
        try:
            bn = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            bn = np.linalg.lstsq(A, b, rcond=None)[0]
        if np.max(np.abs(bn - beta)) < tol:
            beta = bn; break
        beta = bn
    eta = X @ beta
    mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
    W = mu * (1 - mu)
    vcov = np.linalg.inv(X.T @ (X * W[:, None]) + ridge * np.eye(p))
    return beta, np.sqrt(np.diag(vcov))


def cluster_robust(X, y, beta, clusters):
    eta = X @ beta
    mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
    score = X * (y - mu)[:, None]
    W = mu * (1 - mu)
    H = X.T @ (X * W[:, None])
    meat = np.zeros_like(H)
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    Hinv = np.linalg.inv(H)
    return np.sqrt(np.diag(Hinv @ meat @ Hinv))


def build_inputs():
    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    local = df['RNG Delivery Method'].eq('Local Use')

    rng_pi = df[is_rng & pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    rng_pi['status'] = rng_pi['Current Project Status'].astype(str).str.strip()

    def ev_year(statuses):
        sub = rng_pi[rng_pi['status'].isin(statuses)]
        sub = sub[(sub['sy'] >= ERA_START) & (sub['sy'] <= CENSOR_YEAR)]
        return sub.groupby('Landfill ID')['sy'].min()

    ev_all = ev_year({'Operational', 'Shutdown', 'Planned', 'Construction'})
    ev_opshut = ev_year({'Operational', 'Shutdown'})

    all_pi = rng_pi.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: sorted(set(s)))
    bad_date_only = set(all_pi[all_pi.apply(lambda yrs: all(y < ERA_START for y in yrs))].index.tolist())

    lf = pd.read_csv(LANDFILL_CSV)
    dist = pd.read_csv(DIST_CSV)[['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']]
    m = lf.merge(dist, on='Landfill ID', how='left')
    m['has_open'] = m['opened'].notna() & (m['opened'] > 0)
    m['continental'] = m['state'].isin(CONTINENTAL)
    m['has_waste'] = m['waste_tons'].notna() & (m['waste_tons'] > 0)

    cohort = m[m['analyzable'] & m['has_coord'] & m['continental'] & (m['pipeline_covered'] == True)
               & m['has_waste'] & m['has_open'] & ~m['Landfill ID'].isin(bad_date_only)].copy()
    cohort['log_dist'] = np.log(cohort['nearest_pipeline_km_spherical'])
    cohort['log_waste'] = np.log(cohort['waste_tons'])
    cohort['entry'] = np.maximum(cohort['opened'].astype(int), ERA_START)
    return df, cohort, dict(ev_all=ev_all, ev_opshut=ev_opshut)


def correct_event_map(event_map, corrected_for_evall):
    d = {int(k): int(v) for k, v in event_map.items()}
    for lid, (cls, yr) in NEVER_OP.items():
        if cls == 'real' and yr is not None and yr <= CENSOR_YEAR:
            d[lid] = yr
        elif corrected_for_evall:
            d.pop(lid, None)
    return pd.Series(d)


def build_py(cohort, event_map):
    c = cohort.copy()
    c['event_year'] = c['Landfill ID'].map(event_map)
    c['exit'] = c['event_year'].fillna(CENSOR_YEAR).astype(int)
    rows = []
    for _, r in c.iterrows():
        e = int(r['exit']); evt = r['event_year']
        for t in range(int(r['entry']), e + 1):
            rows.append({'Landfill ID': r['Landfill ID'], 'state': r['state'], 'county': r['county'],
                         'year': t, 'log_dist': r['log_dist'], 'log_waste': r['log_waste'],
                         'y': 1 if (pd.notna(evt) and t == int(evt)) else 0})
    return pd.DataFrame(rows)


def fit_stateFE(py):
    y = py['y'].to_numpy()
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]
    per_state = py.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    py2 = py[~py['state'].isin(drop)].copy()
    states2 = sorted(py2['state'].unique()); ref = states2[0]
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states2 if s != ref]
    cols = ['log_dist', 'log_waste'] + year_dummies + state_cols
    X = np.column_stack([np.ones(len(py2))] + [py2[c].to_numpy(float) for c in cols])
    y2 = py2['y'].to_numpy()
    beta, se = irls_logit(X, y2)
    mu = np.clip(_sigmoid(X @ beta), 1e-12, 1 - 1e-12)
    return dict(py=py2, X=X, y=y2, beta=beta, se=se, mu=mu, cols=cols,
                n_py=int(len(y2)), n_events=int(y2.sum()), dropped=drop, ref=ref)


def landfill_score_and_coords(fe, coord_map):
    """Sum person-year scores to landfill level and align coordinates."""
    # scores
    score = fe['X'] * (fe['y'] - fe['mu'])[:, None]
    sf = pd.DataFrame(score, columns=['c%d' % j for j in range(score.shape[1])])
    sf['Landfill ID'] = fe['py']['Landfill ID'].to_numpy()
    S = sf.groupby('Landfill ID')[['c%d' % j for j in range(score.shape[1])]].sum()
    lf_ids = S.index.to_numpy(int)
    S = S.to_numpy(float)
    # coordinates (unit sphere)
    lat = np.array([coord_map[i][0] for i in lf_ids])
    lon = np.array([coord_map[i][1] for i in lf_ids])
    latr = np.radians(lat); lonr = np.radians(lon)
    coords = np.stack([np.cos(latr) * np.cos(lonr), np.cos(latr) * np.sin(lonr), np.sin(latr)], axis=1)
    return S, coords, lf_ids


def conley_se(S, coords, H, cutoff_km):
    dot = coords @ coords.T
    np.clip(dot, -1.0, 1.0, out=dot)
    D = R_EARTH_KM * np.arccos(dot)
    W = np.clip(1.0 - D / cutoff_km, 0.0, 1.0)  # Bartlett kernel
    meat = S.T @ W @ S
    Hinv = np.linalg.inv(H)
    vcov = Hinv @ meat @ Hinv
    se = np.sqrt(np.clip(np.diag(vcov), 0, None))
    return se, int((W > 0).sum()), float(W.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    df, cohort, event_map = build_inputs()
    coord_map = {int(r['Landfill ID']): (r['lat'], r['lon']) for _, r in cohort.iterrows()}

    ev_opshut_orig = event_map['ev_opshut']
    ev_opshut_corr = correct_event_map(ev_opshut_orig, corrected_for_evall=False)

    cutoffs = [25, 50, 100, 200, 400]
    results = {}
    for name, em in [('ev_opshut_orig', ev_opshut_orig), ('ev_opshut_corr', ev_opshut_corr)]:
        py = build_py(cohort, em)
        fe = fit_stateFE(py)
        beta = fe['beta']; i_logdist = 1  # cols = ['log_dist','log_waste',...] -> index 1
        coef = float(beta[i_logdist])
        # standard
        se_std = float(fe['se'][i_logdist])
        p_std = float(2 * (1 - _norm_cdf(abs(coef / se_std))))
        # landfill-cluster (reference)
        cr = cluster_robust(fe['X'], fe['y'], beta, fe['py']['Landfill ID'].to_numpy())
        se_lf = float(cr[i_logdist])
        p_lf = float(2 * (1 - _norm_cdf(abs(coef / se_lf))))
        # Conley HAC
        S, coords, lf_ids = landfill_score_and_coords(fe, coord_map)
        H = fe['X'].T @ (fe['X'] * (fe['mu'] * (1 - fe['mu']))[:, None])
        conley = {}
        for c in cutoffs:
            se_c, n_pairs, w_sum = conley_se(S, coords, H, c)
            conley[str(c)] = {'se': float(se_c[i_logdist]),
                              'p': float(2 * (1 - _norm_cdf(abs(coef / se_c[i_logdist])))),
                              'n_landfill_pairs_weighted': n_pairs, 'w_sum': float(w_sum)}
        results[name] = {
            'coef_log_dist': coef, 'se_standard': se_std, 'p_standard': p_std,
            'se_landfill_cluster': se_lf, 'p_landfill_cluster': p_lf,
            'n_landfills': int(len(lf_ids)), 'n_events': fe['n_events'], 'n_person_years': fe['n_py'],
            'dropped_states': fe['dropped'],
            'conley_km': conley,
        }

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'landfill_csv': str(LANDFILL_CSV), 'dist_csv': str(DIST_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': True, 'synthetic_data_used': False,
        'kernel': 'Bartlett, w = max(0, 1 - d/cutoff)',
        'cohort_n_landfills': int(len(cohort)),
        'results': results,
    }
    (out / 'spatial_conley_hac_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
