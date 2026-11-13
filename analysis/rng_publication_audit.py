"""Audit existing sample use and two development cases; never tune or redraw."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict
import argparse
import csv
import importlib.metadata
import json
import platform
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rng.evidence import load, sha, locate_keyed_records


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf-8')


def table(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    start = time.perf_counter()
    p = argparse.ArgumentParser()
    p.add_argument('--run-dir', required=True)
    args = p.parse_args()
    out = (ROOT / args.run_dir).resolve()
    assert out.is_relative_to(ROOT / 'outputs')
    out.mkdir(parents=True, exist_ok=False)
    inputs = set()

    def read(rel):
        inputs.add(rel)
        return load(ROOT / rel)

    cfg = read('config/rng_pilot.json')
    freeze = read(cfg['inputs']['freeze'])
    eligibility_path = cfg['inputs']['eligibility']
    inputs.add(eligibility_path)
    with (ROOT / eligibility_path).open(encoding='utf-8-sig') as f:
        frame = list(csv.DictReader(f))
    eligible = [r for r in frame if r['status'].startswith('eligible')]
    nonpilot = [r for r in eligible if r['status']=='eligible for frozen candidate draw']
    pilots = [r for r in eligible if r not in nonpilot]
    fixed = freeze['selected_ids']
    reproduced = sorted(random.Random(freeze['random_seed']).sample(sorted(int(r['landfill_id']) for r in nonpilot), 8))
    assert reproduced == fixed and len(eligible)==18 and len(nonpilot)==16 and len(pilots)==2
    assert {int(r['landfill_id']) for r in pilots} == {990, 1625}
    original_source = freeze['input_path'].replace('\\', '/')
    inputs.add(original_source)
    assert sha(ROOT / original_source)==freeze['input_sha256']
    for row in freeze['outputs']:
        rel = row['path'].replace('\\', '/')
        inputs.add(rel)
        assert sha(ROOT / rel)==row['sha256']
    extension = []
    for r in nonpilot:
        if int(r['landfill_id']) not in fixed:
            extension.append(dict(landfill_id=int(r['landfill_id']), name=r['landfill_name'], state=r['state'],
                registry_start=r['snapshot_stated_earliest_RNG_start'],
                exposure='KNOWN_CONVERSION_OUTCOME_CONTEXT_SEC_READING' if r['landfill_id']=='1808' else 'METADATA_READ_HISTORY_OUTCOME_EXPOSURE_NOT_CERTIFIED',
                role='KNOWN_CASE_EXTERNAL_REPLICATION_ONLY' if r['landfill_id']=='1808' else 'PROVISIONAL_VALIDATION_NOT_STARTED',
                new_outcome_analysis_this_run=False))
    assert len(extension)==8
    historical_pilot = next(r for r in frame if r['landfill_id']=='1187')
    project_to_landfill = defaultdict(set)
    alias_to_landfill = defaultdict(set)
    for r in eligible:
        for k in ['RNG_project_ids', 'prior_electricity_project_ids']:
            for pid in r[k].split(';'):
                if pid:
                    project_to_landfill[pid].add(int(r['landfill_id']))
        alias_to_landfill[(r['state'], r['landfill_name'].strip().casefold())].add(int(r['landfill_id']))
    shared_projects = {k:sorted(v) for k,v in project_to_landfill.items() if len(v)>1}
    exact_aliases = {str(k):sorted(v) for k,v in alias_to_landfill.items() if len(v)>1}
    plant_ids = [x['plant_lead'] for x in cfg['cases'].values()]
    history = dict(freeze_time_utc=freeze['run_at_utc'], seed=freeze['random_seed'],
        eligibility_counts=dict(eligible18=len(eligible), eligible_pilots2=len(pilots), nonpilot16=len(nonpilot), fixed8=len(fixed), unselected8=len(extension)),
        fixed_ids=fixed, reproduced_ids=reproduced,
        pilots=dict(eligible_ids=[990,1625], outside_window_id=1187, outside_window_registry_start=historical_pilot['snapshot_stated_earliest_RNG_start']),
        design_use=[
          dict(period='2026-10-20/21 before freeze', cases=[990,1187,1625], use='Pilot trajectories informed feasibility and proposal. Excluded from new random draw; not untouched validation.', source='reports/topic_deepening_2026-10-20/root_methods/COHORT_FREEZE_PLAN.md'),
          dict(period='2026-10-25/26 after freeze', cases=fixed, use='All8 used for registry, catalogue, relation/event and analysis development. Frozen sampling preceded current matching implementation; does not make these8 independent validation.', source='outputs/2026-10-26_rng_linkage/eight_status_006/EIGHT_CASE_STATUS.json'),
          dict(period='2026-10-26 rule runs', cases=[1479,1676], use='Atascocita rule comparison, Mallard2026 restricted catalogue fallback and missing-coordinate/data-quality fixes. Numeric thresholds not changed here. Catalogue vintages differ across cases; disclose development, not pooled same-input accuracy.', source='outputs/2026-10-26_rng_linkage/run_002/RUN_RECORD.json'),
          dict(period='2026-10-26 paper revision', cases=[1808], use='RequestedSEC adjacent text exposed CoastalPlains transition context. It cannot now be called outcome-blind.', source='reports/publication_plan_2026-10-25/PUBLICATION_CASE_READ_RECORD.json')],
        dependencies=dict(shared_project_ids_in_18_eligibility_metadata=shared_projects,
            exact_state_name_duplicates_in_18=exact_aliases,
            repeated_lead_plant_ids_in_original8=[k for k,v in Counter(plant_ids).items() if v>1],
            known_supply_system='Wood Street1890 and Paulson share supply in EGLE2022 source. Paulson not automatically an additional independent case.',
            alias_warning='Atascosita/Atascocita; Houston/Humble; Mallard multipleFRSIDs; differing IDs or absent exact duplicates do not prove independence.',
            unselected_physical_supply_dependence='NOT_YET_AUDITED; precondition to validation, not inferred from exact project IDs'),
        proposed_extension=extension, status='PROPOSAL_ONLY_NO_NEW_CANDIDATE_OUTCOMES_OR_TUNING',
        protocol='reports/publication_plan_2026-10-25/PAPER_EVALUATION_PROTOCOL.json')
    write(out/'SAMPLE_USE_HISTORY.json', history)
    table(out/'VALIDATION_POOL_NOT_STARTED.csv', extension)

    public = 'inputs/public/rng_paper_case_review_2026-10-26/'
    frs = {k:read(public+v)['Results']['FRSFacility'] for k,v in {
      'mallard_lmop':'frs_mallard_lmop.json','mallard_eia':'frs_mallard_eia.json',
      'atascocita_lmop':'frs_atascocita_lmop.json','atascocita_eia':'frs_atascocita_eia.json',
      'mallard_name':'frs_mallard_name.json'}.items()}
    retrievals=[]
    for name in ['DOWNLOAD_ATTEMPT_C001.json','DOWNLOAD_ATTEMPT_C002.json']:
        retrievals += read(public+name)['records']
    assert frs['mallard_eia']==[]
    assert frs['atascocita_lmop']==frs['atascocita_eia']
    ata=frs['atascocita_eia'][0]
    pairs={(r['ProgramSystemAcronym'],r['ProgramSystemId']) for r in ata['ProgramFacilities']}
    assert {('LMOP','1479'),('EIA-860','55526')}.issubset(pairs)
    assert ata['RegistryId']=='110062750465'
    ml=frs['mallard_lmop'][0]
    assert ml['RegistryId']=='110063281032'
    assert not any(r['ProgramSystemAcronym']=='EIA-860' for r in ml['ProgramFacilities'])
    relevant=[r for r in frs['mallard_name'] if 'MALLARD RIDGE' in r['FacilityName']]
    injection=[r for r in relevant if 'INJ POINT' in r['FacilityName']]
    assert len(injection)==2
    official=dict(retrieval_records=retrievals, version='LiveFRS responses at recorded retrievalUTC; per-program refresh/version and historical valid-time not returned',
        documentation='https://www.epa.gov/frs/frs-api; source list includes localHTML. API page updated2026-09-01; not dataset vintage.',
        coordinate_system='FRS Latitude83/Longitude83 NAD83 per officialAPI; no change to existingLMOP/EIA unknown-datum metadata',
        atascocita=dict(registry_id=ata['RegistryId'], admin_co_membership=True, program_records=ata['ProgramFacilities'], valid_from=None, valid_to=None,
            scope='Current administrative correspondence only; exact2018 gas supply/generator membership and all assets not established', flagged_inconsistency='TX-TCEQ ACR record has program name CONROE LANDFILL6 within this returned group; preserve as unresolved metadata, not silently normalise'),
        mallard=dict(registry_id=ml['RegistryId'], lmop_records=frs['mallard_lmop'], eia55013_response_count=0,
            name_query_records=len(frs['mallard_name']), explicitly_relevant_name_records=relevant, injection_point_records=injection,
            admin_lmop_to_eia_co_membership='NOT_RETURNED_IN_BOUNDED_QUERIES',
            limits='Successful empty EIA query is not no generation/no supply. MultipleFRS records and injection points are distinct administrative objects; do not merge them or infer gas routing from name/address.'))
    write(out/'OFFICIAL_LINKS.json', official)
    table(out/'MALLARD_FRS_RECORDS.csv', [dict(registry_id=r['RegistryId'], facility_name=r['FacilityName'],address=r['LocationAddress'],
        program_ids='; '.join(x['ProgramSystemAcronym']+':'+x['ProgramSystemId'] for x in r['ProgramFacilities']),
        status='ADMINISTRATIVE_RECORD_NOT_AUTOMATIC_PHYSICAL_MATCH', valid_time='UNKNOWN') for r in relevant])

    comparisons=[]
    for fid, dirname, official_count in [(1479,'refactored_atascocita_004',1),(1676,'mallard_005',0)]:
        rel=f'outputs/2026-10-26_rng_linkage/{dirname}/CANDIDATE_COMPARISON.csv'
        inputs.add(rel)
        with (ROOT/rel).open(encoding='utf-8-sig') as f:
            candidates=list(csv.DictReader(f))
        for method in ['name','distance','joint']:
            values=[r for r in candidates if r['method']==method]
            comparisons.append(dict(landfill_id=fid, method=method, count=len(values), plant_ids=';'.join(r['plant_code'] for r in values),
                input_scope=cfg['cases'][str(fid)]['candidate_catalogue'], relation_output='CANDIDATE_ONLY_NOT_GAS_SUPPLY', historical_source=rel))
        comparisons.append(dict(landfill_id=fid,method='officialFRS',count=official_count,plant_ids='55526' if official_count else '',
            input_scope='LiveFRS_program_links_not_same_catalogue',relation_output='CURRENT_ADMIN_CO_MEMBERSHIP' if official_count else 'SUCCESSFUL_QUERY_NO_EXPLICIT_EIA_LINK',historical_source=public))
    table(out/'CANDIDATE_METHOD_COMPARISON.csv', comparisons)

    sec=read('reports/publication_plan_2026-10-25/PUBLICATION_CASE_READ_RECORD.json')
    read('reports/publication_plan_2026-10-25/PAPER_EVALUATION_PROTOCOL.json')
    read('reports/publication_plan_2026-10-25/NEIGHBOR_STUDIES.json')
    mallard=read('reports/identity_preflight_2026-10-25_001/MALLARD_PUBLIC_EVIDENCE_2026-10-26.json')
    coverage=read('outputs/2026-10-26_rng_linkage/mallard_source_audit_001/EIA_COVERAGE.json')
    # Re-open raw inputs by keys, not the previous4223 row locator.
    inv=cfg['inputs']['inventory_source']
    inv_source=read(inv)
    invpath='inputs/public/generator_inventory_2026-10-25/september_generator2026.xlsx'
    inputs.add(invpath)
    gen1=locate_keyed_records(ROOT/invpath,'Retired',{'Plant ID':55013,'Generator ID':'GEN1'},
        ['Plant ID','Generator ID','Operating Month','Operating Year','Retirement Month','Retirement Year'])
    assert gen1['matched_count']==1 and gen1['matched_records'][0]['excel_row_one_based']==4223
    lmop=locate_keyed_records(ROOT/original_source,'LMOP Database',{'Landfill ID':1676},
        ['Landfill ID','Project ID','Project Start Date','Project Shutdown Date','Project Type Category','Landfill Name'])
    assert lmop['matched_count']==2
    write(out/'MALLARD_ORIGINAL_RECHECK.json',dict(gen1=gen1, lmop=lmop, human_review='PENDING'))
    generation=read(cfg['inputs']['generation'])['response']['data']
    mallard_rows=[r for r in generation if str(r['plantCode'])=='55013']
    assert len(mallard_rows)==0
    write(out/'MALLARD_COVERAGE_DELTA.json',dict(current_extract_rows=len(mallard_rows),years=list(range(2015,2025)),
        status='CURRENT_FILTERED_EXTRACT_MISSING_NOT_ZERO', full_annual_source_status=coverage['annual_full_eia923_originals']['status'],
        new_generation_input=False, numerical_results_changed=False, prior_coverage=coverage))
    specifications=[
      ('A1',1479,'official administrative co-membership','LMOP1479 and EIA55526 explicitly co-listed','SUPPORTED','FRS current retrieval','OFFICIAL_LINKS.json#/atascocita'),
      ('A2',1479,'project operation transition','Issuer reports named former electricity project converted to commercial RNG inMay2018','SUPPORTED','Retrospective2018 inFY2020 filing','PUBLICATION_CASE_READ_RECORD.json#/sec'),
      ('A3',1479,'complete asset coverage','All landfill generating assets ceased in2018','UNDETERMINED','2018 all-site','Retired identified units plus issuer project do not enumerate all site assets'),
      ('A4',1479,'generation measurement','Missing2019/2020 LFG rows mean measuredzero','UNDETERMINED','2019-2020','S041 missing rows are not observations'),
      ('M1',1676,'official administrative co-membership','LMOP1676 is inFRS110063281032','SUPPORTED','FRS current retrieval','OFFICIAL_LINKS.json#/mallard'),
      ('M2',1676,'official administrative co-membership','DownloadedFRS LMOP1676 result explicitly listsEIA55013','REFUTED','Only this retrieved response','ProgramFacilities list has noEIA-860 entry; no physical non-link inference'),
      ('M3',1676,'complete asset coverage','All similarly namedFRS records represent one complete physical asset','UNDETERMINED','Across live administrative records','Multiple registry and injection-point objects are not merged'),
      ('M4',1676,'RNG operation','Supplier documents namedRNG production/injection by2023-04-03','SUPPORTED','As of2023-04-03','ExistingMallard sourceM04; one supplier group'),
      ('M5',1676,'generation measurement','Current55013 missing rows prove no electricity anywhere at the landfill','UNDETERMINED','2015-2024','Full annual generation coverage and all assets unresolved'),
      ('M6',1676,'commercial event date','LMOP2022-04-30 is independently confirmed exact first commercial day','UNDETERMINED','First commercial start','Module sinceMarch2022/January acceptance/asof2023 evidence are different stages')]
    ledger=[dict(id=i,landfill_id=fid,relation_type=kind,claim=claim,reference_state=state,time_scope=t,source_or_limit=s,
        valid_from=None, valid_to=None,automatic_extraction='COMPLETED_WHERE_LOCAL_SOURCE_AVAILABLE',assistant_source_read='COMPLETED_FOR_STATED_SCOPE',
        human_review='PENDING',second_review='NOT_COMPLETED',reference_level='PROVISIONAL_EVIDENCE_ASSESSMENT_NOT_GOLD_STANDARD')
        for i,fid,kind,claim,state,t,s in specifications]
    source_refs={
      'A1':[dict(path=public+'frs_atascocita_eia.json',location='Results.FRSFacility[0].RegistryId / ProgramFacilities',object='LMOP1479 / EIA-86055526')],
      'A2':[dict(url=sec['sec']['url'],location='Item1 printed10-11 and17',path='reports/publication_plan_2026-10-25/PUBLICATION_CASE_READ_RECORD.json',object='Issuer named project',access='WEB_READER_ONLY_LOCAL403')],
      'A3':[dict(url=sec['sec']['url'],location='Item1 printed17, project scope',object='Former merchant project'),dict(path=invpath,location='Retired Excel2627-2631',object='Plant55526 GEN1/2/3/4/6; not all site assets')],
      'A4':[dict(path=cfg['inputs']['generation'],location='response.data plantCode55526, no2019/2020 LFG/ALL rows',object='Filtered plant records, not observedzero')],
      'M1':[dict(path=public+'frs_mallard_lmop.json',location='Results.FRSFacility[0].RegistryId / ProgramFacilities',object='LMOP1676')],
      'M2':[dict(path=public+'frs_mallard_lmop.json',location='Results.FRSFacility[0].ProgramFacilities entire returned list',object='Explicit administrative entries only')],
      'M3':[dict(path=public+'frs_mallard_name.json',location='Results.FRSFacility, names containing MALLARD RIDGE; retain separateIDs',object='Administrative records / two injection points')],
      'M4':[dict(path='inputs/public/mallard_evidence_2026-10-26/waga_acceptance.html',location='Existing read record claimM04, article blocks3-4',object='NamedAirLiquide RNG facility; supplier groupWaga')],
      'M5':[dict(path=cfg['inputs']['generation'],location='response.data plantCode55013 absent',object='Current filtered extract'),dict(path='outputs/2026-10-26_rng_linkage/mallard_source_audit_001/EIA_COVERAGE.json',location='annual_full_eia923_originals',object='Coverage not confirmed')],
      'M6':[dict(path=original_source,location='LMOP Database Excel3325, ProjectStartDate',object='RNG registration'),dict(path='reports/identity_preflight_2026-10-25_001/MALLARD_PUBLIC_EVIDENCE_2026-10-26.json',location='claimsM03/M04 and eventsME1-3',object='Different operating stages')]
    }
    for row in ledger:
        row['evidence_records']=source_refs[row['id']]
        for ref in row['evidence_records']:
            if ref.get('path'):
                inputs.add(ref['path'])
                ref['sha256']=sha(ROOT/ref['path'])
    write(out/'CLAIM_REFERENCE_LEDGER.json',dict(scope='10 targeted claims in2 development cases, not all eight or a representative performance sample',rows=ledger))
    table(out/'CLAIM_REFERENCE_LEDGER.csv', ledger)
    write(out/'CASE_RELATION_EVENT_DELTAS.json',dict(
      relations=[dict(from_id='LMOP:1479',to_id='EIA-860:55526',relation_type='OFFICIAL_ADMINISTRATIVE_CO_MEMBERSHIP',registry_id=ata['RegistryId'],
          valid_from=None,valid_to=None,as_of='See download retrievalUTC, not2018',reference_state='SUPPORTED',evidence_claim='A1',human_review='PENDING',physical_supply_confirmed=False),
        dict(from_id='LMOP:1676',to_id='FRS:110063281032',relation_type='OFFICIAL_ADMINISTRATIVE_CO_MEMBERSHIP',valid_from=None,valid_to=None,
          as_of='See download retrievalUTC',reference_state='SUPPORTED',evidence_claim='M1',human_review='PENDING'),
        dict(from_id='LMOP:1676',to_id='EIA:55013',relation_type='GAS_SUPPLY',valid_from=None,valid_to=None,as_of=None,
          reference_state='UNDETERMINED',evidence_claim='M2/M3/M5',human_review='PENDING',note='Not refuted by absent official link')],
      events=[dict(object='Issuer named Atascocita project',event_type='GAS_SUPPLY_AGREEMENT_UPDATED',date_low='2016-10-01',date_high='2016-10-31',precision='month',
          evidence_claim='SEC_A1',source_group='MONTAUK_FY2020_ONE_FILING',does_not_establish='Actual continuous flow or EIA generator membership'),
        dict(object='Issuer named Atascocita RNG project',event_type='REPORTED_COMMERCIAL_OPERATION',date_low='2018-05-01',date_high='2018-05-31',precision='month',
          evidence_claim='SEC_A1/SEC_A2',source_group='MONTAUK_FY2020_ONE_FILING',can_change_original_inclusion=False)],
      existing_mallard_events=mallard['events'], numerical_results_changed=False,human_review='PENDING'))
    counts=Counter(x['reference_state'] for x in ledger)
    write(out/'EVALUATION_SUMMARY.json', dict(claims=len(ledger),cases=2,state_counts=dict(counts),human_reviewed_claims=0,second_reviewed_claims=0,
        status='DESCRIPTIVE_PROVISIONAL_COUNTS_NOT_ACCURACY',refuted_claim_scope='M2 refers only to explicit fields in one official response, not physical gas supply',
        unchanged=dict(original8=True,raw_lmop=True,candidate_thresholds=True,accepted_landfill_numeric_comparisons=0),
        actual_human_hours=None, cumulative_human_hours=None, remaining_human_hours=None))
    old_status=read('outputs/2026-10-26_rng_linkage/eight_status_006/EIGHT_CASE_STATUS.json')
    rows=old_status['rows']
    for r in rows:
        if r['landfill_id']==1479:
            r['paper_revision_delta']='FRS explicit1479/55526 co-membership110062750465; sameFY2020 filing reread adds contract/event roles and partial-gas boundary. No all-asset acceptance.'
        elif r['landfill_id']==1676:
            r['paper_revision_delta']='FRS LMOP1676 found but no explicit55013 link;7MallardRidge administrative records including2injectionpoints retained separately. OriginalGEN1/LMOP rechecked. No zero imputation.'
        else:
            r['paper_revision_delta']='No new case evidence this batch; prior unresolved status retained'
    write(out/'EIGHT_CASE_STATUS_PAPER_DELTA.json',dict(scope=old_status['scope'],rows=rows))
    review = 'Human review pending. Do not mark these verified on the user\'s behalf.\n\n'
    review += '1. Atascocita FRS original: '+str((ROOT/(public+'frs_atascocita_eia.json')).resolve())+'\nResults.FRSFacility[0].RegistryId and ProgramFacilities(EIA-86055526,LMOP1479). Also inspect CONROE LANDFILL6 label. Current correspondence is not2018 supply.\n\n'
    review += '2. SEC original webpage: '+sec['sec']['url']+'\nItem1 printed10-11 conversion case and printed17 Atascocita. Distinguish contract, commercial operation and former project using only part of site gas. Local downloads403; accessible web reader is not a saved PDF.\n\n'
    review += '3. Mallard raw workbook: '+str((ROOT/invpath).resolve())+'\nRetired header3; locatePlant55013+GEN1: Excel4223, operatingS/T versusretirementU/V. FrozenLMOP raw LMOP Database LandfillID1676 rows3324/3325. These originals do not prove all-site post2015zero.\n'
    (out/'HUMAN_REVIEW_ENTRIES.txt').write_text(review,encoding='utf-8')
    for rel in ['reports/topic_deepening_2026-10-20/root_methods/COHORT_FREEZE_PLAN.md','reports/topic_deepening_2026-10-20/root_methods/freeze_candidate_cohort.py',
        'reports/identity_preflight_2026-10-25_001/WOOD_PUBLIC_EVIDENCE_2026-10-26.json']:
        inputs.add(rel)
    record=dict(utc=datetime.now(timezone.utc).isoformat(),command=[sys.executable,*sys.argv],python=sys.version,platform=platform.platform(),
        packages={k:importlib.metadata.version(k) for k in ['openpyxl','pandas']},input_sha256={rel:sha(ROOT/rel) for rel in sorted(inputs)},
        code_sha256=sha(Path(__file__)),git_state='No top-levelGit; original code bytes copied',random_seed=freeze['random_seed'],
        split='No model fitting. Existing8 development cases; proposed extension not executed.',
        code_snapshot='CODE_SNAPSHOT.py',network_calls=0,paid_cost=0,elapsed_machine_wall_seconds=time.perf_counter()-start,
        human_hours_used=None,cumulative_human_hours=None,remaining_human_hours=None,
        source_reading='SEC web-reader observations manually recorded separately; failed binary downloads retained, no local original claimed',
        checks=['Frozen source and sample hashes unchanged','18=2+16; fixed draw reproduced exactly','8 separate proposed extension IDs;1808 exposure disclosed',
          'FRS dual Atascocita program queries identical with both IDs','Mallard EIA query success-empty not physical negative',
          'Two injection point administrative records retained','RawGEN1 andLMOP found by keys/header','Mallard generation missing notzero',
          'Provisional reference counts sum to10; human0/second0; no accuracy estimate'],output_paths=[str(x.relative_to(ROOT)) for x in out.iterdir()])
    (out/'CODE_SNAPSHOT.py').write_bytes(Path(__file__).read_bytes())
    write(out/'RUN_RECORD.json',record)
    print(json.dumps(dict(run=str(out),eligible=len(eligible),fixed=fixed,extension=[x['landfill_id'] for x in extension],
        reference_counts=dict(counts),mallard_relevant_records=len(relevant),machine_seconds=record['elapsed_machine_wall_seconds']),ensure_ascii=False))


if __name__=='__main__':
    main()
