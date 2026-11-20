"""Small local runner joining existing inputs to evidence and case analysis."""
from pathlib import Path
from datetime import datetime, date, timezone
from collections import Counter
import csv
import importlib.metadata
import json
import platform
import random
import sys
import time

from . import linkage
from .evidence import load, sha, original_case_records, relations, public_supplement
from .analysis import date_and_asset_checks, plant_series, timeline_plot, comparison_eligibility, public_event_date_check


def project_path(root, value):
    path = (root / str(value).replace('\\', '/')).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'Path leaves project: {value}')
    return path


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=json_default, indent=2), encoding='utf-8')


def write_csv(path, rows):
    if not rows:
        raise ValueError(f'No records for {path.name}; do not create an empty deliverable')
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)


def run(root, fid, config_path, run_dir=None):
    started = time.perf_counter()
    cfg_path = project_path(root, config_path)
    cfg = load(cfg_path)
    if str(fid) not in cfg['cases']:
        raise ValueError('Case has no evidence profile in the existing pilot configuration; do not silently substitute a site.')
    profile = cfg['cases'][str(fid)]
    pid = profile['plant_lead']
    paths = {key: project_path(root, value) for key, value in cfg['inputs'].items()}
    freeze, psource, isource = load(paths['freeze']), load(paths['plant_source']), load(paths['inventory_source'])
    assert freeze['random_seed'] == cfg['frozen_seed']
    for row in freeze['outputs']:
        assert sha(project_path(root, row['path'])) == row['sha256']
    with paths['eligibility'].open(encoding='utf-8-sig', newline='') as handle:
        eligible = sorted(int(r['landfill_id']) for r in csv.DictReader(handle) if r['status'] == 'eligible for frozen candidate draw')
    assert len(eligible) == 16 and sorted(random.Random(freeze['random_seed']).sample(eligible, 8)) == freeze['selected_ids']
    assert fid in freeze['selected_ids']
    raw_lmop = project_path(root, freeze['input_path'])
    raw_plant = project_path(root, psource['local_original'])
    raw_inventory = project_path(root, isource['local_path'])
    pins = {raw_lmop: freeze['input_sha256'], raw_plant: psource['original_sha256'], raw_inventory: isource['sha256'],
            paths['plant_catalogue']: psource['catalog_sha256'], paths['generation']: cfg['generation_sha256'],
            paths['inventory_rows']: isource['relevant_output_sha256']}
    assert all(sha(p) == digest for p, digest in pins.items())
    input_files = [cfg_path, *paths.values(), raw_lmop, raw_plant, raw_inventory]
    if profile.get('issuer_evidence_note'):
        note = project_path(root, profile['issuer_evidence_note'])
        year, month = map(int, profile['issuer_month'].split('-'))
        assert f'{year}年{month}月' in note.read_text(encoding='utf-8')
        input_files.append(note)
    supplement_path = profile.get('public_evidence_manifest')
    if supplement_path:
        supplement_config = load(project_path(root, supplement_path))
        input_files.extend([project_path(root, supplement_path), project_path(root, supplement_config['download_manifest'])])
        input_files.extend(project_path(root, r['path']) for r in load(project_path(root, supplement_config['download_manifest']))['records'] if r.get('sha256'))
    hashes_before = {str(p.relative_to(root)): sha(p) for p in input_files}
    out = project_path(root, run_dir or f"outputs/{datetime.now(timezone.utc):%Y-%m-%d}_rng_linkage/{fid}_{datetime.now(timezone.utc):%H%M%S_%f}Z")
    if not out.is_relative_to(root / 'outputs'):
        raise ValueError('Outputs must stay inside the existing outputs directory')
    out.mkdir(parents=True, exist_ok=False)

    plant2017_catalogue = load(paths['plant_catalogue'])
    prior_plant = next((p for p in plant2017_catalogue if p['Plant Code'] == pid), None)
    inventory_rows = load(paths['inventory_rows'])
    catalogue = plant2017_catalogue if profile['candidate_catalogue'] == 'plant2017' else linkage.inventory_catalogue(inventory_rows)
    site = next(r for r in load(paths['geography'])['sites'] if r['landfill_id'] == fid)['landfill']
    event = next(r for r in load(paths['events'])['sites'] if r['landfill_id'] == fid)
    assert event['plant_candidate_id'] == pid
    features = [linkage.candidate_features(site, p) for p in catalogue]
    ranking = linkage.retrieve(features, cfg['candidate_rules'])
    target = next(r for r in features if r['plant_code'] == pid)
    registry, _, units, projection_omissions = original_case_records(root, paths, freeze, psource, isource, fid, pid,
                                               load(paths['registry_rows'])['records'], event, prior_plant)
    relation_doc, pointers = relations(root, fid, pid, site, target, registry, units, prior_plant, psource, isource, freeze)
    supplement = None
    if supplement_path:
        supplement, _ = public_supplement(root, supplement_path, relation_doc)
        assert supplement['case'] == fid and supplement['plant_lead'] == pid
    anchor = min(r['Project Start Date'].date() for _, r in registry if r['Project Type Category'] == 'Renewable Natural Gas')
    with paths['cohort'].open(encoding='utf-8-sig', newline='') as handle:
        frozen_case = next(r for r in csv.DictReader(handle) if int(r['landfill_id']) == fid)
    assert anchor.isoformat() == frozen_case['snapshot_stated_earliest_RNG_start']
    issuer_pointer = None
    if profile.get('issuer_evidence_note'):
        issuer_pointer = {'path': profile['issuer_evidence_note'], 'sha256': sha(note),
                          'scope': 'Previously targeted issuer text in existing note; original not reverified this run.'}
    dates = date_and_asset_checks(anchor, registry, units, cfg['windows'], profile.get('issuer_month'), issuer_pointer)
    raw_generation = load(paths['generation'])
    assert len(raw_generation['response']['data']) == int(raw_generation['response']['total']) == 3507
    series = plant_series(raw_generation, pid, cfg['generation_scope'], cfg['windows'], anchor.year)
    eligibility = comparison_eligibility(series)
    write_json(out / 'NUMERICAL_ELIGIBILITY.json', eligibility)
    if supplement:
        write_json(out / 'PUBLIC_CLAIMS.json', supplement)
        write_json(out / 'OPERATING_EVENTS.json', {'events': supplement['events'], 'publication_dates': supplement['publication_dates'], 'human_review': 'PENDING'})
        if any(e['event_type'] == 'MODULE_OPERATION_SINCE_REPORTED_MONTH' for e in supplement['events']):
            write_json(out / 'PUBLIC_EVENT_DATE_CHECK.json', public_event_date_check(supplement, anchor, cfg['windows']))
        else:
            write_json(out / 'PUBLIC_EVENT_DATE_CHECK.json', {'primary_anchor': anchor.isoformat(),
                'primary_anchor_changed': False, 'event_kinds_distinguished': True,
                'commercial_start_known': supplement.get('exact_commercial_start_date') is not None,
                'interpretation': supplement['date_interpretation']})
    rows = [{'method': method, 'rank': i, **r, 'joint_tier': linkage.joint_tier(r, cfg['candidate_rules'])}
            for method, group in ranking.items() for i, r in enumerate(group, 1)]
    write_csv(out / 'CANDIDATE_COMPARISON.csv', rows)
    write_csv(out / 'PLANT_GENERATION.csv', series)
    write_json(out / 'CASE_RELATIONS.json', relation_doc)
    write_json(out / 'SOURCE_SPOT_CHECKS.json', {'status': 'ORIGINAL_ROWS_CHECKED', 'sources': pointers, 'raw_records_read_only': True,
                                               'plant2017_present': prior_plant is not None, 'new_dataset_downloads': 0,
                                               'legacy_projection_omissions': projection_omissions})
    write_json(out / 'DATE_WINDOW_CHECK.json', dates)
    write_json(out / 'CASE_STANDARDIZED_INPUTS.json', {'site': site, 'plant_lead': target,
                'registry_events': [{'source_row': n, 'project_id': str(r['Project ID']), 'category': r['Project Type Category'],
                                      'registered_start': r['Project Start Date'], 'registered_shutdown': r['Project Shutdown Date']} for n, r in registry],
                'unit_events': [{'sheet': s, 'source_row': n, 'generator_id': str(r['Generator ID']), 'primary_fuel': r['Energy Source Code'],
                                 'reported_operating_year': r.get('Operating Year'), 'reported_operating_month': r.get('Operating Month'),
                                 'reported_retirement_year': r.get('Retirement Year'), 'reported_retirement_month': r.get('Retirement Month')} for s, n, r in units]})
    timeline_plot(out / 'EVENT_TIMELINE.png', site['Landfill Name'], pid, fid, registry, units, anchor, cfg['windows'], supplement['events'] if supplement else ())
    ranking_summary = {m: [{k: r[k] for k in ['plant_code', 'plant_name', 'name_score', 'distance_km']} for r in group] for m, group in ranking.items()}
    summary = {'case': fid, 'sample_seed': freeze['random_seed'], 'catalogue_kind': profile['candidate_catalogue'],
               'candidate_catalogue_records': len(catalogue), 'same_state_records': sum(r['same_state'] for r in features),
               'missing_coordinate_records_scored_by_name': sum(not r['coordinate_available'] for r in features),
               'rule_results': ranking_summary, 'target_features': target, 'typed_relations': len(relation_doc['relations']),
               'site_pathway': 'UNDETERMINED', 'calendar_window_change': None if dates.get('calendar_windows_unchanged_under_supported_rng_dates') is None else not dates['calendar_windows_unchanged_under_supported_rng_dates'],
               'date_gap_days': dates.get('days_between_reported_retirement_month_and_registered_rng_date'),
               'asset_scope_scenarios': len(dates['asset_scope_scenarios']),
               'all_reported_asset_end_scenarios_before_background': all(s['entirely_before_background'] for s in dates['asset_scope_scenarios']) if dates['asset_scope_scenarios'] else None,
               'plant_generation_status_counts': dict(Counter(r['record_status'] for r in series)),
               'plant2017_contains_lead': prior_plant is not None,
               'legacy_projection_omissions_recovered_from_original': len(projection_omissions),
               'numerical_comparison_eligible': eligibility['eligible'],
               'public_evidence_added': supplement is not None,
               'limits': ['Candidate links are provisional; no supervised model or national accuracy claim.',
                          'This case uses '+profile['candidate_catalogue']+'; fuel-limited staged inventory and2017 all-fuel catalogues are different pools.',
                          'Plant-level generation is not allocated to a landfill; absent extract rows are not zero or proof of no generation.']}
    write_json(out / 'SUMMARY.json', summary)
    tops = {m: group[0]['plant_code'] if group else None for m, group in ranking.items()}
    result = (f"{site['Landfill Name']}：真实数据增量 | LMOP{fid} / 优先EIA{pid}\n\n"
              f"三规则首候选：{tops}；均为候选，不自动确认供气或实体等同。\n"
              f"候选池：{profile['candidate_catalogue']}，{len(catalogue)}条；2017目录是否包含该线索：{prior_plant is not None}。\n"
              f"报告坐标距离{target['distance_km']}km，名称分数{target['name_score']}（不是概率）。\n"
              f"主窗口：{dates['fixed_registry_anchor']}。登记锚点不变，实际投产另记。\n"
              f"有原行依据的资产/日期范围{len(dates['asset_scope_scenarios'])}种；是否全部早于背景窗：{summary['all_reported_asset_end_scenarios_before_background']}。\n"
              f"EIA2015—2024该电厂LFG/ALL记录状态：{summary['plant_generation_status_counts']}，缺失不补零。\n"
              '完整电厂电量只留在plant层，不分配给填埋场/扩建。共享设施与气源边界未解。\n'
              '结果支持所列报告事件的关系/时间核对；整场路径、事件时供气与资产完整性仍未确定。\n'
              'CASE_RELATIONS、SOURCE_SPOT_CHECKS及DATE_WINDOW_CHECK保存类型、有效期未知、源位置与未解原因。\n')
    if supplement:
        result += '\n新增公开证据（逐项来源和限制见PUBLIC_CLAIMS；人工复核待完成）：\n'+supplement['conclusion']+'\n'
    (out / 'RESULT_ZH.txt').write_text(result, encoding='utf-8')
    code_files = [root / 'scripts/lmop_rng_linkage_case.py', *sorted((root / 'src/rng').glob('*.py'))]
    write_json(out / 'CODE_SNAPSHOT.json', {str(p.relative_to(root)): {'sha256': sha(p), 'text': p.read_text(encoding='utf-8')} for p in code_files})
    checks = {'original_sources_and_frozen_inputs_unchanged': all(sha(p) == digest for p, digest in pins.items()),
              'all_run_inputs_unchanged': all(sha(root / p) == h for p, h in hashes_before.items()),
              'frozen_eight_reproduced': True, 'original_row_checks_passed': True,
              'no_electric_plant_supply_autoacceptance': all(r['status'].startswith('UNRESOLVED') for r in relation_doc['relations'] if r['relation_type'] == 'GAS_SUPPLY' and r['to'] == f'EIA:Plant{pid}'),
              'effective_intervals_not_imputed': all(r['valid_from'] is None and r['valid_to'] is None for r in relation_doc['relations']),
              'plant_year_output_unique': len({(r['plant_code'], r['year'], r['fuel'], r['prime_mover']) for r in series}) == len(series) == 10,
              'no_landfill_generation_allocation': all(r['landfill_assigned_MWh'] is None for r in series),
              'plot_created': (out / 'EVENT_TIMELINE.png').stat().st_size > 1000,
              'runtime_bounded': time.perf_counter()-started < cfg['run_limits']['wall_seconds']}
    record = {'utc': datetime.now(timezone.utc).isoformat(), 'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
              'python': sys.version, 'platform': platform.platform(), 'packages': {k: importlib.metadata.version(k) for k in ['openpyxl', 'matplotlib']},
              'input_sha256': hashes_before, 'config_snapshot': cfg, 'module_sha256': {str(p.relative_to(root)): sha(p) for p in code_files},
              'git_state': 'No root Git repository; preserved old run and code snapshots', 'random_seed': freeze['random_seed'],
              'seed_use': 'Original draw verification only', 'split': 'Not applicable: evidence case analysis, not trained-model evaluation',
              'human_hours_used': None, 'human_hours_remaining': None, 'elapsed_tool_wall_seconds': time.perf_counter()-started,
              'network_calls': 0, 'paid_script_cost': 0, 'checks': checks,
              'outputs': {p.name: sha(p) for p in out.iterdir() if p.is_file()}}
    write_json(out / 'RUN_RECORD.json', record)
    assert all(checks.values()), checks
    print(json.dumps({'output': str(out), 'summary': summary, 'checks': checks, 'elapsed_seconds': record['elapsed_tool_wall_seconds']}, ensure_ascii=False))
    return out
