"""Compute nearest natural-gas-pipeline distance for each LMOP landfill (Direction 1, Week 1).

Reads the public HIFLD natural-gas pipeline shapefile (Web Mercator, EPSG:3857)
and the per-landfill coordinate table produced by denominator_gate_rng_20261104.py.
Inverse-projects pipeline vertices to lon/lat, then computes, per landfill, the
distance to the nearest pipeline line segment using a locally-scaled
equirectangular frame (accurate near the landfill, which is what the minimum
requires). Landfills outside the pipeline coverage (Hawaii, Alaska west, PR and
other territories) are flagged rather than silently assigned a distance.

Read-only inputs; no model fitting; new run dir each time.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, struct, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / 'inputs/public/hifld_natural_gas_pipelines_20261104/shapefile_extracted/natural-gas-interstate-and-intrastate-pipelines.shp'
LANDFILL_CSV = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'

R_SPHERE = 6378137.0  # Web Mercator auxiliary sphere radius (m)
DEG = np.pi / 180.0
KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON_AT_EQ = 111.320


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def parse_shapefile_polylines(path):
    b = Path(path).read_bytes()
    off = 100
    segs = []  # list of (lon1, lat1, lon2, lat2)
    null_n = 0
    while off + 8 <= len(b):
        _, clen = struct_unpack_header(b, off)
        off += 8
        content = b[off:off + 2 * clen]
        off += 2 * clen
        t = struct_unpack_i(content, 0)
        if t == 0:
            null_n += 1
            continue
        assert t == 3, t
        nparts, npoints = struct.unpack('<ii', content[36:44])
        # parts indices then points
        parts = np.frombuffer(content, dtype='<i4', count=nparts, offset=44)
        pts = np.frombuffer(content, dtype='<f8', count=npoints * 2, offset=44 + 4 * nparts).reshape(-1, 2)
        # break into part sub-sequences
        idx = np.concatenate([parts, [npoints]])
        for k in range(nparts):
            sl = pts[idx[k]:idx[k + 1]]
            if len(sl) < 2:
                continue
            x, y = sl[:, 0], sl[:, 1]
            # inverse Web Mercator -> lon/lat degrees
            lon = x / R_SPHERE / DEG
            lat = (2.0 * np.arctan(np.exp(y / R_SPHERE)) - np.pi / 2) / DEG
            segs.append((lon[:-1], lat[:-1], lon[1:], lat[1:]))
    return segs, null_n


def struct_unpack_header(b, off):
    return (int.from_bytes(b[off:off + 4], 'big'), int.from_bytes(b[off + 4:off + 8], 'big'))


def struct_unpack_i(content, o):
    return int.from_bytes(content[o:o + 4], 'little')


def point_seg_dist_km(px, py, ax, ay, bx, by):
    """Planar point-to-segment distance in a locally-scaled frame (inputs in km)."""
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
    # concatenate all segments into arrays
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
        lon_p, lat_p = float(r['lon']), float(r['lat'])
        best = None
        # grow a search window until a segment bbox overlaps
        for W in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0):
            dlon = W / max(np.cos(lat_p * DEG), 0.2)
            m = ((seg_lon_min <= lon_p + dlon) & (seg_lon_max >= lon_p - dlon) &
                 (seg_lat_min <= lat_p + W) & (seg_lat_max >= lat_p - W))
            if not m.any():
                continue
            # local planar frame centered on the landfill (km)
            kx = KM_PER_DEG_LON_AT_EQ * np.cos(lat_p * DEG)
            ky = KM_PER_DEG_LAT
            px, py = 0.0, 0.0
            ax = (lon1[m] - lon_p) * kx; ay = (lat1[m] - lat_p) * ky
            bx = (lon2[m] - lon_p) * kx; by = (lat2[m] - lat_p) * ky
            d = point_seg_dist_km(px, py, ax, ay, bx, by)
            best = float(d.min())
            break
        rows.append({'Landfill ID': int(r['Landfill ID']), 'state': r['state'],
                     'lat': lon_p, 'lon': lat_p,
                     'nearest_pipeline_km': best, 'pipeline_covered': best is not None})

    dist = pd.DataFrame(rows)
    covered = dist[dist['pipeline_covered']]
    no_cov = dist[~dist['pipeline_covered']]
    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'pipeline_shapefile': str(SHP), 'pipeline_shapefile_sha256': sha(SHP),
        'landfill_csv': str(LANDFILL_CSV), 'landfill_csv_sha256': sha(LANDFILL_CSV),
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': False, 'synthetic_data_used': False,
        'crs_note': 'Pipeline shapefile is Web Mercator (EPSG:3857); vertices inverse-projected to WGS84 lon/lat; distances are local-equirectangular km.',
        'segments': n_seg, 'null_geometries': null_n,
        'landfills_with_coords': int(have.sum()),
        'landfills_covered': len(covered), 'landfills_no_pipeline_in_dataset': len(no_cov),
        'no_pipeline_states': sorted(no_cov['state'].dropna().unique().tolist()),
        'distance_km': {
            'median': None if covered.empty else round(float(covered['nearest_pipeline_km'].median()), 3),
            'mean': None if covered.empty else round(float(covered['nearest_pipeline_km'].mean()), 3),
            'p10': None if covered.empty else round(float(covered['nearest_pipeline_km'].quantile(.10)), 3),
            'p25': None if covered.empty else round(float(covered['nearest_pipeline_km'].quantile(.25)), 3),
            'p75': None if covered.empty else round(float(covered['nearest_pipeline_km'].quantile(.75)), 3),
            'p90': None if covered.empty else round(float(covered['nearest_pipeline_km'].quantile(.90)), 3),
        },
        'within_km': {k: None if covered.empty else int((covered['nearest_pipeline_km'] <= k).sum())
                      for k in (1, 5, 10, 25, 50)},
    }
    dist.to_csv(out / 'nearest_pipeline_distance.csv', index=False, encoding='utf-8-sig')
    (out / 'distance_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
