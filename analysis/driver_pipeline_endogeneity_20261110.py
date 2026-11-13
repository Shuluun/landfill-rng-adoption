"""Phase 3 driver endogeneity robustness: interstate-trunk vs local-line distance.

The driver line is pipeline distance -> PI-RNG adoption (discrete-time hazard).
Endogeneity concern: pipeline siting is not exogenous to landfill/RNG siting
(local development common cause). The HIFLD shapefile has no vintage/install year
(only TYPEPIPE/Operator/Status/Shape_Leng), so a "pre-existing pipeline" check is
infeasible. Verified this session: Status == "Operating" for all 32961 features,
so there is no Proposed/Abandoned subset to drop either.

The one defensible cheap split available is TYPEPIPE:
  - Interstate (17996): FERC long-haul trunk lines, sited for national transmission,
    far less plausibly endogenous to a specific landfill.
  - Intrastate + Gathering (14965): local lines, the endogeneity-prone subset.
Recompute nearest-pipeline distance using interstate-only and local-only segments,
verify the all-pipeline union reproduces the already-verified Week-3 distances, and
re-run the T1/T2 hazard for each distance variant. The robustness claim holds if the
log_dist coefficient keeps its sign/significance on the interstate-trunk distance.

Read-only inputs; deterministic; new run dir.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DBF = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.dbf'
SHP = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.shp'
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
VERIFIED_DIST = ROOT / 'outputs/2026-11-06_rng_distance_geodesic_verify/run_001/nearest_pipeline_distance_verified.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
CONTINENTAL = {
    'AL','AZ','AR','CA','CO','CT','DE','FL','GA','ID','IL','IN','IA','KS','KY','LA',
    'ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND',
    'OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC',
}
ERA_START = 1995
CENSOR_YEAR = 2024
R_SPHERE = 6378137.0
R_KM = 6371.0088
DEG = np.pi / 180.0


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------- geometry / attribute parsing ----------

def read_dbf_types(path):
    b = Path(path).read_bytes()
    nrec = int.from_bytes(b[4:8], 'little')
    hsize = int.from_bytes(b[8:10], 'little')
    rsize = int.from_bytes(b[10:12], 'little')
    fields = []
    off = 32
    while b[off] != 0x0D:
        name = b[off:off + 11].split(b'\x00')[0].decode('ascii', 'replace')
        ftype = chr(b[off + 11]); flen = b[off + 16]
        fields.append((name, ftype, flen)); off += 32
    name_of = {n: i for i, (n, _, _) in enumerate(fields)}
    pos_of = {n: 0 for n in name_of}
    p = 1
    for n, _, flen in fields:
        pos_of[n] = p; p += flen
    typ_i = name_of['TYPEPIPE']; st_i = name_of['Status']
    types = []; statuses = []
    for i in range(nrec):
        rec = b[hsize + i * rsize: hsize + (i + 1) * rsize]
        if rec[0] == 0x2A:  # 0x2A='*' deleted; 0x20=' ' is an ACTIVE record, keep it
            types.append(''); statuses.append(''); continue
        tp = rec[pos_of['TYPEPIPE']:pos_of['TYPEPIPE'] + fields[typ_i][2]].decode('latin-1').strip()
        st = rec[pos_of['Status']:pos_of['Status'] + fields[st_i][2]].decode('latin-1').strip()
        types.append(tp); statuses.append(st)
    return types, statuses, nrec


def parse_shp_with_index(path):
    b = Path(path).read_bytes()
    off = 100
    recs = []
    null_n = 0
    while off + 8 <= len(b):
        _, clen = (int.from_bytes(b[off:off + 4], 'big'), int.from_bytes(b[off + 4:off + 8], 'big'))
        off += 8
        content = b[off:off + 2 * clen]
        off += 2 * clen
        t = int.from_bytes(content[0:4], 'little')
        if t == 0:
            recs.append(None); null_n += 1; continue
        assert t == 3, t
        nparts, npoints = struct.unpack('<ii', content[36:44])
        parts = np.frombuffer(content, dtype='<i4', count=nparts, offset=44)
        pts = np.frombuffer(content, dtype='<f8', count=npoints * 2, offset=44 + 4 * nparts).reshape(-1, 2)
        idx = np.concatenate([parts, [npoints]])
        l1, la1, l2, la2 = [], [], [], []
        for k in range(nparts):
            sl = pts[idx[k]:idx[k + 1]]
            if len(sl) < 2:
                continue
            x, y = sl[:, 0], sl[:, 1]
            lon = x / R_SPHERE / DEG
            lat = (2.0 * np.arctan(np.exp(y / R_SPHERE)) - np.pi / 2) / DEG
            l1.append(lon[:-1]); la1.append(lat[:-1]); l2.append(lon[1:]); la2.append(lat[1:])
        if l1:
            recs.append((np.concatenate(l1), np.concatenate(la1), np.concatenate(l2), np.concatenate(la2)))
        else:
            recs.append(None)
    return recs, null_n


def build_variant(recs, types, key):
    if key == 'all':
        keep = [i for i, r in enumerate(recs) if r is not None]
    else:
        keep = [i for i, r in enumerate(recs) if r is not None and types[i] == key]
    l1 = np.concatenate([recs[i][0] for i in keep])
    la1 = np.concatenate([recs[i][1] for i in keep])
    l2 = np.concatenate([recs[i][2] for i in keep])
    la2 = np.concatenate([recs[i][3] for i in keep])
    return {'lon1': l1, 'lat1': la1, 'lon2': l2, 'lat2': la2,
            'lon_min': np.minimum(l1, l2), 'lon_max': np.maximum(l1, l2),
            'lat_min': np.minimum(la1, la2), 'lat_max': np.maximum(la1, la2),
            'n_records': len(keep), 'n_segments': len(l1)}


def _unit(lon_deg, lat_deg):
    lonr = np.radians(lon_deg); latr = np.radians(lat_deg)
    return np.stack([np.cos(latr) * np.cos(lonr), np.cos(latr) * np.sin(lonr), np.sin(latr)], axis=-1)


def point_arc_dist_spherical_km(px, py, ax, ay, bx, by):
    p = _unit(px, py)
    a = _unit(ax, ay); b = _unit(bx, by)
    n = np.cross(a, b); nn = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(nn == 0, 1.0, nn)
    pdotn = (p[None, :] * n).sum(axis=1)
    f = p[None, :] - n * pdotn[:, None]
    fn = np.linalg.norm(f, axis=1, keepdims=True); f = f / np.where(fn == 0, 1.0, fn)
    ab = (a * b).sum(axis=1); af = (a * f).sum(axis=1); bf = (b * f).sum(axis=1)
    on_arc = (af >= ab - 1e-12) & (bf >= ab - 1e-12)
    d_foot = R_KM * np.arccos(np.clip((p[None, :] * f).sum(axis=1), -1, 1))
    d_a = R_KM * np.arccos(np.clip((p[None, :] * a).sum(axis=1), -1, 1))
    d_b = R_KM * np.arccos(np.clip((p[None, :] * b).sum(axis=1), -1, 1))
    return np.where(on_arc, d_foot, np.minimum(d_a, d_b))


def compute_distances(lf, variants):
    sub = lf[lf['has_coord'] == True].copy()  # noqa: E712
    out = {}
    for name, v in variants.items():
        rows = []
        for _, r in sub.iterrows():
            lon_p, lat_p = float(r['lon']), float(r['lat'])
            best = None
            for W in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0):
                dlon = W / max(np.cos(lat_p * DEG), 0.2)
                m = ((v['lon_min'] <= lon_p + dlon) & (v['lon_max'] >= lon_p - dlon) &
                     (v['lat_min'] <= lat_p + W) & (v['lat_max'] >= lat_p - W))
                if not m.any():
                    continue
                ds = point_arc_dist_spherical_km(lon_p, lat_p, v['lon1'][m], v['lat1'][m], v['lon2'][m], v['lat2'][m])
                best = float(ds.min()); break
            rows.append({'Landfill ID': int(r['Landfill ID']), 'state': r['state'],
                         'nearest_pipeline_km_spherical': best, 'pipeline_covered': best is not None})
        out[name] = pd.DataFrame(rows)
    return out


# ---------- hazard model ----------

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


def run_hazard(lf, dist_df, event_year, bad_date_only):
    m = lf.merge(dist_df[['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']],
                 on='Landfill ID', how='left')
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
    cohort['has_event'] = cohort['event_year'].notna() & (cohort['entry'] <= cohort['exit'])

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
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]

    def fit(cols, cluster_key=None, dfx=None, yy=None):
        dfx = py if dfx is None else dfx; yy = y if yy is None else yy
        X = np.column_stack([np.ones(len(dfx))] + [dfx[c].to_numpy(float) for c in cols])
        beta, se = irls_logit(X, yy)
        out = {'coef': float(beta[1]), 'se': float(se[1]),
               'p': float(2 * (1 - _norm_cdf(abs(beta[1] / se[1]))))}
        cr = cluster_robust(X, yy, beta, dfx[cluster_key].to_numpy())
        out['se_clustered'] = float(cr[1])
        out['p_clustered'] = float(2 * (1 - _norm_cdf(abs(beta[1] / cr[1]))))
        return out

    T1 = fit(['log_dist', 'log_waste'] + year_dummies, cluster_key='Landfill ID')
    per_state = py.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    py2 = py[~py['state'].isin(drop)].copy()
    states2 = sorted(py2['state'].unique()); ref = states2[0]
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states2 if s != ref]
    T2 = fit(['log_dist', 'log_waste'] + year_dummies + state_cols, cluster_key='Landfill ID', dfx=py2, yy=py2['y'].to_numpy())
    return {'T1': T1, 'T2': T2,
            'n_landfills': int(len(cohort)), 'n_events': int(cohort['has_event'].sum()),
            'n_person_years': int(len(py)), 'dropped_states': drop}


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

    types, statuses, nrec_dbf = read_dbf_types(DBF)
    recs, null_n = parse_shp_with_index(SHP)
    assert len(types) == len(recs) == nrec_dbf == 32961, (len(types), len(recs), nrec_dbf)
    status_set = sorted(set(s for s in statuses if s))

    variants = {k: build_variant(recs, types, k) for k in ['all', 'Interstate', 'Intrastate', 'Gathering']}

    lf = pd.read_csv(LANDFILL_CSV)
    dists = compute_distances(lf, variants)
    for name, df in dists.items():
        df.to_csv(out / f'nearest_pipeline_distance_{name.lower()}.csv', index=False, encoding='utf-8-sig')

    # validation: recomputed 'all' vs the already-verified Week-3 CSV
    verified = pd.read_csv(VERIFIED_DIST)[['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']]
    recomp = dists['all'][['Landfill ID', 'nearest_pipeline_km_spherical', 'pipeline_covered']].rename(
        columns={'nearest_pipeline_km_spherical': 'recomputed', 'pipeline_covered': 'covered_recomputed'})
    chk = verified.merge(recomp, on='Landfill ID', how='left')
    chk = chk[chk['pipeline_covered'] == True]
    chk['diff_km'] = (chk['recomputed'] - chk['nearest_pipeline_km_spherical']).abs()
    validation = {'n_covered_compared': int(len(chk)),
                  'max_abs_diff_km': float(chk['diff_km'].max()),
                  'n_diff_gt_1m': int((chk['diff_km'] > 0.001).sum()),
                  'reproduced': bool(chk['diff_km'].max() < 0.001)}

    # hazard on each variant
    df_lmop = pd.read_excel(LMOP, sheet_name='LMOP Database')
    is_rng = df_lmop['Project Type Category'].eq(RNG_CATEGORY) | df_lmop['RNG Delivery Method'].isin(RNG_METHODS)
    pi = df_lmop['RNG Delivery Method'].eq('Pipeline Injection')
    rng_pi = df_lmop[is_rng & pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= ERA_START) & (rng_pi['sy'] <= CENSOR_YEAR)]
    event_year = valid.groupby('Landfill ID')['sy'].min()
    all_pi = rng_pi.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: sorted(set(s)))
    bad_date_only = set(all_pi[all_pi.apply(lambda yrs: all(y < ERA_START for y in yrs))].index.tolist())

    hazard = {}
    for name, df in [('all', verified), ('Interstate', dists['Interstate']),
                     ('Intrastate', dists['Intrastate']), ('Gathering', dists['Gathering'])]:
        hazard[name] = run_hazard(lf, df, event_year, bad_date_only)

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'landfill_csv': str(LANDFILL_CSV),
        'verified_dist_csv': str(VERIFIED_DIST),
        'dbf_sha256': sha(DBF), 'shp_sha256': sha(SHP),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': True, 'synthetic_data_used': False,
        'n_records': nrec_dbf, 'null_geometries': null_n,
        'status_unique_values': status_set,
        'typetype_counts': {k: variants[k]['n_records'] for k in ['Interstate', 'Intrastate', 'Gathering']},
        'validation_recomputed_all_vs_verified': validation,
        'hazard_log_dist_by_variant': hazard,
        'interpretation': 'Interstate trunk distance is the more plausibly exogenous exposure; '
                          'if the log_dist coefficient keeps sign/significance on interstate-only distance, '
                          'the association is not an artifact of endogenous local (intrastate/gathering) lines.',
    }
    (out / 'driver_pipeline_endogeneity_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
