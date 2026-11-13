"""Driver-side technical completion: 4 sensitivity/robustness checks.

Reuses the Week-3 discrete-time hazard cohort (survival_hazard_rng_20261106.py)
and runs the four remaining technical checks from the 2026-11-06 finish queue:

  1. EVENT_DEF_SENSITIVITY  — event = any-status vs Operational-only vs
                              Operational+Shutdown.
  2. COMPETING_RISK         — local-use RNG treated as a competing event
                              (censored at local-use adoption) vs excluded.
  3. PROJECTID_LEAKAGE      — shared-ProjectID temporal structure + SE clustered
                              by ProjectID (multi-site projects share a cluster).
  4. MARKET_PROXY_COLLINEARITY — state-constant policy covariate is perfectly
                              collinear with state FE (identification demo);
                              time-varying market proxy absent -> limitation.

Read-only inputs; no randomness; no causal claim; new run dir.
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


def build_inputs():
    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    local = df['RNG Delivery Method'].eq('Local Use')

    rng_pi = df[is_rng & pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    rng_pi['status'] = rng_pi['Current Project Status'].astype(str).str.strip()

    # status-filtered event-year functions
    def ev_year(statuses):
        sub = rng_pi[rng_pi['status'].isin(statuses)]
        sub = sub[(sub['sy'] >= ERA_START) & (sub['sy'] <= CENSOR_YEAR)]
        return sub.groupby('Landfill ID')['sy'].min()

    ev_all = ev_year({'Operational', 'Shutdown', 'Planned', 'Construction'})
    ev_op = ev_year({'Operational'})
    ev_opshut = ev_year({'Operational', 'Shutdown'})

    # local-use adoption year (competing event)
    rng_local = df[is_rng & local].copy()
    rng_local['sy'] = pd.to_datetime(rng_local['Project Start Date'], errors='coerce').dt.year
    local_ev = rng_local[(rng_local['sy'] >= ERA_START) & (rng_local['sy'] <= CENSOR_YEAR)].groupby('Landfill ID')['sy'].min()

    # bad-date-only landfills (all PI start years < 1995)
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
    cohort['local_ev'] = cohort['Landfill ID'].map(local_ev)

    # shared ProjectID: map Landfill ID -> Project IDs, find shared
    df['pid'] = df['Project ID'].astype(str).str.strip()
    lf_pid = df[df['pid'].notna() & (df['pid'] != '') & (df['pid'] != 'nan')].groupby('Landfill ID')['pid'].agg(
        lambda s: sorted(set(s)))
    pid_lf = {}
    for lid, pids in lf_pid.items():
        for p in pids:
            pid_lf.setdefault(p, set()).add(int(lid))
    shared_pids = {p: sorted(fs) for p, fs in pid_lf.items() if len(fs) > 1}
    # map landfill -> shared project group id (a landfill is in at most one shared group for clustering demo)
    lf_pidgroup = {}
    for gi, (p, fs) in enumerate(shared_pids.items()):
        for f in fs:
            lf_pidgroup[f] = f'pid_{gi}'

    return df, cohort, dict(ev_all=ev_all, ev_op=ev_op, ev_opshut=ev_opshut), local_ev, shared_pids, lf_pidgroup


def build_py(cohort, event_map, def_name, competing=False):
    c = cohort.copy()
    ev = event_map[def_name]
    c['event_year'] = c['Landfill ID'].map(ev)
    c['exit'] = c['event_year'].fillna(CENSOR_YEAR).astype(int)
    # competing: local-use adoption censors PI risk at local_ev (if < exit and no PI event before)
    if competing:
        le = c['local_ev']
        # only compete if local use happens before the PI event/exit
        mask = le.notna() & (le < c['exit']) & ~(c['event_year'].notna() & (le >= c['event_year']))
        c.loc[mask, 'exit'] = le.loc[mask].astype(int)
        c.loc[mask, 'event_year'] = np.nan  # local-use adoption is a competing (not PI) event
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
    return py


def fit_T1_T2(py, extra_cols=None):
    y = py['y'].to_numpy()
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]
    cols = ['log_dist', 'log_waste'] + year_dummies + (extra_cols or [])

    def run(dfx, yy, cluster_key):
        X = np.column_stack([np.ones(len(dfx))] + [dfx[c].to_numpy(float) for c in cols])
        beta, se = irls_logit(X, yy)
        names = ['const'] + cols
        out = {'coef': float(beta[1]), 'se': float(se[1]), 'p': float(2 * (1 - _norm_cdf(abs(beta[1] / se[1])))),
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
    cols2 = ['log_dist', 'log_waste'] + year_dummies + state_cols + (extra_cols or [])
    y2 = py2['y'].to_numpy()
    X2 = np.column_stack([np.ones(len(py2))] + [py2[c].to_numpy(float) for c in cols2])
    beta2, se2 = irls_logit(X2, y2)
    out2 = {'coef': float(beta2[1]), 'se': float(se2[1]), 'p': float(2 * (1 - _norm_cdf(abs(beta2[1] / se2[1])))),
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

    df, cohort, event_map, local_ev, shared_pids, lf_pidgroup = build_inputs()

    results = {}

    # ---- Check 1: event definition sensitivity ----
    ed = {}
    for defn in ['ev_all', 'ev_op', 'ev_opshut']:
        py = build_py(cohort, event_map, defn)
        T1, T2 = fit_T1_T2(py)
        ed[defn] = {'T1_yearFE_log_dist': T1, 'T2_stateFE_log_dist': T2,
                    'n_events': T1['n_events'], 'n_person_years': T1['n_py']}
    results['event_def_sensitivity'] = ed

    # ---- Check 2: competing risk (local use) ----
    cr = {}
    py_base = build_py(cohort, event_map, 'ev_all')
    T1b, T2b = fit_T1_T2(py_base)
    cr['baseline_all'] = {'T1': T1b, 'T2': T2b}
    py_comp = build_py(cohort, event_map, 'ev_all', competing=True)
    T1c, T2c = fit_T1_T2(py_comp)
    cr['competing_local_use'] = {'T1': T1c, 'T2': T2c, 'n_local_use_facilities': int(local_ev.notna().sum())}
    results['competing_risk'] = cr

    # ---- Check 3: ProjectID leakage ----
    pk = {'n_shared_projectids': len(shared_pids)}
    shared_list = []
    for p, fs in shared_pids.items():
        yrs = {}
        for f in fs:
            yrs[f] = None
        shared_list.append({'project_id': p, 'landfills': fs})
    pk['shared_groups'] = shared_list
    # cluster SE by ProjectID (shared groups = one cluster, others = own landfill)
    py = build_py(cohort, event_map, 'ev_all')
    py['cluster'] = py['Landfill ID'].map(lambda f: lf_pidgroup.get(f, f'lf_{f}'))
    y = py['y'].to_numpy()
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]
    cols = ['log_dist', 'log_waste'] + year_dummies
    X = np.column_stack([np.ones(len(py))] + [py[c].to_numpy(float) for c in cols])
    beta, se = irls_logit(X, y)
    cr_pid = cluster_robust(X, y, beta, py['cluster'].to_numpy())
    cr_lf = cluster_robust(X, y, beta, py['Landfill ID'].to_numpy())
    pk['T1_log_dist'] = {'coef': float(beta[1]),
                         'se_clustered_landfill': float(cr_lf[1]),
                         'se_clustered_projectid': float(cr_pid[1])}
    results['projectid_leakage'] = pk

    # ---- Check 4: market proxy / state FE collinearity ----
    # (a) a state-CONSTANT covariate is a linear combination of state FE -> rank check.
    py2 = py[~py['state'].isin(['AZ','CO','CT','DE','MA','MD','ND','NM','NV','RI','SD','VT','WY'])].copy()
    states2 = sorted(py2['state'].unique()); ref = states2[0]
    stcols = []
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int); stcols.append(f'st_{s}')
    # state-constant policy proxy: state mean log_waste (constant within state)
    py2['state_policy_proxy'] = py2.groupby('state')['log_waste'].transform('mean')
    D_base = np.column_stack([np.ones(len(py2))] + [py2[c].to_numpy(float) for c in stcols])
    D_with = np.column_stack([D_base, py2['state_policy_proxy'].to_numpy(float)])
    rank_base = int(np.linalg.matrix_rank(D_base))
    rank_with = int(np.linalg.matrix_rank(D_with))
    collinear = rank_with == rank_base  # adding state-constant proxy does not raise rank -> collinear with state FE
    # (b) a TIME-VARYING within-state proxy is not collinear (rank rises).
    py2['time_varying_proxy'] = py2['year'] * py2['log_waste']
    D_tv = np.column_stack([D_base, py2['time_varying_proxy'].to_numpy(float)])
    rank_tv = int(np.linalg.matrix_rank(D_tv))
    results['market_proxy_collinearity'] = {
        'state_constant_proxy': {'rank_stateFE': rank_base, 'rank_plus_proxy': rank_with,
                                 'collinear_with_stateFE': collinear},
        'time_varying_proxy': {'rank_plus_proxy': rank_tv,
                               'identified': rank_tv > rank_base},
        'note': 'state-level policy (LCFS/RPS) is constant within state -> absorbed by state FE; '
                'a within-state time-varying market proxy (county population density/urbanity) is needed '
                'and is NOT present in the registry inputs -> limitation.',
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
        'results': results,
    }
    (out / 'driver_finish_sensitivity_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
