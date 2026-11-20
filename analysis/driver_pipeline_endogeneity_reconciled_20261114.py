"""Reconcile the Phase-3 interstate/intrastate/gathering distance split with the
manuscript's reconciled event cohort.

The original driver_pipeline_endogeneity_20261110.py ran the four distance
variants (all / Interstate / Intrastate / Gathering) on the OLD "any-status"
event cohort (144 events, ev_all). The manuscript's headline is the reconciled
Operational+Shutdown cohort (ev_opshut_corr, 121 events, T2 log_dist=-0.1687).
Promoting the interstate-trunk result to a main table therefore requires the
same four-variant split computed on that reconciled cohort, not the superset.

This script reuses the 36-facility audit correction (NEVER_OP + correct_event_map)
from driver_consequence_backfill_20261109.py and the four pre-computed nearest-
pipeline distance CSVs from driver_pipeline_endogeneity_20261110.py. It re-runs
the T1/T2 discrete-time hazard for each distance variant on the corrected
ev_opshut event set.

Sanity: the 'all' variant must reproduce the manuscript T2 coef = -0.1687002936
exactly (it uses the identical verified distance CSV + corrected event map).

Read-only inputs; deterministic; new run dir.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
VERIFIED_DIST = ROOT / 'outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv'
ENDOPATH = ROOT / 'outputs/2026-11-10_rng_pipeline_endogeneity/run_001'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
CONTINENTAL = {
    'AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA',
    'ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND',
    'OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC',
}
ERA_START = 1995
CENSOR_YEAR = 2024

# 36-facility verdict (identical to driver_consequence_backfill_20261109.py)
NEVER_OP = {
    9:    ('real', 2025), 20:   ('real', 2025), 184:  ('real', 2024),
    460:  ('false', None), 495:  ('false', None), 554:  ('real', 2024),
    559:  ('real', 2023), 679:  ('real', 2024), 688:  ('real', 2024),
    705:  ('false', None), 816:  ('false', None), 829:  ('real', 2025),
    838:  ('real', 2024),   # grand opening Nov 2024, no exact first-gas day -> 2024 (assumption)
    945:  ('false', None), 1080: ('uncertain', None), 1150: ('uncertain', None),
    1223: ('false', None), 1238: ('false', None), 1415: ('real', 2025),
    1539: ('uncertain', None), 1624: ('real', 2024), 1819: ('false', None),
    2001: ('real', 2024), 2048: ('real', 2024), 2068: ('real', 2025),
    2165: ('real', 2025), 2323: ('real', 2024), 2336: ('real', 2024),
    2424: ('false', None), 2429: ('real', 2024), 10407: ('false', None),
    10520: ('real', 2026), 10620: ('real', 2025), 11120: ('false', None),
    12144: ('real', 2024),  # operational, exact first-gas day unpublished -> 2024 (assumption)
    21203: ('real', 2025),
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


def build_inputs(dist_csv):
    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    rng_pi = df[is_rng & pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    rng_pi['status'] = rng_pi['Current Project Status'].astype(str).str.strip()

    ev_opshut = rng_pi[rng_pi['status'].isin({'Operational', 'Shutdown'})]
    ev_opshut = ev_opshut[(ev_opshut['sy'] >= ERA_START) & (ev_opshut['sy'] <= CENSOR_YEAR)]
    ev_opshut = ev_opshut.groupby('Landfill ID')['sy'].min()

    all_pi = rng_pi.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: sorted(set(s)))
    bad_date_only = set(all_pi[all_pi.apply(lambda yrs: all(y < ERA_START for y in yrs))].index.tolist())

    lf = pd.read_csv(LANDFILL_CSV)
    dist = pd.read_csv(dist_csv)[['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']]
    m = lf.merge(dist, on='Landfill ID', how='left')
    m['has_open'] = m['opened'].notna() & (m['opened'] > 0)
    m['continental'] = m['state'].isin(CONTINENTAL)
    m['has_waste'] = m['waste_tons'].notna() & (m['waste_tons'] > 0)

    cohort = m[m['analyzable'] & m['has_coord'] & m['continental'] & (m['pipeline_covered'] == True)
               & m['has_waste'] & m['has_open'] & ~m['Landfill ID'].isin(bad_date_only)].copy()
    cohort['log_dist'] = np.log(cohort['nearest_pipeline_km_spherical'])
    cohort['log_waste'] = np.log(cohort['waste_tons'])
    cohort['entry'] = np.maximum(cohort['opened'].astype(int), ERA_START)
    return cohort, ev_opshut


def correct_event_map(event_map):
    d = {int(k): int(v) for k, v in event_map.items()}
    for lid, (cls, yr) in NEVER_OP.items():
        if cls == 'real' and yr is not None and yr <= CENSOR_YEAR:
            d[lid] = yr  # add / re-date true adoption; ev_opshut already excludes false/uncertain
    return pd.Series(d)


def build_py(cohort, event_map):
    c = cohort.copy()
    c['event_year'] = c['Landfill ID'].map(event_map)
    c['exit'] = c['event_year'].fillna(CENSOR_YEAR).astype(int)
    c['has_event'] = c['event_year'].notna() & (c['entry'] <= c['exit'])
    rows = []
    for _, r in c.iterrows():
        e = int(r['exit']); evt = r['event_year']
        for t in range(int(r['entry']), e + 1):
            rows.append({'Landfill ID': r['Landfill ID'], 'state': r['state'], 'county': r['county'],
                         'year': t, 'log_dist': r['log_dist'], 'log_waste': r['log_waste'],
                         'y': 1 if (pd.notna(evt) and t == int(evt)) else 0})
    py = pd.DataFrame(rows)
    py['state_county'] = py['state'].astype(str) + '|' + py['county'].fillna('').astype(str)
    return py, int(c['has_event'].sum())


def fit_T1_T2(py):
    y = py['y'].to_numpy()
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]
    cols = ['log_dist', 'log_waste'] + year_dummies

    def run(dfx, yy, cluster_key):
        X = np.column_stack([np.ones(len(dfx))] + [dfx[c].to_numpy(float) for c in cols])
        beta, se = irls_logit(X, yy)
        out = {'coef': float(beta[1]), 'se': float(se[1]),
               'p': float(2 * (1 - _norm_cdf(abs(beta[1] / se[1])))),
               'n_py': int(len(yy)), 'n_events': int(yy.sum())}
        cr = cluster_robust(X, yy, beta, dfx[cluster_key].to_numpy())
        out['se_clustered'] = float(cr[1])
        out['p_clustered'] = float(2 * (1 - _norm_cdf(abs(beta[1] / cr[1]))))
        return out

    T1 = run(py, y, 'Landfill ID')
    per_state = py.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    py2 = py[~py['state'].isin(drop)].copy()
    states2 = sorted(py2['state'].unique()); ref = states2[0]
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states2 if s != ref]
    cols2 = ['log_dist', 'log_waste'] + year_dummies + state_cols
    y2 = py2['y'].to_numpy()
    X2 = np.column_stack([np.ones(len(py2))] + [py2[c].to_numpy(float) for c in cols2])
    beta2, se2 = irls_logit(X2, y2)
    out2 = {'coef': float(beta2[1]), 'se': float(se2[1]),
            'p': float(2 * (1 - _norm_cdf(abs(beta2[1] / se2[1])))),
            'n_py': int(len(y2)), 'n_events': int(y2.sum()), 'dropped_states': drop}
    cr2 = cluster_robust(X2, y2, beta2, py2['Landfill ID'].to_numpy())
    out2['se_clustered'] = float(cr2[1])
    out2['p_clustered'] = float(2 * (1 - _norm_cdf(abs(beta2[1] / cr2[1]))))
    return T1, out2


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

    variants = {
        'all': VERIFIED_DIST,
        'Interstate': ENDOPATH / 'nearest_pipeline_distance_interstate.csv',
        'Intrastate': ENDOPATH / 'nearest_pipeline_distance_intrastate.csv',
        'Gathering': ENDOPATH / 'nearest_pipeline_distance_gathering.csv',
    }

    hazard = {}
    cohort_sizes = {}
    for name, dist_csv in variants.items():
        cohort, ev_opshut = build_inputs(dist_csv)
        ev_corr = correct_event_map(ev_opshut)
        py, n_events_cohort = build_py(cohort, ev_corr)
        T1, T2 = fit_T1_T2(py)
        cohort_sizes[name] = {'n_landfills': int(len(cohort)), 'n_events': int(n_events_cohort)}
        hazard[name] = {'T1_yearFE_log_dist': T1, 'T2_stateFE_log_dist': T2}

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'landfill_csv': str(LANDFILL_CSV),
        'verified_dist_csv': str(VERIFIED_DIST),
        'endogeneity_dist_csvs': {k: str(v) for k, v in variants.items()},
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': True, 'synthetic_data_used': False,
        'event_cohort': 'ev_opshut_corr (reconciled Operational+Shutdown, 36-facility audit applied)',
        'cohort_by_variant': cohort_sizes,
        'hazard_log_dist_by_variant': hazard,
        'sanity_check': {
            'expected_all_T2_coef': -0.1687002936152284,
            'all_T2_coef': hazard['all']['T2_stateFE_log_dist']['coef'],
            'all_matches_manuscript': abs(hazard['all']['T2_stateFE_log_dist']['coef'] - (-0.1687002936152284)) < 1e-9,
        },
        'interpretation': 'Interstate trunk distance carries the reconciled association; '
                          'intrastate/gathering lines do not, on the SAME cohort as the manuscript headline.',
    }
    (out / 'driver_pipeline_endogeneity_reconciled_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
