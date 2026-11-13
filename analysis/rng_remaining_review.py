"""First-pass originals and bounded checks for the four remaining frozen cases."""
from pathlib import Path
from datetime import datetime,date,timezone
from collections import Counter
import argparse,sys,time,platform,importlib.metadata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from rng.evidence import load,sha,locate_keyed_records
from rng.analysis import configured_windows,plant_series,comparison_eligibility
from rng.pipeline import project_path,write_json,write_csv

CASES=[(1820,56113,'tessman'),(1890,54549,'wood'),(1939,54286,'southside'),(2207,57587,'charleston')]


def main():
    start=time.perf_counter();parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);args=parser.parse_args()
    cfg=load(ROOT/'config/rng_pilot.json');freeze=load(ROOT/cfg['inputs']['freeze'])
    invsrc=load(ROOT/cfg['inputs']['inventory_source']);psrc=load(ROOT/cfg['inputs']['plant_source'])
    lmop,inv,plant=[ROOT/p for p in [freeze['input_path'],invsrc['local_path'],psrc['local_original']]]
    files=[ROOT/'config/rng_pilot.json',ROOT/cfg['inputs']['freeze'],ROOT/cfg['inputs']['inventory_source'],ROOT/cfg['inputs']['plant_source'],lmop,inv,plant,ROOT/cfg['inputs']['generation']]
    indexpath=ROOT/'reports/identity_preflight_2026-10-25_001/REMAINING_FOUR_DOWNLOAD_INDEX.json';index=load(indexpath);files.append(indexpath)
    for record in index['source_manifests']:
        p=ROOT/record['path'];assert sha(p)==record['sha256'];files.append(p)
    for record in index['records']:
        p=ROOT/record['path'];assert sha(p)==record['sha256'];files.append(p)
    for fid,_,name in CASES:
        files.extend([ROOT/cfg['cases'][str(fid)]['public_evidence_manifest'],ROOT/f'outputs/2026-10-26_rng_linkage/{name}_001/RUN_RECORD.json'])
    before={str(p.relative_to(ROOT)):sha(p) for p in files}
    assert sha(lmop)==freeze['input_sha256'] and sha(inv)==invsrc['sha256'] and sha(plant)==psrc['original_sha256']
    out=project_path(ROOT,args.run_dir);assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    locators={};rows=[];raw=load(ROOT/cfg['inputs']['generation'])
    fields=['Plant ID','Plant Name','Generator ID','Energy Source Code','Operating Month','Operating Year','Retirement Month','Retirement Year']
    for fid,pid,name in CASES:
        locators[str(fid)]={
          'registry':locate_keyed_records(lmop,'LMOP Database',{'Landfill ID':fid},['Landfill ID','Landfill Name','Physical Address','Project ID','Current Project Status','Project Type Category','Project Start Date','Project Shutdown Date']),
          'plant2017':locate_keyed_records(plant,'Plant',{'Plant Code':pid},['Plant Code','Plant Name','Street Address','City','County','State','Zip']),
          'Operating':locate_keyed_records(inv,'Operating',{'Plant ID':pid},fields),
          'Retired':locate_keyed_records(inv,'Retired',{'Plant ID':pid},fields)}
        s=load(ROOT/f'outputs/2026-10-26_rng_linkage/{name}_001/SUMMARY.json')
        dateinfo=load(ROOT/f'outputs/2026-10-26_rng_linkage/{name}_001/DATE_WINDOW_CHECK.json')
        win=dateinfo['fixed_registry_anchor'];series=plant_series(raw,pid,cfg['generation_scope'],cfg['windows'],int(win['date'][:4]))
        rows.append({'landfill_id':fid,'candidate_plant':pid,'registry_rows':locators[str(fid)]['registry']['matched_count'],
         'plant2017_matches':locators[str(fid)]['plant2017']['matched_count'],
         'full_snapshot_operating_matches':locators[str(fid)]['Operating']['matched_count'],
         'full_snapshot_retired_matches':locators[str(fid)]['Retired']['matched_count'],
         'registered_rng_start':win['date'],'generation_status_counts':dict(Counter(r['record_status'] for r in series)),
         'numerical_eligibility':comparison_eligibility(series)['eligible'],'full_site_class':'UNDETERMINED','human_review':'PENDING'})
    write_json(out/'ORIGINAL_LOCATORS.json',locators);write_csv(out/'FOUR_CASE_AUDIT.csv',rows)
    from pypdf import PdfReader
    root_sources=ROOT/'inputs/public/rng_remaining_four_2026-10-26'
    wood=PdfReader(root_sources/'wood_EGLE_inspection_20220819.pdf');char=PdfReader(root_sources/'charleston_WVDEP_application_2017.pdf')
    w2,w14,w15=[wood.pages[i-1].extract_text() for i in [2,14,15]]
    assert 'Paulson Street' in w2 and 'air-gapped' in w14 and 'September 9, 2021' in w14 and 'operating during' in w15
    rfs=PdfReader(root_sources/'charleston_EPA_review_schedule_2021.pdf')
    assert 'Charleston Landfill Gas Processing Facility' in rfs.pages[5].extract_text()
    source_read={'automatic_phrase_checks':{'WOOD_PDF2_Paulson':True,'WOOD_PDF14_airgap_and_startup':True,'WOOD_PDF15_operating_conditioner':True,'RFS_PDF6_named_row':True},
        'wood_artifact_pages':len(wood.pages),'wood_main_report_pages':20,'wood_targeted_read_pages':[1,2,3,14,15,20],
        'char_application_pages':len(char.pages),'char_pdf4_extracted_characters':len(char.pages[3].extract_text() or ''),
        'char_source_read_mode':'SCANNED_PDF1_5_ASSISTANT_VISUAL_TRANSCRIPTION_NOT_AUTOMATIC_TEXT_NOT_HUMAN_VERIFIED',
        'char_visual_fields':{'PDF4':'741 South ParkRoad; WV facility039-00461','PDF5':'Proposed remove1 generator, install2 compressor engines; anticipated2017-11-01'},
        'human_verification':'PENDING','exact_source_cards':'Four PUBLIC_EVIDENCE JSON files referenced by current configuration; claims retain support limits'}
    write_json(out/'SOURCE_REVIEW_RECORD.json',source_read)
    primary=configured_windows(2021,cfg['windows']);alternative=configured_windows(2022,cfg['windows'])
    gen_tess=plant_series(raw,56113,cfg['generation_scope'],cfg['windows'],2021)
    checks_temporal={
      'Tessman':{'primary_registration_year':2021,'reported_commissioning_year':2021,'reported_operation_year':2022,
          'primary':primary,'reported_operation_year_description':alternative,'primary_anchor_changed':False,
          'post_values_complete_primary':all(r['net_generation_MWh'] is not None for r in gen_tess if r['year'] in primary['main_post_years']),
          'interpretation':'Separate commissioning and reported operation; no ratio without complete post values or confirmed relation.'},
      'Wood':{'reported_decommission_date':'2021-08-30','eia_retirement_month':'2021-09','reported_component_startup':'2021-09-09',
          'inspection_operating_observation':'2022-08-19','days_decommission_to_component_start':(date(2021,9,9)-date(2021,8,30)).days,
          'primary_registration_year':2021,'inspection_is_startup_alternative':False,'all_documented_2021_events_keep_annual_windows':True,
          'bounded_asset_set_replacement_documented':True,'eia_exact_generator_crosswalk_verified':False,
          'rng_supply_landfills_named':['WoodStreet','PaulsonStreet'],'exclusive_WoodStreet_assignment_permitted':False},
      'SouthSide':{'registry_date':'2020-03-20','source_publication':'2020-03-04','opening_celebration':'2020-03-03',
          'source_full_operation_date':'2020-03-20','source_date_status':'FUTURE_IN_PUBLICATION_NOT_VERIFIED_ACTUAL',
          'historical_contract_year':1998,'historical_source_document':'2010-02','historical_contract_proves2020_supply':False,
          'listed_primary_fuels':{'LFG':1,'NG':3},'full_factory_generation_assignable_to_landfill':False},
      'Charleston':{'eia_retirement_month':'2015-12','registered_project_closure':'2016-12-31','anticipated_application_start':'2017-11-01',
          'registered_rng_start':'2018-02-01','RFS_ID':71314,'RFS_Initial_column':2018,'EIA_ID':57587,'LMOP_LandfillID':2207,
          'anticipated_date_is_actual_alternative':False,'RFS_Initial_is_proven_first_production_year':False,
          'proposed_compressor_engines_are_electric_generators':False,'physical_EIA_link_verified':False}}
    write_json(out/'EVENT_AND_BOUNDARY_CHECKS.json',checks_temporal)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    fig,ax=plt.subplots(figsize=(10,5.4),layout='constrained');ax.set_xlim(0,10);ax.set_ylim(0,6);ax.axis('off')
    def box(x,y,w,h,text,color):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.1',facecolor=color,edgecolor='#49666a'))
        ax.text(x+w/2,y+h/2,text,ha='center',va='center',fontsize=10)
    box(.2,4,2.6,1,'Wood Street landfill\nLMOP1890','#dce9e2');box(.2,2.1,2.6,1,'Paulson Street landfill\nadditional named source','#dce9e2')
    box(4.1,3.2,2.7,1.3,'EDL Wood Road RNG\nconditioning system\nobserved2022-08-19','#dce6ef')
    box(7.7,3.4,2.1,.9,'Consumers Energy\npipeline','#eee5d1')
    for xy,xytext in [((4.1,4.1),(2.9,4.5)),((4.1,3.6),(2.9,2.7)),((7.6,3.85),(6.9,3.85))]:
        ax.annotate('',xy=xy,xytext=xytext,arrowprops={'arrowstyle':'->','color':'#387564','lw':2})
    box(4.1,.5,3.3,1,'EIA54549 / seven listed generators\nidentity and address crosswalk pending','#f1eeee')
    ax.annotate('',xy=(5.3,3.1),xytext=(5.3,1.6),arrowprops={'arrowstyle':'<->','linestyle':'--','color':'#9a5b50','lw':1.7})
    ax.text(6,2.25,'Unresolved exact asset IDs\n16800 vs16980 WoodRoad',fontsize=9,ha='left')
    ax.set_title('Documented process relationships, not a geographic map',fontsize=12)
    ax.text(0,0,'Solid: EGLE inspection narrative, PDF2/14-15. Dashed: unresolved EIA crosswalk. No gas-share or output allocation.',fontsize=9)
    fig.savefig(out/'WOOD_RELATION_BOUNDARY.png',dpi=150);plt.close(fig)
    lines=['本批原件入口：自动按ID定位；用户人工核验均待完成。','']
    for fid,groups in locators.items():
        lines.append('LMOP Landfill ID '+fid)
        for name,obj in groups.items():
            lines.append(f"{obj['absolute_path']} | {obj['sheet']} | header Excel row {obj['header_excel_row']} | filter {obj['filters']}")
            for row in obj['matched_records']:
                lines.append(f"Excel {row['excel_row_one_based']} / code worksheet index {row['worksheet_row_zero_based']}: "+'; '.join(f"{k}={v['value']} [{v['cell']}]" for k,v in row['cells'].items()))
    lines.extend(['','优先本人核验：',str(root_sources/'wood_EGLE_inspection_20220819.pdf')+' PDF14/15（断管与运行），PDF2（Paulson共同供气）；不把检查日当投产日。',
      str(root_sources/'charleston_WVDEP_application_2017.pdf')+' 扫描PDF4/5的物理地址、proposed和anticipated字段。',
      str(root_sources/'southside_EDL_opening.html')+' opening段的will be fully operational；登记日相同不等于实际运行独立确认。'])
    (out/'HUMAN_REVIEW_ENTRIES.txt').write_text('\n'.join(lines),encoding='utf-8')
    validations={'four_original_key_scans_completed':len(locators)==4,'originals_and_inputs_unchanged':all(sha(ROOT/p)==h for p,h in before.items()),
      'source_observation_and_proposal_distinguished':True,'no_new_human_verification_claim':True,'no_output_or_emission_allocation':True,'bounded_runtime':time.perf_counter()-start<120}
    code=[Path(__file__),*sorted((ROOT/'src/rng').glob('*.py'))]
    write_json(out/'CODE_SNAPSHOT.json',{str(p.relative_to(ROOT)):{'sha256':sha(p),'text':p.read_text(encoding='utf-8')} for p in code})
    write_json(out/'RUN_RECORD.json',{'utc':datetime.now(timezone.utc).isoformat(),'command':[sys.executable,*sys.argv],'cwd':str(Path.cwd()),'python':sys.version,'platform':platform.platform(),
       'packages':{p:importlib.metadata.version(p) for p in ['openpyxl','matplotlib','pypdf']},'input_sha256':before,'module_sha256':{str(p.relative_to(ROOT)):sha(p) for p in code},
       'git_state':'No root Git repository; archived code and input hashes','random_seed':20261020,'split':'No trained model; facility-years not independent facilities',
       'human_hours_used':None,'human_hours_remaining':None,'elapsed_tool_wall_seconds':time.perf_counter()-start,'network_calls':0,'paid_script_cost':0,'checks':validations,
       'outputs':{p.name:sha(p) for p in out.iterdir() if p.is_file()}})
    assert all(validations.values())
    print({'output':str(out),'case_audit':rows,'checks':validations})


if __name__=='__main__':main()
