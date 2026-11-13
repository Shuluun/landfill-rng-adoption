"""Audit published-in-workspace exploratory counts, without fitting a model.

New outputs only. CONUS is a descriptive sensitivity population, not a silent
replacement for the original registry or fixed eight. Distances remain a local
equirectangular approximation to the supplied major-pipeline geometry.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, importlib.metadata, io, json, platform, shutil, sys, time, zipfile
import numpy as np
import pandas as pd
from compute_pipeline_distance_20261104 import parse_shapefile_polylines, point_seg_dist_km, SHP

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
LEGACY = ROOT / 'outputs/2026-11-04_rng_denominator_gate/run_001/landfill_level.csv'
DIST = ROOT / 'outputs/2026-11-04_rng_pipeline_distance/run_002/nearest_pipeline_distance.csv'
HIST = ROOT / 'inputs/public/topic_selection_2026-10-20/root_sources/national_lmopdata_files_2001-2023.zip'
NON_CONUS = {'AK', 'HI', 'PR', 'VI', 'GU', 'AS', 'MP'}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def labels(frame):
    pipe = frame['Project Type Category'].eq('Renewable Natural Gas') & frame['RNG Delivery Method'].eq('Pipeline Injection')
    result = pd.DataFrame(index=pd.Index(sorted(frame['Landfill ID'].unique()), name='Landfill ID'))
    for key, statuses in {
        'pipe_operational': ['Operational'],
        'pipe_operational_or_shutdown': ['Operational', 'Shutdown'],
        'pipe_operational_construction_planned': ['Operational', 'Construction', 'Planned'],
    }.items():
        ids = frame.loc[pipe & frame['Current Project Status'].isin(statuses), 'Landfill ID']
        result[key] = result.index.isin(ids)
    result['any_rng_record'] = result.index.isin(frame.loc[frame['Project Type Category'].eq('Renewable Natural Gas'), 'Landfill ID'])
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    args = ap.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()
    out = (ROOT / args.run_dir).resolve()
    assert out.is_relative_to(ROOT / 'outputs')
    out.mkdir(parents=True, exist_ok=False)
    inputs = [RAW, LEGACY, DIST, HIST, SHP,
              ROOT / 'scripts/compute_pipeline_distance_20261104.py']
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    frame = pd.read_excel(RAW, sheet_name='LMOP Database')
    frame['excel_row'] = np.arange(len(frame)) + 2
    base = frame.groupby('Landfill ID', sort=True).first()[[
        'Landfill Name', 'State', 'Latitude', 'Longitude', 'Waste in Place (tons)',
        'Waste in Place Year', 'Year Landfill Opened', 'Ownership Type']]
    tab = base.join(labels(frame))
    legacy = pd.read_csv(LEGACY).set_index('Landfill ID')
    dist = pd.read_csv(DIST).set_index('Landfill ID')
    tab['legacy_analyzable'] = legacy['analyzable']
    tab['legacy_broad_pipe_flag'] = legacy['rng_adopted'] & legacy['rng_delivery'].fillna('').str.contains('Pipeline Injection', regex=False)
    tab['legacy_non_rng_development_flag'] = ~legacy['rng_adopted']
    tab['legacy_distance_km'] = dist['nearest_pipeline_km']
    tab['has_coordinate'] = tab[['Latitude', 'Longitude']].notna().all(axis=1)
    tab['conus_descriptive_sensitivity'] = ~tab['State'].isin(NON_CONUS)
    coord = tab.join(dist[['lat', 'lon']])
    swapped = coord['lat'].eq(coord['Longitude']) & coord['lon'].eq(coord['Latitude']) & coord['has_coordinate']

    # Full search of every segment removes the legacy first-nonempty-box stopping
    # ambiguity. This is exact only within the stated local planar metric.
    segs, nulls = parse_shapefile_polylines(SHP)
    lon1, lat1, lon2, lat2 = [np.concatenate([s[j] for s in segs]) for j in range(4)]
    nondegenerate = (lon1 != lon2) | (lat1 != lat2)
    lon1, lat1, lon2, lat2 = [a[nondegenerate] for a in [lon1, lat1, lon2, lat2]]
    selected = tab[tab['has_coordinate'] & tab['conus_descriptive_sensitivity']]
    qa = []
    tab['audited_local_distance_km'] = np.nan
    for cid, row in selected.iterrows():
        lon, lat = row['Longitude'], row['Latitude']
        kx = 111.320 * np.cos(np.deg2rad(lat))
        d = point_seg_dist_km(0., 0., (lon1-lon)*kx, (lat1-lat)*110.574,
                              (lon2-lon)*kx, (lat2-lat)*110.574)
        value = float(d.min())
        old = row['legacy_distance_km']
        tab.loc[cid, 'audited_local_distance_km'] = value
        qa.append({'Landfill ID': cid, 'old_km': old, 'full_search_km': value,
                   'old_minus_full_km': None if pd.isna(old) else float(old-value)})
    q = pd.DataFrame(qa)
    q.to_csv(out/'DISTANCE_SEARCH_QA.csv', index=False, encoding='utf-8-sig')
    mainpop = tab[tab['audited_local_distance_km'].notna()]
    summaries = []
    for endpoint in ['legacy_broad_pipe_flag', 'pipe_operational', 'pipe_operational_or_shutdown', 'pipe_operational_construction_planned']:
        for population, sub, field in [
            ('legacy_all_finite_distance', tab[tab['legacy_distance_km'].notna()], 'legacy_distance_km'),
            ('conus_full_search_local_metric', mainpop, 'audited_local_distance_km')]:
            for value in [True, False]:
                # Exact reconstruction of the quoted controls for the legacy pair.
                mask = sub[endpoint].eq(value)
                if endpoint == 'legacy_broad_pipe_flag' and not value:
                    mask = sub['legacy_non_rng_development_flag']
                sample = sub.loc[mask, field]
                summaries.append({'population': population, 'endpoint': endpoint, 'positive': value,
                                  'n': len(sample), 'median_km': float(sample.median()),
                                  'mean_km': float(sample.mean()), 'within5km_n': int(sample.le(5).sum()),
                                  'within5km_pct': 100*float(sample.le(5).mean())})
    pd.DataFrame(summaries).to_csv(out/'ENDPOINT_DISTANCE_COMPARISON.csv', index=False, encoding='utf-8-sig')
    pipe_rows = frame[frame['Project Type Category'].eq('Renewable Natural Gas') & frame['RNG Delivery Method'].eq('Pipeline Injection')].copy()
    pipe_rows[['Landfill ID', 'Landfill Name', 'Project ID', 'Current Project Status',
               'Project Start Date', 'excel_row']].to_csv(out/'PIPELINE_PROJECT_STATUS_ORIGINAL_ROWS.csv', index=False, encoding='utf-8-sig')
    pipe_status = pipe_rows.groupby('Current Project Status').agg(project_rows=('Landfill ID','size'),
                                                                  unique_landfills=('Landfill ID','nunique'))
    pipe_status.to_csv(out/'PIPELINE_STATUS_COUNTS.csv', encoding='utf-8-sig')

    # Bounded audit of an existing annual snapshot; no synthetic risk set, no Cox.
    with zipfile.ZipFile(HIST) as z:
        member = '2020Aug_lmopdata.xlsx'
        payload = z.read(member)
    historical = pd.read_excel(io.BytesIO(payload), sheet_name='LMOP Database')
    hlabel = labels(historical)
    hist_base = historical.groupby('Landfill ID', sort=True).first()[['State', 'Latitude', 'Longitude', 'Waste in Place (tons)', 'Waste in Place Year']].join(hlabel)
    hist_base = hist_base.add_prefix('baseline2020_')
    join = hist_base.join(tab[['pipe_operational', 'pipe_operational_or_shutdown', 'any_rng_record']], how='outer')
    join['present2020'] = join.index.isin(hist_base.index)
    join['present2024'] = join.index.isin(tab.index)
    join.to_csv(out/'SNAPSHOT_2020_2024_FEASIBILITY.csv', encoding='utf-8-sig')
    baseline_no_op = hist_base.index[~hist_base['baseline2020_pipe_operational']]
    matched_no_op = tab.index.intersection(baseline_no_op)
    changed_ids = matched_no_op[tab.loc[matched_no_op, 'pipe_operational'].to_numpy()]
    changed_rows = []
    for cid in changed_ids:
        current = pipe_rows[pipe_rows['Landfill ID'].eq(cid) & pipe_rows['Current Project Status'].eq('Operational')]
        previous = historical[historical['Landfill ID'].eq(cid) & historical['Project Type Category'].eq('Renewable Natural Gas')]
        dates = pd.to_datetime(current['Project Start Date'], errors='coerce').dropna()
        first = dates.min() if len(dates) else pd.NaT
        prior_pipe_history = bool(((previous['RNG Delivery Method'].eq('Pipeline Injection')) & previous['Current Project Status'].isin(['Operational','Shutdown'])).any())
        changed_rows.append({'Landfill ID': cid, 'name': tab.loc[cid,'Landfill Name'],
                              'state': tab.loc[cid,'State'], 'earliest_2024_operational_pipe_start': first,
                              'start_before_2020_Aug01': bool(pd.notna(first) and first < pd.Timestamp('2020-08-01')),
                              'start_after_2020_Aug31': bool(pd.notna(first) and first > pd.Timestamp('2020-08-31')),
                              'baseline_any_rng': bool(len(previous)),
                              'baseline_prior_operational_or_shutdown_pipeline': prior_pipe_history,
                              'baseline_rng_statuses': ';'.join(sorted(previous['Current Project Status'].dropna().unique())),
                              'current_excel_rows': ';'.join(map(str,current['excel_row']))})
    changed = pd.DataFrame(changed_rows)
    changed.to_csv(out/'SNAPSHOT_NEW_OPERATIONAL_CANDIDATES.csv', index=False, encoding='utf-8-sig')
    historical_summary = {
        'member': member, 'member_sha256': hashlib.sha256(payload).hexdigest(),
        'rows2020': len(historical), 'unique_landfills2020': len(hist_base),
        'pipeline_operational2020': int(hlabel['pipe_operational'].sum()),
        'common_ids': int(join['present2020'].mul(join['present2024']).sum()),
        'only2020': int((join['present2020'] & ~join['present2024']).sum()),
        'only2024': int((~join['present2020'] & join['present2024']).sum()),
        'no_operational_pipeline2020_and_matched2024': len(matched_no_op),
        'among_these_operational_pipeline2024': int(tab.loc[matched_no_op,'pipe_operational'].sum()),
        'candidate_start_before_baseline_month': int(changed['start_before_2020_Aug01'].sum()),
        'candidate_start_after_baseline_month': int(changed['start_after_2020_Aug31'].sum()),
        'candidate_baseline_prior_operational_or_shutdown_pipe': int(changed['baseline_prior_operational_or_shutdown_pipeline'].sum()),
        'limitations': ['Not a frozen incidence risk set; shutdown/prior RNG and delivery-category changes not yet adjudicated.',
                       'Snapshot appearance is not verified commissioning; ID stability and dated field consistency need checks.',
                       'Only baseline covariates would be used for a prospective association model; no causal identification established.']}
    save(out/'HISTORICAL_FEASIBILITY.json', historical_summary)
    tab.to_csv(out/'LANDFILL_SIGNAL_AUDIT.csv', encoding='utf-8-sig')
    complete = mainpop['Waste in Place (tons)'].gt(0) & mainpop['Year Landfill Opened'].notna()
    report = {
        'scope': 'Descriptive audit and protocol development, not adjusted association or frozen cohort',
        'registry_landfills': len(tab), 'legacy_analyzable': int(tab['legacy_analyzable'].sum()),
        'coordinate_landfills': int(tab['has_coordinate'].sum()),
        'legacy_finite_distances': int(tab['legacy_distance_km'].notna().sum()),
        'legacy_positive_negative_excluded': [int((tab['legacy_broad_pipe_flag'] & tab['legacy_distance_km'].notna()).sum()),
                                             int((tab['legacy_non_rng_development_flag'] & tab['legacy_distance_km'].notna()).sum()),
                                             int((~tab['legacy_broad_pipe_flag'] & ~tab['legacy_non_rng_development_flag'] & tab['legacy_distance_km'].notna()).sum())],
        'pipeline_operational_all': int(tab['pipe_operational'].sum()),
        'pipeline_development_all': int(tab['pipe_operational_construction_planned'].sum()),
        'legacy_swapped_coordinate_output_rows': int(swapped.sum()),
        'nonconus_assigned_legacy_finite_distances': int((~tab['conus_descriptive_sensitivity'] & tab['legacy_distance_km'].notna()).sum()),
        'conus_full_search_landfills': len(mainpop),
        'full_search_changed_over_1m': int(q['old_minus_full_km'].abs().gt(.001).sum()),
        'max_old_minus_full_km': float(q['old_minus_full_km'].max()),
        'complete_coords_positive_waste_openyear_conus': int(complete.sum()),
        'operational_pipeline_in_this_complete_subset': int(mainpop.loc[complete,'pipe_operational'].sum()),
        'distance_limitations': ['Approximate local planar distance after inverse3857; independent geodesic validation pending.',
                                 'CONUS restriction proposed for sensitivity; not silent removal from registry.',
                                 'Nearest major mapped pipeline is not a verified feasible interconnection or route cost.'],
        'historical_feasibility': historical_summary,
        'models_fitted': 0, 'human_used_hours': None, 'human_remaining_hours': None,
        'manual_original_verification': 'PENDING; assistant computation does not change status'}
    checks = {'unique_landfill_ids': bool(tab.index.is_unique),
              'op_pipeline_count_matches_previous_audit': int(tab['pipe_operational'].sum()) == 104,
              'all_conus_coordinate_sites_have_finite_nonnegative_audited_distance': bool(mainpop['audited_local_distance_km'].ge(0).all()) and len(mainpop) == len(selected),
              'full_search_never_farther_than_window_search': bool(q['old_minus_full_km'].ge(-1e-9).all()),
              'original_inputs_unchanged': hashes == {str(p.relative_to(ROOT)):sha(p) for p in inputs}}
    save(out/'SIGNAL_AUDIT.json', report)
    save(out/'CHECKS.json', checks)
    assert all(checks.values()), checks
    shutil.copy2(__file__, out/'CODE_SNAPSHOT.py')
    save(out/'RUN_RECORD.json', {'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),
         'machine_seconds':time.perf_counter()-t0,'command':[sys.executable,*sys.argv],
         'packages':{x:importlib.metadata.version(x) for x in ['numpy','pandas','openpyxl']},
         'python':sys.version,'platform':platform.platform(),'inputs_sha256':hashes,'script_sha256':sha(Path(__file__)),
         'git_state':'workspace_root_not_a_git_repository','random_seed':None,'split':'none; no model',
         'human_time':'unknown; machine time recorded separately','output':str(out.relative_to(ROOT))})
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
