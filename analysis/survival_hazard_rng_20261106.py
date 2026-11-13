"""Week-3 first discrete-time hazard model of pipeline-injection RNG adoption.

Time-to-adoption of pipeline-injection RNG, modeled as a discrete-time (person-year)
pooled logit with calendar-year fixed effects (to absorb the RNG boom) and optional
state fixed effects. This is the temporal analogue of the Week-2 cross-sectional
logit, and is the piece that differentiates from the 2025 cross-sectional
"distance x size + logit" conference paper.

Cohort (pre-stated, documented):
  - risk set = analyzable continental-48+DC landfills with coordinates, pipeline
    coverage, waste>0, and an open year.
  - time origin = max(Year Landfill Opened, 1995)  (left truncation at the RNG era).
  - event = first pipeline-injection RNG project with Project Start Date year in
    [1995, 2024] (any status; the start date is the registry adoption time).
  - censored at 2024 (Construction/Planned with 2025-2027 starts are right-censored).
  - any landfill whose only PI-RNG start date predates 1995 (a data error, e.g. the
    1986 rows) is excluded from the risk set; McCarty Road auto-corrects via its 2021
    project, and the 1999 case stays in the era.

Specs: T1 = log_dist + log_waste + year FE; T2 = T1 + state FE (zero/all-event
states dropped, conditional-logit semantics). Standard errors: inverse-Hessian plus
landfill- and county-clustered for the distance effect.

Read-only inputs; no randomness; no causal claim; new run dir each time.
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
    local = df['RNG Delivery Method'].eq('Local Use')

    # event year per landfill: min PI RNG start year in [1995, 2024]
    rng_pi = df[is_rng & pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= ERA_START) & (rng_pi['sy'] <= CENSOR_YEAR)]
    event_year = valid.groupby('Landfill ID')['sy'].min()
    # landfills with only pre-1995 (data-error) PI RNG dates -> exclude from risk set
    all_pi = rng_pi.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: sorted(set(s)))
    bad_date_only = all_pi[all_pi.apply(lambda yrs: all(y < ERA_START for y in yrs))].index.tolist()
    has_local = set(df.loc[is_rng & local, 'Landfill ID'])

    lf = pd.read_csv(LANDFILL_CSV)
    dist = pd.read_csv(DIST_CSV)[['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']]
    m = lf.merge(dist, on='Landfill ID', how='left')
    m['event_year'] = m['Landfill ID'].map(event_year)
    m['has_open'] = m['opened'].notna() & (m['opened'] > 0)
    m['continental'] = m['state'].isin(CONTINENTAL)
    m['has_waste'] = m['waste_tons'].notna() & (m['waste_tons'] > 0)

    cohort = m[m['analyzable'] & m['has_coord'] & m['continental'] & (m['pipeline_covered'] == True)
               & m['has_waste'] & m['has_open'] & ~m['Landfill ID'].isin(bad_date_only)].copy()
    cohort['log_dist'] = np.log(cohort['nearest_pipeline_km_spherical'])
    cohort['log_waste'] = np.log(cohort['waste_tons'])
    cohort['entry'] = np.maximum(cohort['opened'].astype(int), ERA_START)
    cohort['exit'] = cohort['event_year'].fillna(CENSOR_YEAR).astype(int)
    # a landfill with event_year must have entry <= event_year; else treat as censored at exit
    cohort['has_event'] = cohort['event_year'].notna() & (cohort['entry'] <= cohort['exit'])

    # build person-year rows
    rows = []
    for _, r in cohort.iterrows():
        e = int(r['exit']); ev = r['event_year']
        for t in range(int(r['entry']), e + 1):
            rows.append({'Landfill ID': r['Landfill ID'], 'state': r['state'], 'county': r['county'],
                         'year': t, 'log_dist': r['log_dist'], 'log_waste': r['log_waste'],
                         'y': 1 if (pd.notna(ev) and t == int(ev)) else 0})
    py = pd.DataFrame(rows)
    py['state_county'] = py['state'].astype(str) + '|' + py['county'].fillna('').astype(str)

    y = py['y'].to_numpy()
    # baseline hazard dummies only for years that actually contain >=1 event;
    # zero-event years (pre-2004) otherwise quasi-separate and diverge.
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]

    def fit(cols, cluster_key=None, dfx=None, yy=None):
        dfx = py if dfx is None else dfx
        yy = y if yy is None else yy
        X = np.column_stack([np.ones(len(dfx))] + [dfx[c].to_numpy(float) for c in cols])
        names = ['const'] + cols
        beta, se = irls_logit(X, yy)
        res = {'n_py': int(len(yy)), 'n_events': int(yy.sum()),
               'coef': {c: float(beta[j]) for j, c in enumerate(names)},
               'se': {c: float(se[j]) for j, c in enumerate(names)},
               'p': {c: float(2 * (1 - _norm_cdf(abs(beta[j] / se[j])))) for j, c in enumerate(names)}}
        if cluster_key is not None:
            cr = cluster_robust(X, yy, beta, dfx[cluster_key].to_numpy())
            res['se_clustered_landfill'] = {c: float(cr[j]) for j, c in enumerate(names)}
            res['p_clustered_landfill'] = {c: float(2 * (1 - _norm_cdf(abs(beta[j] / cr[j])))) for j, c in enumerate(names)}
        if 'state_county' in dfx.columns:
            crc = cluster_robust(X, yy, beta, dfx['state_county'].to_numpy())
            res['se_clustered_county'] = {c: float(crc[j]) for j, c in enumerate(names)}
            res['p_clustered_county'] = {c: float(2 * (1 - _norm_cdf(abs(beta[j] / crc[j])))) for j, c in enumerate(names)}
        return res

    T1 = fit(['log_dist', 'log_waste'] + year_dummies, cluster_key='Landfill ID')

    # T2: add state FE (drop zero/all-event states)
    per_state = py.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    py2 = py[~py['state'].isin(drop)].copy()
    states2 = sorted(py2['state'].unique()); ref = states2[0]
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states2 if s != ref]
    y2 = py2['y'].to_numpy()

    T2 = fit(['log_dist', 'log_waste'] + year_dummies + state_cols, cluster_key='Landfill ID', dfx=py2, yy=y2)

    def g(res, key):
        b = res['coef'][key]; se = res['se'][key]; p = res['p'][key]
        se_cl = res.get('se_clustered_landfill', {}).get(key)
        p_cl = res.get('p_clustered_landfill', {}).get(key)
        se_cc = res.get('se_clustered_county', {}).get(key)
        p_cc = res.get('p_clustered_county', {}).get(key)
        return {'coef': b, 'se': se, 'p': p, 'hr_per_efold': float(np.exp(b)),
                'hr_per_10x': float(np.exp(b * np.log(10))),
                'se_clustered_landfill': se_cl, 'p_clustered_landfill': p_cl,
                'se_clustered_county': se_cc, 'p_clustered_county': p_cc}

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'landfill_csv': str(LANDFILL_CSV), 'dist_csv': str(DIST_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': True, 'synthetic_data_used': False,
        'cohort': {
            'n_landfills': int(len(cohort)), 'n_events': int(cohort['has_event'].sum()),
            'n_censored': int((~cohort['has_event']).sum()),
            'n_person_years': int(len(py)),
            'era': f'{ERA_START}-{CENSOR_YEAR}',
            'bad_date_excluded_landfills': bad_date_only,
            'local_use_landfills_in_risk_set': sorted(has_local & set(cohort['Landfill ID'])),
        },
        'T1_yearFE': g(T1, 'log_dist'), 'T1_log_waste': g(T1, 'log_waste'),
        'T2_yearFE_stateFE': g(T2, 'log_dist'), 'T2_log_waste': g(T2, 'log_waste'),
        'T1_n_py': T1['n_py'], 'T1_n_events': T1['n_events'],
        'T2_n_py': T2['n_py'], 'T2_n_events': T2['n_events'],
        'T2_dropped_states': drop,
        'log_waste_coefs': {'T1': T1['coef']['log_waste'], 'T2': T2['coef']['log_waste']},
    }
    (out / 'survival_hazard_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    py.to_csv(out / 'person_year.csv', index=False, encoding='utf-8-sig')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
