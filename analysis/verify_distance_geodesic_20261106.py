"""Independent geodesic verification of the nearest-pipeline distance (Direction 1, Week 3).

Recomputes, for every coordinate-bearing landfill, the distance to the nearest
natural-gas pipeline segment using spherical great-circle point-to-arc geometry
(independent of the local-equirectangular approximation used in Week 1), and
compares the two field by field. Also re-emits a distance CSV with the lat/lon
columns in the correct order (the Week-1 CSV had them swapped; its distance
column was correct and is what the Week-2 regression used).

Read-only inputs; no model fitting; new run dir each time.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.shp'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
OLD_DIST_CSV = ROOT / 'outputs/2026-11-04_rng_pipeline_distance/run_002/nearest_pipeline_distance.csv'

R_SPHERE = 6378137.0  # Web Mercator auxiliary sphere radius (m), used only for the inverse projection
R_KM = 6371.0088      # mean Earth radius (km) for the spherical great-circle verification
DEG = np.pi / 180.0
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_AT_EQ = 111.320


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def parse_shapefile_polylines(path):
    b = Path(path).read_bytes()
    off = 100
    segs = []
    null_n = 0
    while off + 8 <= len(b):
        _, clen = (int.from_bytes(b[off:off + 4], 'big'), int.from_bytes(b[off + 4:off + 8], 'big'))
        off += 8
        content = b[off:off + 2 * clen]
        off += 2 * clen
        t = int.from_bytes(content[0:4], 'little')
        if t == 0:
            null_n += 1
            continue
        assert t == 3, t
        nparts, npoints = struct.unpack('<ii', content[36:44])
        parts = np.frombuffer(content, dtype='<i4', count=nparts, offset=44)
        pts = np.frombuffer(content, dtype='<f8', count=npoints * 2, offset=44 + 4 * nparts).reshape(-1, 2)
        idx = np.concatenate([parts, [npoints]])
        for k in range(nparts):
            sl = pts[idx[k]:idx[k + 1]]
            if len(sl) < 2:
                continue
            x, y = sl[:, 0], sl[:, 1]
            lon = x / R_SPHERE / DEG
            lat = (2.0 * np.arctan(np.exp(y / R_SPHERE)) - np.pi / 2) / DEG
            segs.append((lon[:-1], lat[:-1], lon[1:], lat[1:]))
    return segs, null_n


def _unit(lon_deg, lat_deg):
    lonr = np.radians(lon_deg); latr = np.radians(lat_deg)
    return np.stack([np.cos(latr) * np.cos(lonr), np.cos(latr) * np.sin(lonr), np.sin(latr)], axis=-1)


def point_arc_dist_spherical_km(px, py, ax, ay, bx, by):
    """Great-circle distance (km) from point P to minor arc A-B, on a sphere.

    px,py scalars (degrees); ax,ay,bx,by are arrays of segment endpoints (degrees).
    Returns a per-segment distance array. Exact for a sphere.
    """
    p = _unit(px, py)                      # (3,)
    a = _unit(ax, ay); b = _unit(bx, by)   # (m,3)
    n = np.cross(a, b)
    nn = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(nn == 0, 1.0, nn)
    pdotn = (p[None, :] * n).sum(axis=1)
    f = p[None, :] - n * pdotn[:, None]    # projection of p onto the great-circle plane
    fn = np.linalg.norm(f, axis=1, keepdims=True)
    f = f / np.where(fn == 0, 1.0, fn)
    ab = (a * b).sum(axis=1)
    af = (a * f).sum(axis=1)
    bf = (b * f).sum(axis=1)
    on_arc = (af >= ab - 1e-12) & (bf >= ab - 1e-12)
    d_foot = R_KM * np.arccos(np.clip((p[None, :] * f).sum(axis=1), -1, 1))
    d_a = R_KM * np.arccos(np.clip((p[None, :] * a).sum(axis=1), -1, 1))
    d_b = R_KM * np.arccos(np.clip((p[None, :] * b).sum(axis=1), -1, 1))
    d_end = np.minimum(d_a, d_b)
    return np.where(on_arc, d_foot, d_end)


def point_seg_dist_km_equi(px, py, ax, ay, bx, by, kx, ky):
    """Local-equirectangular point-to-segment distance (km) -- the Week-1 method."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    denom = abx * abx + aby * aby
    t = np.clip((apx * abx + apy * aby) / denom, 0.0, 1.0)
    cx, cy = ax + t * abx, ay + t * aby
    return np.hypot(px - cx, py - cy)


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

    segs, null_n = parse_shapefile_polylines(SHP)
    lon1 = np.concatenate([s[0] for s in segs]); lat1 = np.concatenate([s[1] for s in segs])
    lon2 = np.concatenate([s[2] for s in segs]); lat2 = np.concatenate([s[3] for s in segs])
    n_seg = len(lon1)
    seg_lon_min = np.minimum(lon1, lon2); seg_lon_max = np.maximum(lon1, lon2)
    seg_lat_min = np.minimum(lat1, lat2); seg_lat_max = np.maximum(lat1, lat2)

    lf = pd.read_csv(LANDFILL_CSV)
    have = lf['has_coord'] == True  # noqa: E712
    sub = lf.loc[have, ['Landfill ID', 'state', 'lat', 'lon']].copy()
    rows = []
    for _, r in sub.iterrows():
        lon_p, lat_p = float(r['lon']), float(r['lat'])   # correct: lon<-'lon', lat<-'lat'
        best_e = None; best_s = None
        for W in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0):
            dlon = W / max(np.cos(lat_p * DEG), 0.2)
            m = ((seg_lon_min <= lon_p + dlon) & (seg_lon_max >= lon_p - dlon) &
                 (seg_lat_min <= lat_p + W) & (seg_lat_max >= lat_p - W))
            if not m.any():
                continue
            ax = lon1[m]; ay = lat1[m]; bx = lon2[m]; by = lat2[m]
            # equirectangular (Week-1 method)
            kx = KM_PER_DEG_LON_AT_EQ * np.cos(lat_p * DEG); ky = KM_PER_DEG_LAT
            de = point_seg_dist_km_equi(0.0, 0.0, (ax - lon_p) * kx, (ay - lat_p) * ky,
                                        (bx - lon_p) * kx, (by - lat_p) * ky, kx, ky)
            # spherical great-circle (independent)
            ds = point_arc_dist_spherical_km(lon_p, lat_p, ax, ay, bx, by)
            best_e = float(de.min()); best_s = float(ds.min())
            break
        rows.append({'Landfill ID': int(r['Landfill ID']), 'state': r['state'],
                     'lat': lat_p, 'lon': lon_p,
                     'nearest_pipeline_km_spherical': best_s,
                     'nearest_pipeline_km_equirect': best_e,
                     'pipeline_covered': best_s is not None})

    d = pd.DataFrame(rows)
    cov = d[d['pipeline_covered']].copy()
    cov['diff_km'] = cov['nearest_pipeline_km_equirect'] - cov['nearest_pipeline_km_spherical']
    cov['abs_diff_km'] = cov['diff_km'].abs()
    cov['rel_diff_pct'] = 100 * cov['diff_km'] / cov['nearest_pipeline_km_spherical']

    # compare against the Week-1 CSV (distance column only)
    old = pd.read_csv(OLD_DIST_CSV)[['Landfill ID', 'nearest_pipeline_km']].rename(
        columns={'nearest_pipeline_km': 'old_equirect'})
    cmp = cov.merge(old, on='Landfill ID', how='left')
    cmp['old_vs_this_equi_diff'] = (cmp['old_equirect'] - cmp['nearest_pipeline_km_equirect']).abs()

    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'pipeline_shapefile': str(SHP), 'pipeline_shapefile_sha256': sha(SHP),
        'landfill_csv': str(LANDFILL_CSV), 'landfill_csv_sha256': sha(LANDFILL_CSV),
        'old_distance_csv': str(OLD_DIST_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': False, 'synthetic_data_used': False,
        'method_note': 'spherical great-circle point-to-minor-arc (R=6371.0088km) vs Week-1 local-equirectangular (scaled by cos(lat)); both over the same candidate segments found by the same growing-bbox search.',
        'segments': n_seg, 'null_geometries': null_n,
        'landfills_covered': int(cov.shape[0]), 'landfills_no_pipeline': int((~d['pipeline_covered']).sum()),
        'equirect_vs_spherical_km': {
            'mean_abs_diff': round(float(cov['abs_diff_km'].mean()), 5),
            'median_abs_diff': round(float(cov['abs_diff_km'].median()), 5),
            'p90_abs_diff': round(float(cov['abs_diff_km'].quantile(.90)), 5),
            'p99_abs_diff': round(float(cov['abs_diff_km'].quantile(.99)), 5),
            'max_abs_diff': round(float(cov['abs_diff_km'].max()), 5),
            'n_diff_gt_0p1km': int((cov['abs_diff_km'] > 0.1).sum()),
            'n_diff_gt_0p5km': int((cov['abs_diff_km'] > 0.5).sum()),
            'n_diff_gt_1km': int((cov['abs_diff_km'] > 1.0).sum()),
        },
        'rel_diff_pct': {
            'median_abs': round(float(cov['rel_diff_pct'].abs().median()), 4),
            'p99_abs': round(float(cov['rel_diff_pct'].abs().quantile(.99)), 4),
            'n_rel_gt_1pct': int((cov['rel_diff_pct'].abs() > 1.0).sum()),
        },
        'reproducibility_vs_week1_equirect': {
            'max_abs_diff': round(float(cmp['old_vs_this_equi_diff'].max()), 5),
            'n_diff_gt_1m': int((cmp['old_vs_this_equi_diff'] > 0.001).sum()),
        },
        'spherical_distance_km': {
            'median': round(float(cov['nearest_pipeline_km_spherical'].median()), 3),
            'p90': round(float(cov['nearest_pipeline_km_spherical'].quantile(.90)), 3),
        },
    }

    d.to_csv(out / 'nearest_pipeline_distance_verified.csv', index=False, encoding='utf-8-sig')
    (out / 'geodesic_verify_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
