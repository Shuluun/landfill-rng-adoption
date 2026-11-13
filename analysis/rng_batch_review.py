"""Located first-pass review of fixed Monterey/Skyline cases and plant-only windows."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import importlib.metadata
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from rng.evidence import load, sha, locate_keyed_records
from rng.analysis import plant_series, configured_windows
from rng.pipeline import write_json, write_csv, project_path


def plant_window(series, year, config, event):
    """An EIA-plant description; does not assert a landfill link or adoption date."""
    win = configured_windows(year, config)
    indexed = {r['year']: r for r in series}
    pre = [indexed.get(y, {}).get('net_generation_MWh') for y in win['background_years']]
    post = [indexed.get(y, {}).get('net_generation_MWh') for y in win['main_post_years']]
    complete = all(v is not None for v in pre + post)
    pre_mean = sum(pre)/3 if complete else None
    post_mean = sum(post)/2 if complete else None
    ratio = post_mean/pre_mean if complete and pre_mean > 0 else None
    return {'event_definition': event, 'anchor_year_for_description_only': year, **win,
            'pre_values_MWh': pre, 'post_values_MWh': post, 'complete_values': complete,
            'pre_mean_MWh': pre_mean, 'post_mean_MWh': post_mean, 'post_pre_ratio': ratio,
            'percent_difference': (ratio-1)*100 if ratio is not None else None,
            'scope': 'EIA_PLANT_ONLY_NOT_AN_ACCEPTED_LANDFILL_ADOPTION_COMPARISON',
            'landfill_assigned_MWh': None,
            'interpretation': 'Different event definitions compare different calendar periods. Not equivalent treatment-date estimates, a causal effect or stable commercial adoption.'}


def main():
    started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--monterey-run', default='outputs/2026-10-26_rng_linkage/monterey_002')
    parser.add_argument('--skyline-run', default='outputs/2026-10-26_rng_linkage/skyline_002')
    args = parser.parse_args()
    cfg = load(ROOT/'config/rng_pilot.json')
    freeze = load(ROOT/cfg['inputs']['freeze'])
    invsrc = load(ROOT/cfg['inputs']['inventory_source'])
    plantsrc = load(ROOT/cfg['inputs']['plant_source'])
    raw_paths = [ROOT/freeze['input_path'], ROOT/invsrc['local_path'], ROOT/plantsrc['local_original']]
    generation_path = ROOT/cfg['inputs']['generation']
    download_path = ROOT/'inputs/public/rng_case_evidence_2026-10-26/DOWNLOAD_ATTEMPT_002.json'
    downloads = load(download_path)['records']
    originals = {r['id']:r for r in downloads if r.get('sha256')}
    inputs = [ROOT/'config/rng_pilot.json', ROOT/cfg['inputs']['freeze'], ROOT/cfg['inputs']['inventory_source'],
              ROOT/cfg['inputs']['plant_source'], *raw_paths, generation_path, download_path]
    for fid,arg in [(217,args.monterey_run),(1456,args.skyline_run)]:
        directory=project_path(ROOT,arg)
        inputs.extend(directory/f for f in ['RUN_RECORD.json','SUMMARY.json','CASE_RELATIONS.json','OPERATING_EVENTS.json','PLANT_GENERATION.csv'])
        inputs.append(ROOT/cfg['cases'][str(fid)]['public_evidence_manifest'])
    inputs.extend(ROOT/r['path'] for r in originals.values())
    before = {str(p.relative_to(ROOT)):sha(p) for p in inputs}
    assert sha(generation_path)==cfg['generation_sha256']
    assert sha(raw_paths[0])==freeze['input_sha256'] and sha(raw_paths[1])==invsrc['sha256']
    assert all(sha(ROOT/r['path'])==r['sha256'] for r in originals.values())
    out=project_path(ROOT,args.run_dir)
    assert out.is_relative_to(ROOT/'outputs')
    out.mkdir(parents=True,exist_ok=False)
    locators={}
    fields=['Plant ID','Plant Name','Generator ID','Status','Energy Source Code','Operating Month','Operating Year','Retirement Month','Retirement Year']
    for fid,pid in [(217,10748),(1456,56528)]:
        locators[str(fid)]={
            'registry':locate_keyed_records(raw_paths[0],'LMOP Database',{'Landfill ID':fid},['Landfill ID','Landfill Name','Physical Address','City','County','State','Zip Code','Project ID','Current Project Status','Project Type Category','Project Start Date','Project Shutdown Date']),
            'plant2017':locate_keyed_records(raw_paths[2],'Plant',{'Plant Code':pid},['Plant Code','Plant Name','Street Address','City','County','State','Zip','Utility Name']),
            'Operating':locate_keyed_records(raw_paths[1],'Operating',{'Plant ID':pid},fields),
            'Retired':locate_keyed_records(raw_paths[1],'Retired',{'Plant ID':pid},fields)}
    assert [locators['217'][k]['matched_count'] for k in ['registry','plant2017','Operating','Retired']]==[8,1,4,6]
    assert [locators['1456'][k]['matched_count'] for k in ['registry','plant2017','Operating','Retired']]==[2,1,0,4]
    write_json(out/'ORIGINAL_LOCATORS.json',locators)
    from pypdf import PdfReader
    cec=PdfReader(ROOT/originals['MON_CEC_REPORT']['path'])
    wm=PdfReader(ROOT/originals['SKY_WM_PRESENTATION']['path'])
    cec20=cec.pages[19].extract_text(); cec27=cec.pages[26].extract_text(); cec9=cec.pages[8].extract_text()
    assert all(x in cec20 for x in ['April 8, 2022','June 29, 2022','temporarily shut down'])
    assert 'solely utilized' in cec9 and 'commence regular operation' in cec27
    assert 'January 2020' in wm.pages[6].extract_text() and 'Atmos' in wm.pages[6].extract_text()
    cards={'read_scope':'Targeted source reading, not all pages; user human review remains pending',
        'MON_CEC_REPORT':{'source':originals['MON_CEC_REPORT'],'pages_read':[1,2,5,8,9,10,11,19,20,21,22,23,27,28],
            'key_pages':[{'pdf_page':20,'printed_page':'17','claim':'April2022 part-time testing/data, temporary shutdown'},
                         {'pdf_page':27,'printed_page':'24','claim':'Regular fuel service still conditional'},
                         {'pdf_page':9,'printed_page':'6','claim':'Initial LFG alone versus future AD/WWTP'}],
            'publication_label_conflict':'Portal/file2024, cover June2023/CEC-600-2022-008, suggested citationCEC-600-2023-008; actual SHA and contractARV-17-036 retained'},
        'SKY_WM_PRESENTATION':{'source':originals['SKY_WM_PRESENTATION'],'pages_read':[1,7],
            'key_pages':[{'pdf_page':7,'printed_slide':'7','claim':'January2020 operation and Atmos injection reported by WM'}],
            'organisation_group':'WM_ONE_OPERATOR'},
        'failed_original_fetches':[r for r in downloads if not r.get('sha256')],
        'failed_fetch_interpretation':'ReGen factsheet and page HTTP403; web text read is not a downloaded original or a critical local source. No claim based solely on search snippets.',
        'human_verification':'PENDING'}
    write_json(out/'SOURCE_REVIEW_RECORD.json',cards)
    raw=load(generation_path)
    monterey=plant_series(raw,10748,cfg['generation_scope'],cfg['windows'],2020)
    skyline=plant_series(raw,56528,cfg['generation_scope'],cfg['windows'],2020)
    scenarios=[plant_window(monterey,2020,cfg['windows'],'FROZEN_REGISTRATION_YEAR'),
               plant_window(monterey,2022,cfg['windows'],'DOCUMENTED_INTERMITTENT_TESTING_YEAR_NOT_COMMERCIAL_START')]
    write_json(out/'MONTEREY_PLANT_WINDOW_COMPARISON.json',{'plant_code':10748,'scenarios':scenarios,
        'primary_anchor_changed':False,'is_primary_landfill_numeric_comparison':False,
        'main_finding':'Direction of two-period plant averages differs across two documented event definitions; commercial RNG adoption is not established by either ratio.'})
    write_csv(out/'MONTEREY_PLANT_WINDOW_COMPARISON.csv',scenarios)
    same= configured_windows(2020,cfg['windows'])==configured_windows(int(load(ROOT/cfg['cases']['1456']['public_evidence_manifest'])['events'][0]['date_low'][:4]),cfg['windows'])
    write_json(out/'SKYLINE_DATE_AND_RECORD_CHECK.json',{'registry_start':'2020-02-01','reported_rng_month':'2020-01',
        'same_annual_windows':same,'exact_commercial_day':None,
        'reported_unit_retirement_month':'2019-11','registered_project_closure':'2019-12-31',
        'zero_years':[r['year'] for r in skyline if r['record_status']=='zero'],
        'missing_years':[r['year'] for r in skyline if r['record_status']=='record_missing'],
        'conclusion':'Month and asset definitions differ; no annual primary-window change. Actual zero retained, later missing rows not filled.'})
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(10,7),layout='constrained',sharex=True)
    for ax,series,name in [(axes[0],monterey,'Monterey candidate plant10748'),(axes[1],skyline,'Skyline candidate plant56528')]:
        ax.plot([r['year'] for r in series],[r['net_generation_MWh'] if r['net_generation_MWh'] is not None else float('nan') for r in series],'-o',color='#235b79',label='Reported LFG / ALL net generation')
        ax.axvspan(2016.5,2019.5,color='#dae4ee',alpha=.6,label='Primary background2017-2019')
        ax.axvspan(2020.5,2022.5,color='#d7e7dc',alpha=.6,label='Primary post2021-2022')
        ax.axvline(2020,color='#876132',linestyle=':',label='Frozen registration year2020')
        missing=[r['year'] for r in series if r['record_status']=='record_missing']
        if missing: ax.text(.98,.88,'Missing extract rows: '+', '.join(map(str,missing))+'\nNot plotted as zero',ha='right',va='top',transform=ax.transAxes,fontsize=9)
        ax.set_title(name+' (link provisional; no landfill allocation)',fontsize=11)
        ax.set_ylabel('Net generation (MWh)'); ax.set_ylim(bottom=0);ax.grid(alpha=.2)
    axes[0].axvline(2022,color='#ae513b',linestyle='--',label='Intermittent testing year2022')
    axes[0].legend(fontsize=8,ncols=2,loc='lower left')
    axes[1].set_xticks(range(2015,2025));axes[1].set_xlabel('Calendar year; annual co-occurrence is not simultaneous operation')
    fig.savefig(out/'PLANT_TRAJECTORIES.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4.6),layout='constrained')
    labels=['Registry-year window\n2017-19 vs2021-22','Testing-year window\n2019-21 vs2023-24']
    for n,s in enumerate(scenarios):
        ax.bar(n-.17,s['pre_mean_MWh'],width=.3,color='#829ab0',label='Three-year background' if n==0 else None)
        ax.bar(n+.17,s['post_mean_MWh'],width=.3,color='#4d856d',label='Two-year later period' if n==0 else None)
        ax.text(n,max(s['pre_mean_MWh'],s['post_mean_MWh'])+1700,f"{s['percent_difference']:+.1f}%",ha='center',fontsize=11)
    ax.set_xticks([0,1],labels);ax.set_ylabel('EIA10748 period mean net generation (MWh)')
    ax.set_title('Different event definitions change the plant-only description\nNeither comparison estimates an RNG effect',fontsize=11)
    ax.set_ylim(0,44000);ax.legend(fontsize=8,loc='upper left');ax.spines[['top','right']].set_visible(False)
    fig.savefig(out/'MONTEREY_EVENT_WINDOW_COMPARISON.png',dpi=150);plt.close(fig)
    lines=['本批关键原件核对入口；自动定位，不代签人工核验。','']
    for fid in ['217','1456']:
        lines.append('Landfill ID '+fid)
        for kind,obj in locators[fid].items():
            lines.append(f"{obj['absolute_path']} | sheet={obj['sheet']} | header Excel row={obj['header_excel_row']} | filters={obj['filters']}")
            for row in obj['matched_records']:
                lines.append('Excel row='+str(row['excel_row_one_based'])+'; '+', '.join(f"{k}: {v['cell']}={v['value']}" for k,v in row['cells'].items()))
        lines.append('')
    lines.extend(['优先本人核对三组：',str((ROOT/originals['MON_CEC_REPORT']['path']).resolve())+' PDF20/印刷17、27/印刷24（试运行与常态供气）；PDF9/印刷6（初期气源）',
        str((ROOT/originals['SKY_WM_PRESENTATION']['path']).resolve())+' PDF7/slide7，January2020与Atmos；封面日期2020-11-11',
        'EIA库存Operating8844—8847/Retired六条，与2017Plant3214、LMOP366—373：只说明所列对象和快照，不证明整场资产完整。',
        'Human verification=PENDING；所有原件保持只读。'])
    (out/'HUMAN_REVIEW_ENTRIES.txt').write_text('\n'.join(lines),encoding='utf-8')
    checks={'original_key_counts_verified':True,'source_event_phrases_found':True,
        'no_landfill_allocation':all(r['landfill_assigned_MWh'] is None for r in monterey+skyline),
        'two_event_definitions_not_replacement_anchors':True,'skyline_zero_not_missing':len([r for r in skyline if r['record_status']=='zero'])==1,
        'all_inputs_unchanged':all(sha(ROOT/p)==h for p,h in before.items())}
    code=[Path(__file__),*sorted((ROOT/'src/rng').glob('*.py'))]
    write_json(out/'CODE_SNAPSHOT.json',{str(p.relative_to(ROOT)):{'sha256':sha(p),'text':p.read_text(encoding='utf-8')} for p in code})
    write_json(out/'RUN_RECORD.json',{'utc':datetime.now(timezone.utc).isoformat(),'command':[sys.executable,*sys.argv],
        'cwd':str(Path.cwd()),'python':sys.version,'platform':platform.platform(),
        'packages':{p:importlib.metadata.version(p) for p in ['openpyxl','matplotlib','pypdf']},
        'input_sha256':before,'module_sha256':{str(p.relative_to(ROOT)):sha(p) for p in code},
        'git_state':'No root Git repository; source and code hashes retained','random_seed':20261020,
        'split':'No model; repeated years not independent facilities','network_calls':0,'paid_script_cost':0,
        'human_hours_used':None,'human_hours_remaining':None,'elapsed_tool_wall_seconds':time.perf_counter()-started,
        'checks':checks,'outputs':{p.name:sha(p) for p in out.iterdir() if p.is_file()}})
    assert all(checks.values())
    print({'output':str(out),'plant_only_percent_differences':[round(s['percent_difference'],3) for s in scenarios],'checks':checks})


if __name__=='__main__': main()
