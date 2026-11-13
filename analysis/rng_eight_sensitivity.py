"""Compute fixed-eight judgments, original-data coverage and bounded sensitivities."""
from pathlib import Path
from datetime import datetime,timezone,date
from collections import Counter
from decimal import Decimal,ROUND_HALF_UP
import argparse,csv,json,sys,time,platform,importlib.metadata

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from rng.evidence import load,sha
from rng.quantitative import window_summary,listed_asset_scopes


def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
def table(p,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def main():
    started=time.perf_counter();p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);args=p.parse_args()
    out=(ROOT/args.run_dir).resolve();assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    paths=['config/rng_pilot.json','reports/publication_plan_2026-10-25/EIGHT_SENSITIVITY_EVIDENCE.json',
      'reports/generator_inventory_2026-10-25_001/EVENT_EVIDENCE_TABLE.json',
      'outputs/2026-10-26_rng_linkage/annual_coverage_001/ANNUAL_COVERAGE.json',
      'outputs/2026-10-26_rng_linkage/annual_coverage_001/API_ORIGINAL_COMPARISON.json',
      'outputs/2026-10-26_rng_linkage/annual_coverage_001/ORIGINAL_ANNUAL_ROWS.json',
      'outputs/2026-10-26_rng_linkage/publication_review_002/EIGHT_CASE_STATUS_PAPER_DELTA.json',
      'reports/generator_inventory_2026-10-25_001/RELEVANT_INVENTORY_ROWS.json',
      'reports/publication_plan_2026-10-25/PUBLICATION_CASE_READ_RECORD.json']
    cfg,spec,events,cov,api_delta,originals,old,inventory,sec=[load(ROOT/x) for x in paths]
    paths += [cfg['inputs']['freeze'],cfg['inputs']['cohort'],cfg['inputs']['generation'],
      'inputs/public/rng_eight_quantitative_2026-10-26/wood_N5997_stack_test_2012.pdf',
      'inputs/public/rng_eight_quantitative_2026-10-26/wood_N5997_stack_test_2018.pdf',
      'inputs/public/rng_eight_quantitative_2026-10-26/3_1_Generator_Y2017.xlsx',
      'inputs/public/identity_preflight_2026-10-25/eia8602017.zip',
      'inputs/public/rng_eight_quantitative_2026-10-26/WOOD_GENERATOR2017_KEY_SCAN.json']
    paths.extend(x['public_evidence_manifest'] for x in cfg['cases'].values() if x.get('public_evidence_manifest'))
    hashes={r:sha(ROOT/r) for r in paths}
    freeze=load(ROOT/cfg['inputs']['freeze']);assert sorted(x['landfill_id'] for x in events['sites'])==freeze['selected_ids']
    rows=[];scenarios=[];assets=[];changes=[]
    previous={x['landfill_id']:x for x in old['rows']}
    for site in events['sites']:
        fid=site['landfill_id'];code=cfg['cases'][str(fid)]['plant_lead'];anchor=date.fromisoformat(site['registry_RNG'][0]['start'][:10])
        original=[r for r in cov['rows'] if r['plant_code']==code];assert len(original)==10
        values={r['year']:r['lfg_net_generation_MWh'] for r in original}
        primary=window_summary(values,anchor.year)
        current_scopes=listed_asset_scopes(site,anchor,'inputs/public/generator_inventory_2026-10-25/september_generator2026.xlsx');assets.extend(current_scopes)
        last=next(x for x in current_scopes if x['scope']=='LISTED_LFG_RETIRED_SUBSET_LAST_REPORTED_RETIREMENT')
        same_year=changed_year=0
        # Numerical outputs are plant-only descriptions. No matching method is its own reference.
        definitions=[dict(id='FROZEN_REGISTRATION',year=anchor.year,role='FROZEN_REGISTRATION',kind='PRIMARY_DESIGN',evidence=f'LMOP Landfill{fid}, frozenoriginalrows')]+spec['event_definitions'][str(fid)]
        for d in definitions:
            ws=window_summary(values,d['year'])
            scenarios.append(dict(landfill_id=fid,plant_code=code,scenario=d['id'],event_role=d['role'],comparison_kind=d['kind'],evidence=d['evidence'],
                primary_anchor_changed=False,asset_scope='CANDIDATE_EIA_PLANT_LFG_NET_NOT_WHOLELANDFILL',
                asset_relation_status='UNRESOLVED_TIMEVALID_PROJECT_TO_UNIT_CROSSWALK',human_review='PENDING',accepted_landfill_numeric_comparison=False,**ws))
            if d['id']!='FROZEN_REGISTRATION':
                same_year+=d['year']==anchor.year;changed_year+=d['year']!=anchor.year
        judgment=spec['case_judgments'][str(fid)]
        actual=[x for x in original if x['lfg_net_generation_MWh'] is not None]
        annual_missing=[x for x in original if x['lfg_net_generation_MWh'] is None]
        reasons=[]
        if not primary['complete3plus2']:reasons.append('Main3pre/2post annualrawvalues incomplete')
        reasons.append('Eventvalid project/asset relation and full boundary not accepted')
        row=dict(landfill_id=fid,name=site['name'],candidate_plant_code=code,registry_rng_date=anchor.isoformat(),
            registry_only_judgment=previous[fid]['registry_supported_judgment'],evidence_augmented_path=judgment['path'],
            evidence_augmented_judgment=judgment['statement'],judgment_scope=judgment['scope'],
            original_annual_lfg_values=len(actual),original_annual_lfg_missing=len(annual_missing),
            zero_years=';'.join(str(r['year']) for r in actual if r['lfg_net_generation_MWh']==0),
            negative_years=';'.join(str(r['year']) for r in actual if r['lfg_net_generation_MWh']<0),
            main_pre_values=primary['pre_nonmissing'],main_post_values=primary['post_nonmissing'],
            pre_mean_MWh=primary['pre_mean_MWh'],post_mean_MWh=primary['post_mean_MWh'],
            candidate_plant_only_main_percent=primary['plant_only_percent_change'],
            event_year_MWh=primary['event_year_MWh'],event_year_vs_pre_percent=primary['event_year_vs_pre_percent'],
            event_year_statistic='Separateauxiliarydescription, not postcomparison orcausaleffect',
            main_values_complete=primary['complete3plus2'],accepted_landfill_numeric_comparison=False,
            numeric_exclusion='; '.join(reasons),listed_retired_LFG_units=len(last['asset_ids']),
            last_listed_retired_subset_low=last['retirement_low'],last_listed_retired_subset_high=last['retirement_high'],
            last_retired_subset_to_registry_gap_min_days=last['gap_min_days'],last_retired_subset_to_registry_gap_max_days=last['gap_max_days'],
            listed_retired_subset_before_background=last['entirely_before_background'],
            documented_alt_stages_same_annual_window=same_year,documented_alt_stages_changed_annual_window=changed_year,
            actual_first_commercial_day_known=False,human_review='PENDING',second_review='NOT_COMPLETED',
            source_evidence=';'.join(judgment['source_ids']),source_originals='annual_coverage_001/ORIGINAL_ANNUAL_ROWS.json; existingcaseevidencemanifests; EIGHT_SENSITIVITY_EVIDENCE.json')
        rows.append(row)
        changes.append(dict(landfill_id=fid,old_pre_values=previous[fid]['pre_nonmissing_years_of3'],old_post_values=previous[fid]['post_nonmissing_years_of2'],
            new_pre_values=primary['pre_nonmissing'],new_post_values=primary['post_nonmissing'],
            coverage_changed=(previous[fid]['pre_nonmissing_years_of3'],previous[fid]['post_nonmissing_years_of2'])!=(primary['pre_nonmissing'],primary['post_nonmissing']),
            coverage_certainty_change='Filteredextract absence upgraded to exactID completeannualsource-sheet check; noallsiteabsenceclaim'))
    assert [x['landfill_id'] for x in rows]==freeze['selected_ids']
    rounding=[]
    for d in api_delta['rows']:
        if d['status']!='DIFFERENT':continue
        old=Decimal(str(d['api_MWh']));new=Decimal(str(d['annual_original_MWh']))
        rounding.append(dict(**d,api_minus_original_MWh=float(old-new),agrees_after_two_decimal_rounding=old==new.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)))
    assert all(x['agrees_after_two_decimal_rounding'] for x in rounding)
    boundary=[]
    for r in cov['rows']:
        if r['plant_code']!=54286 or r['lfg_net_generation_MWh'] is None or r['allfuel_net_generation_MWh'] is None:continue
        lfg=r['lfg_net_generation_MWh'];full=r['allfuel_net_generation_MWh']
        boundary.append(dict(plant_code=54286,year=r['year'],lfg_net_MWh=lfg,allfuel_net_MWh=full,nonLFG_net_MWh=full-lfg,
            excess_if_allfuel_mislabelled_LFG_percent=100*(full/lfg-1) if lfg>0 else None,
            comparison_kind='DOCUMENTED_FUEL_SCOPE_CONTRAST_NOT_TWO_VALID_LANDFILL_ALLOCATIONS',
            source_workbook=r['workbook'],source_sheet=r['generation_sheet'],source_excel_rows=r['generation_excel_rows'],
            actual_misallocation_claimed=False))
    keyed=load(ROOT/'inputs/public/rng_eight_quantitative_2026-10-26/WOOD_GENERATOR2017_KEY_SCAN.json')
    sourcepath=Path(keyed['absolute_path']);assert sha(sourcepath)==keyed['sha256']
    capacity2017=[r['cells']['Nameplate Capacity (MW)']['value'] for r in keyed['matched_records']]
    capacity2026=[r['Nameplate Capacity (MW)'] for r in inventory if r.get('Plant ID')==54549 and r['source_sheet']=='Retired']
    assert sorted(capacity2017)==sorted(capacity2026)==[.8]*4+[1.6]*3
    asset_support=dict(plant_code=54549,source2017_keyscan=keyed,
        source2017_original_archive='inputs/public/identity_preflight_2026-10-25/eia8602017.zip',member='3_1_Generator_Y2017.xlsx',
        raw2017_composition_MW=capacity2017,raw2026_retired_composition_MW=capacity2026,documented_test_composition_MW=[.8]*4+[1.6]*3,
        set_count=7,total_nameplate_MW=round(sum(capacity2017),6),group_composition_agrees=True,
        actual2018_tested_local_engine_numbers=[3,5,6,7],all7_tested_together_claimed=False,
        document2018_plant_relation='LFGfromWoodStreetlandfill to sevenenginepowerstation explicitly described;2018actualtest',
        eia_exact_identifier_crosswalk='NOT_EXPLICIT_IN_TEST_REPORTS; matching composition/name/owner supports set-level correspondence, not exactunit-ID identity',
        address_conflict='EIA2017Plant16800WoodRoad vs test16980WoodRoad retained, no numeric addresscorrection',
        current_pipeline_supply='2022inspectionWoodStreetplusPaulson; no sourcefractions or allocation',
        same_source_dependency='2012/2018Derenzo contractedtestreports oneorganisation group; EGLEhosting alone notindependentverification',human_review='PENDING')
    write(out/'WOOD_ASSET_SET_CORROBORATION.json',asset_support)
    write(out/'EIGHT_CASE_JUDGMENTS.json',dict(scope='Fixed8descriptive evidence judgments, not allsite classification',rows=rows))
    table(out/'EIGHT_CASE_JUDGMENTS.csv',rows)
    write(out/'EVENT_STAGE_SENSITIVITY.json',dict(scope='Source-supported eventstage contrasts; differentstage contrasts are not equivalentcommercialdate estimates',rows=scenarios,
        excluded_anchors=spec['excluded_date_anchors']))
    table(out/'EVENT_STAGE_SENSITIVITY.csv',scenarios)
    write(out/'ASSET_DATE_INTERVALS.json',dict(rows=assets,full_site_inference_permitted=False))
    table(out/'ASSET_DATE_INTERVALS.csv',assets)
    wide=[]
    for r in rows:
        ss=[s for s in scenarios if s['landfill_id']==r['landfill_id']]
        aa=[s for s in assets if s['landfill_id']==r['landfill_id']]
        calculated=[s['plant_only_percent_change'] for s in ss if s['plant_only_percent_change'] is not None]
        order_states={s['entirely_before_background'] for s in aa}
        site=next(s for s in events['sites'] if s['landfill_id']==r['landfill_id'])
        wide.append(dict(landfill_id=r['landfill_id'],name=r['name'],source_event_definitions=len(ss),
            event_years=';'.join(str(s['anchor_year']) for s in ss),
            event_stages_change_calendar_window=bool(r['documented_alt_stages_changed_annual_window']),
            fully_observed_candidate_plant_stage_descriptions=len(calculated),
            candidate_plant_description_min_percent=min(calculated) if calculated else None,
            candidate_plant_description_max_percent=max(calculated) if calculated else None,
            numerical_stage_contrast_available=len(calculated)>1,
            percentage_range_is='Differentstage/calendarwindow description; NOT confidenceinterval or RNGtreatmenteffect',
            asset_date_scope_records=len(aa),source_scopes_change_exit_before_background_judgment=len(order_states)>1,
            asset_scope_min_gap_days=min(s['gap_min_days'] for s in aa),asset_scope_max_gap_days=max(s['gap_max_days'] for s in aa),
            all_these_listed_scope_exit_dates_before_registration=all(s['entirely_before_rng_registration'] for s in aa),
            known_Operating_LFG_rows_excluded_from_retired_subset=sum(u['sheet']=='Operating' and u['fuel']=='LFG' for u in site['reported_unit_rows']),
            physical_same_asset_crosswalk_complete=False,whole_site_classification='UNDETERMINED',
            sensitivity_limit='Changingassetoradministrativeeventscope is a differentquestion, not error in a knownphysicalevent; do notextend retiredsubset to fullsite',
            human_review='PENDING'))
    write(out/'EIGHT_SENSITIVITY_SUMMARY.json',dict(rows=wide))
    table(out/'EIGHT_SENSITIVITY_SUMMARY.csv',wide)
    write(out/'FUEL_BOUNDARY_CONTRAST.json',dict(rows=boundary))
    table(out/'FUEL_BOUNDARY_CONTRAST.csv',boundary)
    write(out/'ROUNDING_RECONCILIATION.json',dict(rows=rounding,scientific_results_changed=False))
    write(out/'BEFORE_AFTER_COVERAGE_CHECK.json',dict(rows=changes,all_primary_coverage_counts_unchanged=not any(x['coverage_changed'] for x in changes)))
    summary=dict(fixed_cases=8,original_annual_plant_years=80,actual_lfg_values=sum(r['lfg_net_generation_MWh'] is not None for r in cov['rows']),
        lfg_missing_rows=sum(r['lfg_net_generation_MWh'] is None for r in cov['rows']),
        zero_plant_years=[dict(plant=r['plant_code'],year=r['year']) for r in cov['rows'] if r['lfg_net_generation_MWh']==0],
        frame_present_without_generation=[dict(plant=r['plant_code'],year=r['year']) for r in cov['rows'] if r['frame_records'] and not r['raw_allfuel_rows']],
        plant_only_primary_complete_cases=[r['landfill_id'] for r in rows if r['main_values_complete']],
        accepted_landfill_numeric_comparisons=sum(r['accepted_landfill_numeric_comparison'] for r in rows),
        event_year_auxiliary_calculable_cases=[r['landfill_id'] for r in rows if r['event_year_vs_pre_percent'] is not None],
        candidate_retired_subset_before_background=[r['landfill_id'] for r in rows if r['listed_retired_subset_before_background']],
        scenario_rows=len(scenarios),asset_interval_rows=len(assets),paper_mainline_decision='CURRENT_DATA_DO_NOT_SUPPORT_NUMERIC_POST_RNG_COMPARISON_AS_MAIN_MANUSCRIPT_RESULT',
        alternative_scope='Evidence-based8case energy-use histories and bounded sensitivity can continue only after assessing contribution/review feasibility; not guaranteedpublishable',
        no_causal_effect=True,no_national_error_estimate=True,no_missing_zero_imputation=True,human_review='PENDING',human_hours=None,remaining_human_hours=None)
    write(out/'SUMMARY.json',summary)
    make_figures(out,cov['rows'],rows,boundary)
    code=[Path(__file__),ROOT/'src/rng/quantitative.py',ROOT/'src/rng/analysis.py']
    write(out/'CODE_SNAPSHOT.json',{str(p.relative_to(ROOT)):dict(sha256=sha(p),text=p.read_text(encoding='utf-8')) for p in code})
    assert all(sha(ROOT/r)==h for r,h in hashes.items())
    write(out/'RUN_RECORD.json',dict(utc=datetime.now(timezone.utc).isoformat(),command=[sys.executable,*sys.argv],python=sys.version,platform=platform.platform(),
        packages={k:importlib.metadata.version(k) for k in ['openpyxl','matplotlib','pypdf']},input_sha256=hashes,module_sha256={str(p.relative_to(ROOT)):sha(p) for p in code},
        random_seed=cfg['frozen_seed'],split='Fixed8descriptiveassessment; developmentcases not independentvalidation',git_state='No rootGit; code/sourceSHA recorded',
        elapsed_machine_wall_seconds=time.perf_counter()-started,human_hours=None,cumulative_human_hours=None,remaining_human_hours=None,network_calls=0,paid_cost=0,
        outputs={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def make_figures(out,coverage,rows,boundary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import ListedColormap
    names={217:'Monterey',1456:'Skyline',1479:'Atascocita',1676:'Mallard',1820:'Tessman',1890:'WoodStreet',1939:'SouthSide',2207:'Charleston'}
    years=list(range(2015,2025));codes=[r['candidate_plant_code'] for r in rows]
    lookup={(r['plant_code'],r['year']):r for r in coverage}
    matrix=np.array([[0 if lookup[c,y]['lfg_net_generation_MWh'] is None else 1 if lookup[c,y]['lfg_net_generation_MWh']==0 else 2 if lookup[c,y]['lfg_net_generation_MWh']>0 else 3 for y in years] for c in codes])
    fig,ax=plt.subplots(figsize=(11.3,5.7),layout='constrained');ax.imshow(matrix,cmap=ListedColormap(['#dddddd','#ffffff','#437d98','#bf8760']),vmin=0,vmax=3,aspect='auto')
    ax.set(xticks=range(10),xticklabels=years,yticks=range(8),yticklabels=[names[r['landfill_id']]+' / '+str(r['candidate_plant_code']) for r in rows],title='Final annual EIA-923: exact plant-code LFG record coverage')
    from matplotlib.patches import Rectangle,Patch
    for i,r in enumerate(rows):
        for j,y in enumerate(years):
            value=lookup[r['candidate_plant_code'],y]['lfg_net_generation_MWh']
            ax.text(j,i,'NA' if value is None else '0' if value==0 else f'{value/1000:.1f}',ha='center',va='center',color='white' if value and value>0 else '#303030',fontsize=9)
        j=int(r['registry_rng_date'][:4])-2015;ax.add_patch(Rectangle((j-.49,i-.49),.98,.98,fill=False,ec='#bb542d',lw=2))
    ax.legend(handles=[Patch(color='#437d98',label='Positive net generation (cell: GWh)'),Patch(facecolor='white',edgecolor='gray',label='Observed zero'),Patch(color='#dddddd',label='No LFG generation row'),Patch(facecolor='none',edgecolor='#bb542d',label='Frozen registration year')],loc='upper center',bbox_to_anchor=(.5,-.1),ncol=2,fontsize=9)
    fig.savefig(out/'ANNUAL_COVERAGE.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10.3,5.4),layout='constrained')
    for i,r in enumerate(rows):
        lo=r['last_retired_subset_to_registry_gap_min_days']/365.25;hi=r['last_retired_subset_to_registry_gap_max_days']/365.25
        ax.errorbar((lo+hi)/2,i,xerr=[[(hi-lo)/2],[(hi-lo)/2]],fmt='o',color='#285969',capsize=4)
        count=r['listed_retired_LFG_units'];ax.text(hi+.12,i,str(count)+' listed retired LFG '+('unit' if count==1 else 'units'),va='center',fontsize=8)
    ax.set(yticks=range(8),yticklabels=[names[r['landfill_id']] for r in rows],xlabel='Years from latest reported retirement in the listed subset to RNG registration',title='Conditional asset chronology: listed subsets, not complete site retirement')
    ax.invert_yaxis();ax.axvline(0,color='gray',lw=1);ax.grid(axis='x',alpha=.2);ax.set_xlim(-.2,11)
    fig.savefig(out/'LISTED_ASSET_EVENT_GAPS.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8.6,4.4),layout='constrained');x=np.arange(len(boundary));w=.34
    ax.bar(x-w/2,[r['lfg_net_MWh'] for r in boundary],w,label='LFG fuel component',color='#42778b')
    ax.bar(x+w/2,[r['allfuel_net_MWh'] for r in boundary],w,label='All reported fuels at plant',color='#bb8c57')
    ax.set(xticks=x,xticklabels=[r['year'] for r in boundary],ylabel='Net generation (MWh)',title='Plant 54286: fuel scope contrast, no landfill allocation');ax.legend();ax.grid(axis='y',alpha=.15)
    fig.savefig(out/'FUEL_SCOPE_CONTRAST.png',dpi=150);plt.close(fig)


if __name__=='__main__':main()
