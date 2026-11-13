"""Audit the frozen registry baseline and export a manually coded contribution matrix.

The interpretive labels are explicitly curated, not inferred ground truth or an ML score.
Run in a new directory; existing research outputs and original inputs are never rewritten.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import shutil
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rng.evidence import locate_keyed_records
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

PLAN = ROOT / 'reports/publication_plan_2026-10-25'
OLD = ROOT / 'outputs/2026-10-26_rng_linkage'
PUBLIC = ROOT / 'inputs/public/rng_contribution_2026-10-27'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value):
    return value.isoformat() if isinstance(value, datetime) else value


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def main():
    start = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    out = (ROOT / args.run_dir).resolve()
    assert out.is_relative_to(ROOT / 'outputs'), 'Run must remain in existing outputs'
    out.mkdir(parents=True, exist_ok=False)
    inputs = set()
    checks = []

    def track(path):
        path = path.resolve()
        assert path.is_relative_to(ROOT) and path.is_file(), str(path)
        inputs.add(path)
        return path

    def check(label, condition):
        assert condition, label
        checks.append({'check': label, 'status': 'PASS'})

    coding_path = track(PLAN / 'EIGHT_CONTRIBUTION_CODING_2026-10-27.json')
    evidence_path = track(PLAN / 'CONTRIBUTION_CASE_EVIDENCE_2026-10-27.json')
    coding, new_evidence = load(coding_path), load(evidence_path)
    cfg = load(track(ROOT / 'config/rng_pilot.json'))
    ids = [c['landfill_id'] for c in coding['cases']]
    check('fixed eight and seed unchanged', ids == [217,1456,1479,1676,1820,1890,1939,2207]
          and cfg['frozen_seed'] == 20261020 and set(map(int, cfg['cases'])) == set(ids))
    check('four common questions, no candidate-pair sample inflation',
          all([c['question'] for c in row['cells']] == coding['questions'] for row in coding['cases']))
    track(ROOT / cfg['inputs']['freeze'])
    track(ROOT / cfg['inputs']['cohort'])

    # All columns, including Direct projects, capacity and flow: honest registry baseline.
    raw = track(ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx')
    check('frozen LMOP SHA unchanged', digest(raw) == 'a5c8bea26e7b5f6ecef247b762bde89b999915504814825a1eac7a1cd9f4ddd3')
    wb = load_workbook(raw, read_only=True, data_only=True)
    ws = wb['LMOP Database']
    headers = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True)))
    records = []
    for excel_row, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        d = dict(zip(headers, values))
        if d['Landfill ID'] in ids:
            records.append({'excel_row':excel_row, 'fields':{k:normalized(v) for k,v in d.items()},
                            'cells':{k:f'{get_column_letter(i)}{excel_row}' for i,k in enumerate(headers,1)}})
    wb.close()
    baseline = {'path':str(raw), 'sha256':digest(raw), 'sheet':'LMOP Database',
                'header_excel_row':1, 'all_columns':headers, 'records':records,
                'scope':'Snapshot registration; no continuous operation or plant membership inferred'}
    write_json(out / 'REGISTRY_FULL_BASELINE.json', baseline)
    prior = load(track(ROOT / cfg['inputs']['registry_rows']))['records']
    check('all34 frozen project rows match prior extraction, including dates and row locators', len(records)==34
          and all(any(old['Project ID']==r['fields']['Project ID'] and old['excel_row']==r['excel_row']
                      and all(r['fields'][k]==v for k,v in old.items() if k in r['fields']) for old in prior)
                  for r in records))
    south = [r['fields'] for r in records if r['fields']['Landfill ID']==1939]
    check('SouthSide existing Operational Direct projects retained in baseline',
          len([r for r in south if r['Project Type Category']=='Direct' and r['Current Project Status']=='Operational'])==2)

    fields = ['Utility ID','Utility Name','Plant Code','Plant Name','Generator ID',
              'Nameplate Capacity (MW)','Status','Operating Month','Operating Year','Energy Source 1']
    g2017 = track(ROOT / 'inputs/public/rng_eight_quantitative_2026-10-26/3_1_Generator_Y2017.xlsx')
    g2018 = track(PUBLIC / '3_1_Generator_Y2018.xlsx')
    package = track(PUBLIC / 'eia8602018_archive.zip')
    with zipfile.ZipFile(package) as archive:
        member = '3_1_Generator_Y2018.xlsx'
        check('single2018 workbook matches inspected official ZIP member',
              hashlib.sha256(archive.read(member)).hexdigest()==digest(g2018))
    old_url_response = track(PUBLIC / 'eia8602018.zip')
    check('HTML returned by obsoleteURL is rejected as data', not zipfile.is_zipfile(old_url_response)
          and old_url_response.read_bytes().lstrip().lower().startswith(b'<!doctype html>'))
    locators = {'2017':{}, '2018':{}, 'zip_member':member, '2018_zip_sha256':digest(package)}
    for plant in [10748,55526,54549]:
        locators['2017'][str(plant)] = locate_keyed_records(g2017, 'Operable', {'Plant Code':plant}, fields)
    for sheet in ['Operable','Proposed','Retired and Canceled']:
        use = fields + (['Retirement Month','Retirement Year'] if sheet=='Retired and Canceled' else [])
        locators['2018'][sheet] = locate_keyed_records(g2018, sheet, {'Plant Code':55526}, use)
    write_json(out / 'THREE_CASE_GENERATOR_LOCATORS.json', locators)
    rows17 = locators['2017']['55526']['matched_records']
    rows18 = locators['2018']['Retired and Canceled']['matched_records']
    def values(row):
        return {k:v['value'] for k,v in row['cells'].items()}
    check('2017Atascocita six unique OP LFG units',
          {values(r)['Generator ID'] for r in rows17}=={f'GEN{i}' for i in range(1,7)}
          and all(values(r)['Status']=='OP' and values(r)['Energy Source 1']=='LFG' for r in rows17))
    check('2018same six reported retired February2018; none Operable or Proposed',
          {values(r)['Generator ID'] for r in rows18}=={values(r)['Generator ID'] for r in rows17}
          and all(values(r)['Status']=='RE' and values(r)['Retirement Month']==2 and values(r)['Retirement Year']==2018 for r in rows18)
          and not locators['2018']['Operable']['matched_records']
          and not locators['2018']['Proposed']['matched_records'])
    inv = load(track(ROOT / 'reports/generator_inventory_2026-10-25_001/EVENT_EVIDENCE_TABLE.json'))
    site = next(s for s in inv['sites'] if s['landfill_id']==1479)
    old_units = [r for r in site['reported_unit_rows'] if r['sheet']=='Retired' and r['fuel']=='LFG']
    old_capacity = sum(r['nameplate_MW'] for r in old_units)
    # The historical count is read from the actual previous judgment, not assumed to be all units.
    previous = load(track(OLD / 'eight_sensitivity_002/EIGHT_CASE_JUDGMENTS.json'))['rows']
    oldata = next(r for r in previous if r['landfill_id']==1479)
    cap18 = sum(values(r)['Nameplate Capacity (MW)'] for r in rows18)
    cap17 = sum(values(r)['Nameplate Capacity (MW)'] for r in rows17)
    ata_raw = [r['fields'] for r in records if r['fields']['Landfill ID']==1479 and r['fields']['Project Type Category']=='Electricity']
    delta = {'plant':55526, 'old_2026_subset_units':oldata['listed_retired_LFG_units'],
             'old_subset_generator_ids':[r['id'] for r in old_units], 'old_subset_capacity_MW':old_capacity,
             '2017_annual_units':len(rows17), '2017_annual_capacity_MW':cap17,
             '2018_annual_retired_units':len(rows18), '2018_annual_capacity_MW':cap18,
             'newly_recovered_generator':'GEN5', 'retirement_month':'2018-02',
             'frozen_LMOP_rated_capacity_sum_MW':sum(r['Rated MW Capacity'] for r in ata_raw),
             'capacity_change_from_historical_subset_MW':round(cap18-old_capacity,6),
             'capacity_change_percent':round((cap18/old_capacity-1)*100,6),
             'scope':'Six units observed in2017 and sixRE in2018 at this EIA plant; not proof of all landfill assets/flows or exactLMOPproject-to-unit allocation',
             'downstream_effect':'Count/capacity subset completed; last retirement month, registered pathway, main3+2 completeness and generation values unchanged',
             'historical_output':'eight_sensitivity_002 preserved; its five-unit count is superseded for this bounded plant by this delta only',
             'human_review':'PENDING', 'second_review':'NOT_COMPLETED'}
    write_json(out / 'ATASCOCITA_ASSET_DELTA.json', delta)
    check('Atascocita recovered1.7MW and total10.2MW, no changed date',
          oldata['listed_retired_LFG_units']==5 and abs(cap18-10.2)<1e-9
          and abs(cap17-cap18)<1e-9 and abs(delta['frozen_LMOP_rated_capacity_sum_MW']-cap18)<1e-9)

    # Independent original XML confirmation of GEN5's ID, capacity, RE and retirement fields.
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    gen5 = next(r for r in rows18 if values(r)['Generator ID']=='GEN5')
    with zipfile.ZipFile(g2018) as z:
        book=ET.fromstring(z.read('xl/workbook.xml'))
        rid=next(s for s in book.find('s:sheets',ns) if s.attrib['name']=='Retired and Canceled').attrib['{'+ns['r']+'}id']
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        target=next(s for s in rels if s.attrib['Id']==rid).attrib['Target']
        target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        strings=[''.join(t.itertext()) for t in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        tree=ET.fromstring(z.read(target))
        cells={c.attrib['r']:c for c in tree.findall('.//s:sheetData/s:row/s:c',ns)}
        rawcheck={}
        for k in ['Plant Code','Generator ID','Nameplate Capacity (MW)','Status','Retirement Month','Retirement Year']:
            ref=gen5['cells'][k]['cell']; cell=cells[ref]; v=cell.find('s:v',ns).text
            v=strings[int(v)] if cell.attrib.get('t')=='s' else float(v)
            check('independent XML GEN5 '+k, v==values(gen5)[k])
            rawcheck[k]={'cell':ref,'value':v}
    write_json(out / 'GEN5_XML_CHECK.json', {'member':target,'excel_row':gen5['excel_row_one_based'],'fields':rawcheck})

    # Materialized and remotely read sources have different provenance states.
    for doc in new_evidence['sources']:
        if doc.get('path'):
            p=track(ROOT / doc['path']); doc['sha256']=digest(p)
        else:
            doc['sha256']=None; doc['local_original_saved']=False
    frs=load(PUBLIC / 'wood_frs_eia.json')['Results']['FRSFacility']
    check('currentWood FRS links EIAonly, not automatically LMOP/N5997', len(frs)==1
          and frs[0]['RegistryId']=='110028027891'
          and [(r['ProgramSystemAcronym'],r['ProgramSystemId']) for r in frs[0]['ProgramFacilities']]==[('EIA-860','54549')])
    for path in PUBLIC.glob('DOWNLOAD_ATTEMPT_*.json'):
        track(path)
    for path in PLAN.glob('CONTRIBUTION_*REQUEST*.json'):
        track(path)
    write_json(out / 'NEW_SOURCE_READ_RECORD.json',new_evidence)

    base_notes={}
    for case in coding['cases']:
        rs=[r for r in records if r['fields']['Landfill ID']==case['landfill_id']]
        base_notes[case['landfill_id']]='；'.join(
            f"{r['fields']['Project ID']} {r['fields']['Project Type Category']}/{r['fields']['Current Project Status']} "
            f"开始{str(r['fields']['Project Start Date'])[:10]} 关闭{str(r['fields']['Project Shutdown Date'])[:10]}"
            for r in rs)
    def refpath(ref):
        ref=ref.split('#')[0]
        if ref=='run':
            return None
        if ref.startswith(('eight_sensitivity_002/','publication_review_002/')):
            return OLD / ref
        if ref.endswith('_PUBLIC_EVIDENCE_2026-10-26.json'):
            return ROOT / 'reports/identity_preflight_2026-10-25_001' / ref
        return PLAN / ref

    cells=[]; summaries=[]
    for case in coding['cases']:
        cid=case['landfill_id']; old=next(r for r in previous if r['landfill_id']==cid)
        registry_rows=[r['excel_row'] for r in records if r['fields']['Landfill ID']==cid]
        for cell in case['cells']:
            for ref in cell['refs']:
                if ref.startswith('run#'):
                    assert (out / ref.split('#')[1]).exists(), ref
                else:
                    p=track(refpath(ref))
                    doc=load(p)
                    # Preserve and hash previously downloaded originals behind reused evidence.
                    if isinstance(doc, dict) and doc.get('download_manifest'):
                        manifest=track(ROOT / doc['download_manifest'])
                        for source in load(manifest)['records']:
                            if source.get('sha256'):
                                original=track(ROOT / source['path'])
                                assert digest(original)==source['sha256']
            cells.append({'landfill_id':cid,'name':case['name'],'question':cell['question'],
                          'increment_kind':cell['kind'],'registry_baseline':base_notes[cid],
                          'registry_excel_rows':registry_rows,'evidence_increment':cell['increment'],
                          'evidence_refs':cell['refs'],'baseline_supported_claim_reversed':cell['kind']=='REVERSAL',
                          'human_review':'PENDING','second_review':'NOT_COMPLETED'})
        summaries.append({'landfill_id':cid,'name':case['name'],'registry_already_known':base_notes[cid],
                          **{c['question']:c['increment'] for c in case['cells']},
                          'material_addition':case['material_addition'],
                          'bounded_conversion_evidence':case['bounded_conversion'],
                          'testing_stage_qualification':case['testing_qualification'],
                          'additional_landfill_supply_documented':case['shared_supply_new'],
                          'registry_pathway_reversal_established':False,
                          'main_pre_values':old['main_pre_values'],'main_post_values':old['main_post_values'],
                          'accepted_landfill_numeric_comparison':old['accepted_landfill_numeric_comparison'],
                          'remaining_unknown':case['remaining_unknown'],
                          'registry_excel_rows':registry_rows,'human_review':'PENDING','second_review':'NOT_COMPLETED'})
    check('all32 cells and8 cases remain, no baseline reversal manufactured',len(cells)==32
          and len(summaries)==8 and not any(r['baseline_supported_claim_reversed'] for r in cells))
    check('no numeric eligibility gained by recovering a retirement record',
          sum(r['accepted_landfill_numeric_comparison'] for r in summaries)==0
          and sum(r['main_pre_values']==3 and r['main_post_values']==2 for r in summaries)==1)
    check('review status not inflated',all(r['human_review']=='PENDING' and r['second_review']=='NOT_COMPLETED' for r in cells))
    write_json(out / 'CONTRIBUTION_CELLS.json', {'rubric':coding['rubric'],'rows':cells})
    write_csv(out / 'CONTRIBUTION_CELLS.csv',cells)
    write_json(out / 'EIGHT_INFORMATION_CONTRIBUTION.json', {'rows':summaries})
    write_csv(out / 'EIGHT_INFORMATION_CONTRIBUTION.csv',summaries)
    summary={'cases':8,'common_question_cells':32,'independent_sample_count':None,
             'independence_warning':'Shared systems/source families/development exposure not resolved;8 is case count, not assertion of independence',
             'supported_registry_pathway_reversals_established':0,
             'newly_explained_bounded_conversion_cases':[r['landfill_id'] for r in summaries if r['bounded_conversion_evidence']],
             'testing_stage_qualification_cases':[217], 'shared_supply_increment_cases':[1890],
             'overlap_warning':'These categories overlap and are not four separate independent discoveries',
             'numerical_comparisons_accepted':0,'candidate_plants_with_complete_main_values':1,
             'new_asset_delta':delta,'verdict':coding['verdict'],'decision_boundary':coding['decision_boundary'],
             'checks_passed':len(checks),'independent_human_reviews_completed':0,
             'human_hours_used':None,'original_budget_remaining':None,'original_cap_hours':60,'weekly_human_cap_hours':5,
             'email_sent':False,'new_validation_case_analyzed':False,'sample_or_rules_changed':False}
    write_json(out / 'SUMMARY.json',summary)
    write_json(out / 'CHECKS.json',checks)
    lines=['八例新增信息贡献矩阵 — 2026-10-27',
           '基线：实际Sep2024 LMOP全部33列、34行；包括Direct项目。以下为助手逐项解释，非独立参考真值。',
           '新增到登记之外 ≠ 本轮新发现 ≠ 推翻原判断 ≠ 论文创新。旧资料的重复阅读不计新来源。','']
    for row in summaries:
        lines += [f"{row['landfill_id']} {row['name']}", '登记已知：'+row['registry_already_known']]
        lines += [q+'：'+row[q] for q in coding['questions']]
        lines += ['实质增量：'+row['material_addition'],'仍未知：'+row['remaining_unknown'],
                  f"主要窗口可用年数：前{row['main_pre_values']}/3，后{row['main_post_values']}/2；正式场址比较未接受。",'']
    lines += ['去留判断',coding['verdict'],coding['decision_boundary'],'',
              '两例有直接有界转换解释（1479/1890），一例有测试阶段限制（217）；没有确认同对象同时间的登记路径反转。',
              '0反转不代表数据库绝无错误；未知和待复核不当支持或反驳。原六完整案例门槛未达。',
              '建议：停止按目前主线扩写投稿稿件。以本矩阵和现有报告请Guo评估是否有值得单独立项的实质问题；无新增明确问题前不继续散点补证。',
              '原始数据、旧产物和邮件均保留；未发送。累计人工与余额未知，机器时间不作学生工时。',
              '复现：.\\.venv-research\\Scripts\\python.exe -X utf8 scripts/rng_contribution_matrix.py --run-dir outputs/2026-10-27_rng_linkage/contribution_003',
              '新目录自动拒绝覆盖；标签来自版本化人工编码表，重跑是可追溯导出，不是自动验证解释正确。']
    (out / '八例新增信息与论文去留.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    track(ROOT / 'inputs/public/rng_paper_case_review_2026-10-26/frs_atascocita_eia.json')
    code=track(Path(__file__))
    helper=track(ROOT / 'src/rng/evidence.py')
    before={str(p.relative_to(ROOT)):digest(p) for p in sorted(inputs)}
    shutil.copyfile(code,out / 'CODE_SNAPSHOT.py')
    shutil.copyfile(helper,out / 'EVIDENCE_HELPER_SNAPSHOT.py')
    output_sha={p.name:digest(p) for p in out.iterdir() if p.is_file()}
    write_json(out / 'RUN_RECORD.json',{'command':[sys.executable,*sys.argv],
               'created_utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,
               'platform':platform.platform(),'packages':{p:importlib.metadata.version(p) for p in ['openpyxl','pypdf']},
               'git':'Workspace has no top-level Git repository; exact code/input snapshots and hashes recorded',
               'input_sha256':before,'output_sha256':output_sha,'frozen_seed':20261020,
               'split_logic':'Original8development cases only; no train/test split or new validation outcomes',
               'coding_status':'Retrospective assistant judgments pending independent review; no accuracy/F1 or database error rate',
               'machine_elapsed_seconds':time.perf_counter()-start,'human_hours_used':None,
               'source_download_seconds':'Separate DOWNLOAD_ATTEMPT records; failed HTML not accepted as data',
               'environment_changes':'None','existing_outputs_overwritten':False})
    print(json.dumps({'run':str(out),'cases':8,'checks_passed':len(checks),
                      'new_ata_units':len(rows18),'accepted_comparisons':0,
                      'verdict':'DO_NOT_CONTINUE_CURRENT_MANUSCRIPT_PACKAGING'},ensure_ascii=False))


if __name__=='__main__':
    main()
