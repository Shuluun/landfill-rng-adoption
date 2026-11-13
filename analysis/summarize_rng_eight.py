"""Refresh the fixed-eight review ledger from existing real records; no new links."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import importlib.metadata
import json
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rng.evidence import load, sha
from rng.analysis import plant_series, comparison_eligibility
from rng.pipeline import write_json, write_csv, project_path


def main():
    started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--mallard-run', default='outputs/2026-10-26_rng_linkage/mallard_005')
    parser.add_argument('--case-run', action='append', default=[], help='Explicit additional completed first-pass ID=output_directory')
    args = parser.parse_args()
    cfg = load(ROOT / 'config/rng_pilot.json')
    paths = {k: project_path(ROOT, v) for k, v in cfg['inputs'].items()}
    freeze = load(paths['freeze'])
    baseline_path = ROOT / 'reports/registry_baseline_2026-10-25_001/BASELINE_SUMMARY.json'
    baseline = {s['id']: s for s in load(baseline_path)['sites']}
    events = load(paths['events'])['sites']
    raw = load(paths['generation'])
    assert sha(paths['generation']) == cfg['generation_sha256']
    for record in freeze['outputs']:
        assert sha(project_path(ROOT, record['path'])) == record['sha256']
    mallard = project_path(ROOT, args.mallard_run)
    extra_runs = {}
    for value in args.case_run:
        fid, directory = value.split('=',1)
        assert int(fid) in freeze['selected_ids'] and int(fid) not in [1479,1676]
        resolved = project_path(ROOT,directory)
        assert load(resolved/'SUMMARY.json')['case']==int(fid)
        extra_runs[int(fid)] = (directory,resolved)
    sources = [ROOT / 'config/rng_pilot.json', paths['freeze'], paths['events'], paths['generation'], baseline_path,
               mallard / 'SUMMARY.json', mallard / 'PUBLIC_CLAIMS.json', mallard / 'RUN_RECORD.json']
    for _, directory in extra_runs.values():
        sources.extend(directory/f for f in ['SUMMARY.json','PUBLIC_CLAIMS.json','RUN_RECORD.json'])
    input_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    out = project_path(ROOT, args.run_dir)
    assert out.is_relative_to(ROOT / 'outputs')
    out.mkdir(parents=True, exist_ok=False)
    rows, observations = [], []
    for event in events:
        fid, pid = event['landfill_id'], event['plant_candidate_id']
        reg = baseline[fid]
        anchor = int(reg['RNG_stated_start'][:4])
        series = plant_series(raw, pid, cfg['generation_scope'], cfg['windows'], anchor)
        eligibility = comparison_eligibility(series)
        observations.extend({'landfill_id_for_candidate_context_only': fid, **r} for r in series)
        if fid == 1676:
            status = 'DOCUMENTED_HISTORICAL_ID_CHAIN_AND_SUPPLIER_RNG_EVENTS_PENDING_HUMAN'
            added = 'Historical partial-site ID chain; three old units report2013 retirement; module operating2022-03, acceptance2023-01(context), RNG producing/injecting asof2023-04-03. Complete electricity assets and event-year old-plant gas supply unresolved.'
            detail = args.mallard_run
            next_task = 'Human review of three original entries; full annual EIA923 coverage remains unconfirmed. Do not delay eight-case first pass.'
        elif fid == 1479:
            status = 'ORIGINAL_ROWS_AND_RULE_COMPARISON_DONE_PENDING_PHYSICAL_RELATION'
            added = 'Five listed units report retirement2018-02; registry RNG2018-05. Prior issuer note not newly reverified. Plant output missing in main post years; site pathway unknown.'
            detail = 'outputs/2026-10-26_rng_linkage/refactored_atascocita_003'
            next_task = 'Event-time physical relation and independent operating evidence remain needed; reuse existing run.'
        elif fid in extra_runs:
            detail, directory = extra_runs[fid]
            status = 'FIRST_PASS_ORIGINALS_AND_PUBLIC_DOCUMENTS_READ_PENDING_HUMAN_PHYSICAL_BOUNDARY'
            added = load(directory/'PUBLIC_CLAIMS.json')['conclusion']
            next_task = 'Critical human original review and event-valid electricity/asset relation remain pending; first pass can continue to next frozen case.'
        else:
            status = 'EIGHT_SITE_PREFLIGHT_AVAILABLE_DETAILED_CASE_REVIEW_PENDING'
            added = 'Existing registry/inventory lead only; '+event['original_identity_tier']+'. No newly verified physical relation or site operation finding.'
            detail = str(paths['events'].relative_to(ROOT))
            next_task = 'First-pass source/relationship review in frozen-ID order; keep unknowns rather than replace case.'
        registry_judgment = ('Electricity and RNG both listed Operational in Sep2024 snapshot; simultaneous operation not established.' if reg['snapshot_co_listing_Operational_electricity_and_RNG'] else
                             'All listed electricity projects registered Shutdown; RNG start listed. Actual complete site withdrawal not established.')
        rows.append({'landfill_id': fid, 'name': event['name'], 'plant_lead_not_assignment': pid,
            'registered_rng_start': reg['RNG_stated_start'], 'registry_supported_judgment': registry_judgment,
            'added_evidence_supported_judgment': added, 'review_status': status,
            'pre_nonmissing_years_of3': eligibility['pre_nonmissing_years'],
            'post_nonmissing_years_of2': eligibility['post_nonmissing_years'],
            'five_year_candidate_plant_values_complete': eligibility['five_year_values_complete'],
            'numeric_comparison_eligible': eligibility['eligible'],
            'exclusion_reason': 'Time-valid landfill/asset relationship and measurement comparability not established'+(' ; pre/post values incomplete' if not eligibility['five_year_values_complete'] else ''),
            'site_electricity_pathway': 'UNDETERMINED', 'human_verification': 'PENDING',
            'registry_source_path': 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx',
            'registry_sheet': 'LMOP Database', 'registry_excel_rows': reg['source_excel_rows'],
            'inventory_evidence': str(paths['events'].relative_to(ROOT)), 'detailed_case_record': detail, 'next_task': next_task})
    assert [r['landfill_id'] for r in rows] == freeze['selected_ids'] and len(rows) == 8
    write_csv(out / 'EIGHT_CASE_STATUS.csv', rows)
    write_json(out / 'EIGHT_CASE_STATUS.json', {'scope': 'Fixed eight, not national; candidate-plant values are not assigned to landfill', 'rows': rows})
    write_csv(out / 'CONDITIONAL_PLANT_COVERAGE.csv', observations)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    codes = {'record_missing': 0, 'value_missing': 1, 'zero': 2, 'negative': 3, 'positive': 4}
    colors = ['#dedede', '#b998c2', '#e7c36f', '#cc7370', '#4b8a78']
    matrix = [[codes[r['record_status']] for r in observations if r['landfill_id_for_candidate_context_only'] == s['landfill_id']] for s in rows]
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    ax.imshow(matrix, cmap=ListedColormap(colors), norm=BoundaryNorm([-.5,.5,1.5,2.5,3.5,4.5], 5), aspect='auto')
    ax.set_xticks(range(10), range(2015, 2025))
    ax.set_yticks(range(8), [f"{r['landfill_id']} / plant lead {r['plant_lead_not_assignment']}" for r in rows])
    ax.set_title('Coverage of candidate-plant LFG / ALL net-generation extract\nLinks provisional; missing rows are not zero or site non-operation', fontsize=11)
    ax.set_xlabel('Calendar year; EIA annual electricity API snapshot, MWh. No allocation to landfill.')
    ax.legend(handles=[Patch(facecolor=colors[n], label=label) for label,n in codes.items()], loc='upper center', bbox_to_anchor=(.5,-.13), ncols=5, fontsize=8)
    fig.savefig(out / 'CANDIDATE_PLANT_COVERAGE.png', dpi=150)
    plt.close(fig)
    summary = {'fixed_cases': 8, 'with_detailed_reproducible_case_runs': 2+len(extra_runs),
               'first_pass_detailed_source_review_pending': 6-len(extra_runs),
               'candidate_plant_five_year_value_complete_cases': [r['landfill_id'] for r in rows if r['five_year_candidate_plant_values_complete']],
               'eligible_numeric_comparisons': sum(r['numeric_comparison_eligible'] for r in rows),
               'complete_site_pathway_classifications': 0,
               'next_case': next((r['landfill_id'] for r in rows if r['landfill_id'] not in [1479,1676,*extra_runs]),None),
               'human_hours_used': None, 'human_hours_remaining': None}
    summary['bounded_asset_subset_transition_documented_cases'] = [fid for fid, (_,directory) in extra_runs.items() if load(directory/'PUBLIC_CLAIMS.json').get('bounded_asset_transition_documented')]
    summary['next_stage_action'] = 'Targeted identity/asset crosswalk and human original review; prepare evidence-bounded draft' if summary['next_case'] is None else 'Continue remaining fixed cases first pass'
    write_json(out / 'SUMMARY.json', summary)
    checks = {'eight_retained': True, 'no_numeric_comparison_without_relation': summary['eligible_numeric_comparisons'] == 0,
              'no_landfill_allocation': all(r['landfill_assigned_MWh'] is None for r in observations),
              'plant_year_keys_unique': len({(r['plant_code'],r['year']) for r in observations}) == 80,
              'inputs_unchanged': all(sha(ROOT / p) == h for p,h in input_hashes.items())}
    code = [Path(__file__), *sorted((ROOT / 'src/rng').glob('*.py'))]
    write_json(out / 'CODE_SNAPSHOT.json', {str(p.relative_to(ROOT)): {'sha256': sha(p), 'text': p.read_text(encoding='utf-8')} for p in code})
    write_json(out / 'RUN_RECORD.json', {'utc': datetime.now(timezone.utc).isoformat(), 'command': [sys.executable,*sys.argv],
        'cwd': str(Path.cwd()), 'python': sys.version, 'platform': platform.platform(),
        'packages': {p: importlib.metadata.version(p) for p in ['openpyxl','matplotlib','pypdf']},
        'input_sha256': input_hashes, 'module_sha256': {str(p.relative_to(ROOT)): sha(p) for p in code},
        'git_state': 'No root Git repository; hashes and code snapshots retained', 'random_seed': 20261020,
        'split': 'No model trained; repeated years not independent facilities', 'network_calls': 0,
        'human_hours_used': None, 'human_hours_remaining': None, 'elapsed_tool_wall_seconds': time.perf_counter()-started,
        'checks': checks, 'output_sha256': {p.name: sha(p) for p in out.iterdir() if p.is_file()}})
    assert all(checks.values())
    print(json.dumps({'output':str(out), 'summary':summary, 'checks':checks}, ensure_ascii=False))


if __name__ == '__main__':
    main()
