"""Scan official final annual923 originals for the frozen eight plant leads."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from zipfile import ZipFile
import argparse,csv,json,sys,time,platform,importlib.metadata,math

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from rng.evidence import load,sha


def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')
def norm(x):return ' '.join(str(x).split()) if x is not None else ''
def pid(x):
    try:return str(int(float(str(x))))
    except (ValueError,TypeError):return None
def number(x):
    if x is None or str(x).strip() in {'','.','NA','N/A','NM','*','--'}:return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None


def scan(wb,sheet,targets,source):
    ws=wb[sheet];headers=None;found=[];count=0
    for n,cells in enumerate(ws.iter_rows(),1):
        values=[c.value for c in cells]
        if headers is None:
            h={norm(v):i for i,v in enumerate(values) if v is not None}
            if 'Plant Id' in h:
                headers=h;headerrow=n;original_headers={norm(v):v for v in values if v is not None}
            elif n>12:raise ValueError('Plant Id header not found: '+sheet)
            continue
        code=pid(values[headers['Plant Id']])
        if code:count+=1
        if code not in targets:continue
        fields={h:values[i] for h,i in headers.items()}
        cellmap={h:dict(cell=cells[i].coordinate,original_header=original_headers[h],value=values[i]) for h,i in headers.items()}
        found.append(dict(plant_code=code,excel_row=n,header_excel_row=headerrow,fields=fields,cells=cellmap,
            source=source,sheet=sheet,automatic_extraction='KEY_MATCH_ORIGINAL',human_review='PENDING'))
    return dict(sheet=sheet,header_excel_row=headerrow,rows_with_plant_id=count,selected_rows=found)


def aggregate(records,fuel=None):
    rows=records if fuel is None else [r for r in records if r['fields']['Reported Fuel Type Code']==fuel]
    if not rows:return None,'NO_MATCHING_RAW_ROW'
    allrows=[r for r in rows if r['fields']['Reported Prime Mover']=='ALL']
    chosen=allrows if allrows else rows
    keys=[(r['fields'].get('Reported Prime Mover'),r['fields'].get('Reported Fuel Type Code'),r['fields'].get('Nuclear Unit Id')) for r in chosen]
    if len(keys)!=len(set(keys)):return None,'DUPLICATE_RAW_KEY_UNRESOLVED'
    vals=[number(r['fields']['Net Generation (Megawatthours)']) for r in chosen]
    if any(v is None for v in vals):return None,'SOURCE_FIELD_MISSING_OR_NONNUMERIC'
    value=sum(vals)
    return value,'OBSERVED_ZERO' if value==0 else 'OBSERVED_NEGATIVE' if value<0 else 'OBSERVED_POSITIVE'


def main():
    started=time.perf_counter();p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);args=p.parse_args()
    out=(ROOT/args.run_dir).resolve();assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    import openpyxl
    config=load(ROOT/'config/rng_pilot.json');targets={str(x['plant_lead']) for x in config['cases'].values()}
    folder=ROOT/'inputs/public/eia923_annual_2015_2024_2026-10-26';workbooks=folder/'workbooks';workbooks.mkdir(exist_ok=True)
    before={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'config/rng_pilot.json',ROOT/config['inputs']['generation'],ROOT/config['inputs']['freeze'],ROOT/config['inputs']['cohort']]}
    annual=[];coverage=[];extracted=[]
    for year in range(2015,2025):
        archive=folder/f'f923_{year}.zip';before[str(archive.relative_to(ROOT))]=sha(archive)
        with ZipFile(archive) as z:
            candidates=[i for i in z.infolist() if i.filename.endswith('.xlsx') and 'Schedules_2_3_4_5_' in i.filename]
            assert len(candidates)==1 and candidates[0].file_size<150000000
            member=candidates[0].filename;assert Path(member).name==member
            dest=workbooks/member;payload=z.read(member)
            if dest.exists():assert dest.read_bytes()==payload
            else:dest.write_bytes(payload)
        before[str(dest.relative_to(ROOT))]=sha(dest)
        src=dict(archive=str(archive.relative_to(ROOT)),archive_sha256=sha(archive),member=member,
            workbook_absolute_path=str(dest.resolve()),workbook_sha256=sha(dest),release='Final/FinalRevision, title retained; retrieval recorded in download manifest')
        extracted.append(src)
        wb=openpyxl.load_workbook(dest,read_only=True,data_only=True)
        g=scan(wb,'Page 1 Generation and Fuel Data',targets,src)
        f=scan(wb,'Page 6 Plant Frame',targets,src)
        wb.close()
        annual.append(dict(year=year,generation=g,plant_frame=f))
        for code in sorted(targets,key=int):
            rows=[r for r in g['selected_rows'] if r['plant_code']==code]
            frames=[r for r in f['selected_rows'] if r['plant_code']==code]
            lfg,ls=aggregate(rows,'LFG');allfuel,ats=aggregate(rows)
            coverage.append(dict(year=year,plant_code=int(code),raw_allfuel_rows=len(rows),raw_lfg_rows=sum(r['fields']['Reported Fuel Type Code']=='LFG' for r in rows),
                raw_fuel_codes=';'.join(sorted({str(r['fields']['Reported Fuel Type Code']) for r in rows})),
                raw_prime_movers=';'.join(sorted({str(r['fields']['Reported Prime Mover']) for r in rows})),
                lfg_net_generation_MWh=lfg,lfg_status=ls,allfuel_net_generation_MWh=allfuel,allfuel_status=ats,
                frame_records=len(frames),frame_frequency=';'.join(str(r['fields'].get('Respondent Frequency',r['fields'].get('Reporting Frequency',''))) for r in frames),
                source_check='FULL_LOCAL_FINAL_ANNUAL_MAINLAND_GENERATION_AND_FRAME_SHEETS_CHECKED',
                generation_excel_rows=';'.join(str(r['excel_row']) for r in rows),frame_excel_rows=';'.join(str(r['excel_row']) for r in frames),
                workbook=str(dest.relative_to(ROOT)),generation_sheet=g['sheet'],frame_sheet=f['sheet'],
                interpretation='No row is not zero; complete source-sheet check is not an all-site physical audit'))
        print(json.dumps(dict(year=year,raw_generation_rows=g['rows_with_plant_id'],raw_frame_rows=f['rows_with_plant_id'],matched_rows=len(g['selected_rows']),machine_seconds=time.perf_counter()-started)),flush=True)
        assert time.perf_counter()-started<300,'Scoped runtime limit exceeded; keep partial log'
    api=load(ROOT/config['inputs']['generation'])['response']['data']
    deltas=[]
    for r in coverage:
        matches=[a for a in api if str(a['plantCode'])==str(r['plant_code']) and str(a['period'])==str(r['year'])]
        assert len(matches)<=1
        old=number(matches[0]['generation']) if matches else None;new=r['lfg_net_generation_MWh']
        status='BOTH_MISSING_CONFIRMED_ORIGINAL_SHEET' if old is None and new is None else 'UNCHANGED' if old==new else 'DIFFERENT'
        deltas.append(dict(plant_code=r['plant_code'],year=r['year'],api_MWh=old,annual_original_MWh=new,status=status))
    write(out/'ORIGINAL_ANNUAL_ROWS.json',dict(scope='Allfuel raw rows for8existing plant leads; not new sites or verified landfill allocation',years=annual))
    write(out/'ANNUAL_COVERAGE.json',dict(rows=coverage,units='MWh net generation',absent_rows_are_zero=False))
    write(out/'API_ORIGINAL_COMPARISON.json',dict(rows=deltas,status_counts=dict(Counter(r['status'] for r in deltas))))
    write(out/'EXTRACTED_MEMBERS.json',dict(scope='Only official specifically inspected generationworkbook members extracted; other archive members remainunread',rows=extracted))
    with (out/'ANNUAL_COVERAGE.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(coverage[0]));w.writeheader();w.writerows(coverage)
    assert all(sha(ROOT/k)==v for k,v in before.items())
    code=Path(__file__);(out/'CODE_SNAPSHOT.py').write_bytes(code.read_bytes())
    write(out/'RUN_RECORD.json',dict(utc=datetime.now(timezone.utc).isoformat(),command=[sys.executable,*sys.argv],python=sys.version,platform=platform.platform(),
        packages={'openpyxl':importlib.metadata.version('openpyxl')},input_sha256=before,code_sha256=sha(code),git_state='No rootGit; codebytes/inputSHA recorded',
        random_seed=config['frozen_seed'],split='Fixed8coverage audit, no fitting or new cases',paid_cost=0,network_calls=0,
        elapsed_machine_wall_seconds=time.perf_counter()-started,human_hours=None,cumulative_human_hours=None,remaining_human_hours=None,
        checks=dict(years=10,plant_years=len(coverage),no_zero_imputation=True,all_originals_unchanged=True),
        outputs={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(dict(run=str(out),coverage_rows=len(coverage),comparison=dict(Counter(r['status'] for r in deltas)))),flush=True)


if __name__=='__main__':main()
