"""Bounded feasibility counts for literature-led RNG questions; no model/cohort freeze."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, importlib.metadata, io, json, shutil, sys, time, zipfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_json(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def flags(d):
    rng = d['Project Type Category'].eq('Renewable Natural Gas')
    pipe = rng & d['RNG Delivery Method'].eq('Pipeline Injection')
    electricity = d['Project Type Category'].eq('Electricity')
    result = d.groupby('Landfill ID',sort=True).first()[['Landfill Name','State','Latitude','Longitude',
                'Waste in Place (tons)','Waste in Place Year','Year Landfill Opened',
                'Current Landfill Status','Ownership Type','LFG Collection System In Place?']].copy()
    masks = {
        'pipe_op': pipe & d['Current Project Status'].eq('Operational'),
        'pipe_history': pipe & d['Current Project Status'].isin(['Operational','Shutdown']),
        'rng_history': rng & d['Current Project Status'].isin(['Operational','Shutdown']),
        'pipe_development': pipe & d['Current Project Status'].isin(['Planned','Construction']),
        'electric_op': electricity & d['Current Project Status'].eq('Operational'),
        'electric_history': electricity & d['Current Project Status'].isin(['Operational','Shutdown']),
        'direct_op': d['Project Type Category'].eq('Direct') & d['Current Project Status'].eq('Operational')}
    for k,m in masks.items(): result[k] = result.index.isin(d.loc[m,'Landfill ID'])
    result['energy_context'] = np.select([result.electric_op & result.direct_op,result.electric_op,result.direct_op,
                                        result.electric_history],['electric_and_direct','electric','direct','past_electric_only'],default='other_or_no_record')
    ed = d.loc[masks['electric_op']].copy()
    ed['start'] = pd.to_datetime(ed['Project Start Date'],errors='coerce')
    result['earliest_registered_current_electric_start'] = ed.groupby('Landfill ID')['start'].min()
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);args=parser.parse_args()
    start=time.perf_counter();utc=datetime.now(timezone.utc).isoformat()
    out=(ROOT/args.run_dir).resolve();assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    raw=ROOT/'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
    archive=ROOT/'inputs/public/topic_selection_2026-10-20/root_sources/national_lmopdata_files_2001-2023.zip'
    hashes={str(p.relative_to(ROOT)):sha(p) for p in [raw,archive]}
    with zipfile.ZipFile(archive) as z: payload=z.read('2020Aug_lmopdata.xlsx')
    before=pd.read_excel(io.BytesIO(payload),sheet_name='LMOP Database')
    after=pd.read_excel(raw,sheet_name='LMOP Database');after['excel_row']=np.arange(len(after))+2
    shared_fields=['State','Latitude','Longitude','Waste in Place (tons)','Waste in Place Year',
                   'Year Landfill Opened','Current Landfill Status','Ownership Type',
                   'LFG Collection System In Place?']
    conflicts={period:{k:int((d.groupby('Landfill ID')[k].nunique(dropna=True)>1).sum()) for k in shared_fields}
               for period,d in [('2020',before),('2024',after)]}
    assert not any(n for fields in conflicts.values() for n in fields.values()),conflicts
    b=flags(before);a=flags(after)
    joined=b.add_prefix('baseline_').join(a.add_prefix('end_'),how='left')
    joined['matched2024']=joined.index.isin(a.index)
    # Baseline prior RNG exclusions are based on recorded OP/Shutdown in that
    # snapshot, not independently verified absence of earlier RNG.
    joined['provisional_no_prior_rng_history'] = ~joined.baseline_rng_history
    joined['candidate_new_current_op'] = joined.matched2024 & ~joined.baseline_pipe_op & joined.end_pipe_op.eq(True)
    joined['candidate_new_recorded_history'] = joined.matched2024 & ~joined.baseline_pipe_history & joined.end_pipe_history.eq(True)
    rngpipe = after['Project Type Category'].eq('Renewable Natural Gas') & after['RNG Delivery Method'].eq('Pipeline Injection')
    history = after.loc[rngpipe & after['Current Project Status'].isin(['Operational','Shutdown'])].copy()
    history['start']=pd.to_datetime(history['Project Start Date'],errors='coerce')
    joined['earliest_end_pipe_history_start'] = history.groupby('Landfill ID')['start'].min()
    joined['dated_after_baseline_month'] = joined.earliest_end_pipe_history_start.gt(pd.Timestamp('2020-08-31'))
    joined['provisional_dated_new_rng_history'] = joined.candidate_new_recorded_history & joined.provisional_no_prior_rng_history & joined.dated_after_baseline_month
    joined['registered_electric_project_age_years_2020'] = (pd.Timestamp('2020-08-31')-joined.baseline_earliest_registered_current_electric_start).dt.days/365.25
    joined.to_csv(out/'BASELINE_CONTEXT.csv',encoding='utf-8-sig')
    group_rows=[]
    matched=joined[joined.matched2024]
    for pop,sub in [('matched_baseline_no_pipe_op',matched[~matched.baseline_pipe_op]),
                    ('matched_baseline_no_recorded_rng_history',matched[matched.provisional_no_prior_rng_history])]:
        for context,g in sub.groupby('baseline_energy_context'):
            group_rows.append({'population':pop,'baseline_context':context,'landfills':len(g),
                               'current_op_changes':int(g.candidate_new_current_op.sum()),
                               'history_changes':int(g.candidate_new_recorded_history.sum()),
                               'dated_new_rng_history_candidates':int(g.provisional_dated_new_rng_history.sum()),
                               'baseline_positive_wip':int(g['baseline_Waste in Place (tons)'].gt(0).sum()),
                               'baseline_coordinates':int(g[['baseline_Latitude','baseline_Longitude']].notna().all(axis=1).sum())})
    counts=pd.DataFrame(group_rows);counts.to_csv(out/'BASELINE_CONTEXT_COUNTS.csv',index=False,encoding='utf-8-sig')
    changes=joined[joined.candidate_new_current_op]
    pd.crosstab(changes.baseline_pipe_development,changes.baseline_electric_op).to_csv(out/'48_CANDIDATES_BASELINE_DEVELOPMENT_BY_ELECTRIC.csv')
    # Audit a stricter candidate label, rather than calling it verified incidence.
    c=joined[joined.provisional_dated_new_rng_history]
    c.to_csv(out/'DATED_NEW_REGISTRY_HISTORY_CANDIDATES.csv',encoding='utf-8-sig')
    original_rows=[]
    for period,d in [('2020',before),('2024',after)]:
        for idx,row in d[d['Landfill ID'].isin(c.index)].iterrows():
            original_rows.append({'snapshot':period,'sheet':'LMOP Database','excel_row':int(idx)+2,
                    **{k:row[k] for k in ['Landfill ID','Landfill Name','Project ID','Current Project Status',
                                         'Project Type Category','RNG Delivery Method','Project Start Date']}})
    pd.DataFrame(original_rows).to_csv(out/'CANDIDATE_ORIGINAL_ROWS.csv',index=False,encoding='utf-8-sig')
    risk=matched[matched.provisional_no_prior_rng_history]
    complete=risk[['baseline_Latitude','baseline_Longitude','baseline_Waste in Place (tons)',
                   'baseline_Year Landfill Opened']].notna().all(axis=1)&risk['baseline_Waste in Place (tons)'].gt(0)
    write_json(out/'BASELINE_COMPLETENESS.json',{'population':'matched_baseline_no_recorded_rng_history',
        'population_n':len(risk),'complete_n':int(complete.sum()),
        'dated_candidates_in_complete':int(risk.loc[complete,'provisional_dated_new_rng_history'].sum()),
        'definition':'Nonmissing baseline Latitude/Longitude/WIP/openyear and WIP>0; geographic coverage is not yet a verified distance.'})
    stage={}
    for val in [False,True]:
        g=matched[(~matched.baseline_pipe_op)&matched.baseline_pipe_development.eq(val)]
        stage[str(val)]={'baseline_sites':len(g),'current_op_in2024':int(g.end_pipe_op.eq(True).sum())}
    report={'scope':'Literature-led feasibility; not final risk set or adjusted association',
            'baseline_landfills':len(b),'matched':len(matched),'48_current_op_candidates':len(changes),
            'among48_baseline_electric_op':int(changes.baseline_electric_op.sum()),
            'among48_baseline_pipe_planned_or_construction':int(changes.baseline_pipe_development.sum()),
            'baseline_development_groups':stage,
            'provisional_dated_new_history_no_prior_rng':len(c),
            'among_stricter_candidates_baseline_electric_op':int(c.baseline_electric_op.sum()),
            'among_stricter_candidates_baseline_pipe_development':int(c.baseline_pipe_development.sum()),
            'candidate_electric_age_available':int(c.registered_electric_project_age_years_2020.notna().sum()),
            'source_field_conflicts_by_snapshot':conflicts,
            'interpretation_limits':['Current operational2024 is survival-conditioned deployment, not cumulative incidence.',
              'OPorShutdown history expands the observed endpoint, but does not prove complete lifetime history.',
              'Baseline planned/construction is already a selected development group; stage comparison is not a causal transition model.',
              'Earliest registered project start is neither generator hardware age nor measured PPA expiry.',
              'Same landfillID and project categories need identity/date checks; no independent manual review claimed.'],
            'models_fitted':0,'human_hours_used':None,'human_hours_remaining':None}
    checks={'unique_baseline_ids':bool(joined.index.is_unique),'replicates48_current_op_candidates':len(changes)==48,
            'candidate_strict_subset':bool(c.index.isin(matched[~matched.baseline_rng_history].index).all()),
            'no_conflicting_canonical_fields':not any(n for fields in conflicts.values() for n in fields.values()),
            'inputs_unchanged':hashes=={str(p.relative_to(ROOT)):sha(p) for p in [raw,archive]}}
    assert all(checks.values()),checks
    write_json(out/'FEASIBILITY.json',report);write_json(out/'CHECKS.json',checks)
    shutil.copy2(__file__,out/'CODE_SNAPSHOT.py')
    write_json(out/'RUN_RECORD.json',{'started_utc':utc,'finished_utc':datetime.now(timezone.utc).isoformat(),
        'machine_seconds':time.perf_counter()-start,'command':[sys.executable,*sys.argv],
        'packages':{k:importlib.metadata.version(k) for k in ['pandas','numpy','openpyxl']},
        'inputs_sha256':hashes,'archive_member':'2020Aug_lmopdata.xlsx','member_sha256':hashlib.sha256(payload).hexdigest(),
        'script_sha256':sha(Path(__file__)),'git_state':'workspace_root_not_a_git_repository','seed':None,
        'split':'none; no model','output':str(out.relative_to(ROOT)),'human_hours_used':None})
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
