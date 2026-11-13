"""Read-only feasibility audit for the proposed RNG/infrastructure study; no fitting."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse, csv, hashlib, json, platform, shutil, struct, sys, time, zipfile
import xml.etree.ElementTree as ET
from openpyxl import load_workbook
import openpyxl

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def missing(v):return v is None or isinstance(v,str) and not v.strip()
def main():
    start=time.perf_counter();parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);args=parser.parse_args()
    out=(ROOT/args.run_dir).resolve();assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    raw=ROOT/'data/raw/2026-10-06_public_inputs/lmopdata.xlsx';rawsha=sha(raw)
    assert rawsha=='a5c8bea26e7b5f6ecef247b762bde89b999915504814825a1eac7a1cd9f4ddd3'
    w=load_workbook(raw,read_only=True,data_only=True);s=w['LMOP Database'];it=iter(s.values);h=next(it);groups=defaultdict(list)
    for n,vals in enumerate(it,2):
        r=dict(zip(h,vals));r['_excel_row']=n;groups[r['Landfill ID']].append(r)
    descriptions=[list(r) for r in w['Field Descriptions'].values];w.close()
    assert len(groups)==2641 and sum(map(len,groups.values()))==3399
    fields=['Latitude','Longitude','Waste in Place (tons)','Waste in Place Year','LFG Collected (mmscfd)',
            'LFG Collection System In Place?','Year Landfill Opened','Landfill Closure Year','Current Landfill Status','Ownership Type']
    conflicts={k:sum(len({str(r[k]) for r in rs if not missing(r[k])})>1 for rs in groups.values()) for k in fields}
    assert not any(conflicts.values()),'Report conflicts before choosing a canonical field'
    rng=lambda r:r['Project Type Category']=='Renewable Natural Gas'
    op=lambda r:rng(r) and r['Current Project Status']=='Operational'
    pipe=lambda r:op(r) and r['RNG Delivery Method']=='Pipeline Injection'
    rows=[]
    for cid,rs in sorted(groups.items()):
        d={k:next((r[k] for r in rs if not missing(r[k])),None) for k in fields}
        lat,lon=d['Latitude'],d['Longitude'];finitecoord=isinstance(lat,(float,int)) and isinstance(lon,(float,int)) and -90<=lat<=90 and -180<=lon<=180
        rows.append({'landfill_id':cid,'name':rs[0]['Landfill Name'],'state':rs[0]['State'],
            'project_rows':len(rs),'registry_any_rng_type':any(rng(r) for r in rs),
            'registry_operational_rng':any(op(r) for r in rs),'registry_operational_pipeline_rng':any(pipe(r) for r in rs),
            'registry_operational_or_shutdown_rng':any(rng(r) and r['Current Project Status'] in ['Operational','Shutdown'] for r in rs),
            'registry_operational_electricity':any(r['Project Type Category']=='Electricity' and r['Current Project Status']=='Operational' for r in rs),
            'coordinate_pair_valid_numeric':finitecoord,**d,
            'rng_statuses':';'.join(sorted({str(r['Current Project Status']) for r in rs if rng(r)})),
            'original_excel_rows':';'.join(str(r['_excel_row']) for r in rs)})
    with (out/'LANDFILL_REGISTRY_AUDIT.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
    rngrows=[r for rs in groups.values() for r in rs if rng(r)]
    opdates=[r['Project Start Date'] for r in rngrows if op(r)]
    valid=lambda r,fs:all(not missing(r[k]) for k in fs)
    counts={k:sum(r[k] for r in rows) for k in ['registry_any_rng_type','registry_operational_rng','registry_operational_pipeline_rng','registry_operational_or_shutdown_rng','coordinate_pair_valid_numeric']}
    statuses=[{'project_status':a,'delivery_method':b,'rows':v} for (a,b),v in sorted(Counter((str(r['Current Project Status']),str(r['RNG Delivery Method'])) for r in rngrows).items())]
    bytarget={str(y):{'landfills':sum(r['registry_operational_pipeline_rng']==y for r in rows),
        'missing_by_field':{k:sum(r['registry_operational_pipeline_rng']==y and missing(r[k]) for r in rows) for k in fields},
        'valid_coordinate_pair':sum(r['registry_operational_pipeline_rng']==y and r['coordinate_pair_valid_numeric'] for r in rows)} for y in [False,True]}
    summary={'scope':'Proposal feasibility audit of frozen registration; not fitted model, frozen analysis cohort or verified actual adoption',
        'landfills':len(rows),'project_level_rows':sum(map(len,groups.values())),'counts':counts,
        'missing_by_field':{k:sum(missing(r[k]) for r in rows) for k in fields},'field_conflicts':conflicts,
        'missing_by_provisional_pipeline_target':bytarget,'rng_project_rows_by_status_delivery':statuses,
        'rng_project_start_missing':sum(missing(r['Project Start Date']) for r in rngrows),
        'rng_start_dates_Dec31':sum(isinstance(r['Project Start Date'],datetime) and (r['Project Start Date'].month,r['Project Start Date'].day)==(12,31) for r in rngrows),
        'operational_rng_rows':len(opdates),'operational_rng_start_missing':sum(missing(v) for v in opdates),
        'operational_rng_start_Dec31':sum(isinstance(v,datetime) and (v.month,v.day)==(12,31) for v in opdates),
        'same_registry_has_operational_electric_and_rng_landfills':sum(r['registry_operational_electricity'] and r['registry_operational_rng'] for r in rows),
        'complete_fields_coordinates_WIP_openyear':sum(valid(r,['Latitude','Longitude','Waste in Place (tons)','Year Landfill Opened']) for r in rows),
        'complete_fields_plus_collectedgas':sum(valid(r,['Latitude','Longitude','Waste in Place (tons)','Year Landfill Opened','LFG Collected (mmscfd)']) for r in rows),
        'nonzero_numeric_collectedgas':sum(isinstance(r['LFG Collected (mmscfd)'],(float,int)) and r['LFG Collected (mmscfd)']>0 for r in rows),
        'warnings':['NoRNGrecord is not proof of no actualRNG','Operational is registry state, not independently verified production',
                    'Project rows/expansions are not independent landfills','Missing gas and WIP years cannot be filled with zero',
                    'Current gas/closure/WIP may be post-adoption; no Cox input constructed','Co-listed uses are not mutually exclusive competing absorbing events']}
    save(out/'LMOP_FEASIBILITY.json',summary);save(out/'FIELD_DESCRIPTIONS.json',descriptions)

    # Inspect exact official ZIP without extracting its members or adding dependencies.
    pdir=ROOT/'inputs/public/rng_adoption_review_2026-11-04';pipezip=pdir/'NaturalGas_InterIntrastate_Pipelines_US_EIA.zip'
    with zipfile.ZipFile(pipezip) as z:
        assert z.testzip() is None
        members=[{'member':i.filename,'bytes':i.file_size,'sha256':hashlib.sha256(z.read(i.filename)).hexdigest()} for i in z.infolist()]
        prj=z.read(next(n for n in z.namelist() if n.endswith('.prj'))).decode()
        shp=z.read(next(n for n in z.namelist() if n.endswith('.shp')))
        assert struct.unpack('>i',shp[:4])[0]==9994 and struct.unpack('<i',shp[32:36])[0]==3
        dbf=z.read(next(n for n in z.namelist() if n.endswith('.dbf')))
        nrecords=struct.unpack('<I',dbf[4:8])[0];hlen,rlen=struct.unpack('<HH',dbf[8:12]);fieldsdb=[]
        for pos in range(32,hlen-1,32):
            d=dbf[pos:pos+32]
            if not d or d[0]==13:break
            fieldsdb.append({'name':d[:11].split(b'\0')[0].decode(),'type':chr(d[11]),'width':d[16]})
        types=Counter();stat=Counter()
        for i in range(nrecords):
            row=dbf[hlen+i*rlen:hlen+(i+1)*rlen];cursor=1;d={}
            if row[:1]==b'*':continue
            for f in fieldsdb:
                d[f['name']]=row[cursor:cursor+f['width']].decode('utf-8',errors='replace').strip();cursor+=f['width']
            types[d.get('TYPEPIPE','')]+=1;stat[d.get('Status','')]+=1
        xml=ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.xml'))))
        metadata={tag:[e.text for e in xml.iter(tag) if e.text and e.text.strip()][:6] for tag in ['mdDateSt','pubDate','idAbs','idPurp','useLimit','idCredit','resTitle']}
    pipeline={'source':'https://www.eia.gov/maps/map_data/NaturalGas_InterIntrastate_Pipelines_US_EIA.zip',
              'path':str(pipezip.relative_to(ROOT)),'sha256':sha(pipezip),'compressed_bytes':pipezip.stat().st_size,
              'file_name_vintage':'202001','metadata':metadata,'prj':prj,'geometry':'Polyline',
              'bounding_box':list(struct.unpack('<4d',shp[36:68])),'records':nrecords,'dbf_fields':fieldsdb,
              'pipeline_types':dict(types),'status_values':dict(stat),'members':members,
              'missing_for_research':['Verified connection points/acceptance capacity','Complete localdistributiongrid','Per-segmentin-servicedates','Distance accuracy atsub-km scale'],
              'coordinates_warning':'OriginalZIP geographic degrees; DOE mirror metadata3857 is a separate representation. Do not compute Euclidean metres in either degrees or uncorrectedWebMercator.',
              'artifact_download_verified':True,'nearest_distances_computed':False,'all_licensing_and_coverage_questions_resolved':False}
    save(out/'PIPELINE_ARTIFACT_AUDIT.json',pipeline)
    history=ROOT/'inputs/public/topic_selection_2026-10-20/root_sources/national_lmopdata_files_2001-2023.zip'
    with zipfile.ZipFile(history) as z:hist=[{'member':i.filename,'bytes':i.file_size} for i in z.infolist()]
    save(out/'HISTORICAL_LMOP_AVAILABILITY.json',{'path':str(history.relative_to(ROOT)),'sha256':sha(history),'members':hist,
         'status':'Known local archive index inspected;2020baseline contents/IDjoins and time-varying predictors not audited in this run'})
    checks=['FrozenLMOPshaunchanged','3399projectrowscollapse2641uniqueLandfillIDs','Repeatedlandfillfieldconflictszero',
            'OperationalpipelineRNGpositive104','ExactpipelineZIPCRC/headerPolyline/DBFrecordsparsed','HistoricalLMOParchiveindexexists',
            'No distances/fittedcoefficients/newcohort freeze or humanhours fabricated']
    assert counts['registry_operational_pipeline_rng']==104 and sum(not missing(r['LFG Collected (mmscfd)']) for r in rows)==1151
    assert nrecords==sum(types.values());assert sha(raw)==rawsha
    save(out/'CHECKS.json',{'passed':checks,'count':len(checks),'not_independent_scientific_review':True})
    tracked=[raw,pipezip,history,Path(__file__),pdir/'DOE_NETL_pipeline_metadata.json',pdir/'DOWNLOAD_ATTEMPT_002.json']
    shutil.copyfile(__file__,out/'CODE_SNAPSHOT.py')
    save(out/'RUN_RECORD.json',{'command':[sys.executable,*sys.argv],'created_utc':datetime.now(timezone.utc).isoformat(),
         'client_date':'2026-11-04','python':sys.version,'platform':platform.platform(),'openpyxl':openpyxl.__version__,
         'input_sha256':{str(p.relative_to(ROOT)):sha(p) for p in tracked},
         'output_sha256':{p.name:sha(p) for p in out.iterdir() if p.is_file()},'git':'RootnotGit;codeandinputhashesrecorded',
         'sampling':'None; fullsourcegroupauditonly;original8/seed/configunchanged','models_fitted':0,
         'machine_elapsed_seconds':time.perf_counter()-start,'human_hours_used':None,'budget_reset':False})
    print(json.dumps({'out':str(out),'unique_landfills':len(rows),'registered_operational_rng':counts['registry_operational_rng'],
        'registered_operational_pipeline_rng':104,'missing_collected_gas':summary['missing_by_field']['LFG Collected (mmscfd)'],
        'pipeline_records':nrecords,'checks_passed':len(checks)},ensure_ascii=False))

if __name__=='__main__':main()
