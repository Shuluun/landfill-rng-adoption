"""Bounded non-spatial name fallback in already-acquired annual plant frames."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,re,sys,time
import openpyxl

ROOT=Path(__file__).resolve().parents[1]
RULES={217:('CA',r'marina landfill|monterey regional waste'),1456:('TX',r'skyline'),
  1479:('TX',r'atasco'),1676:('WI',r'mallard'),1820:('TX',r'tessman'),
  1890:('MI',r'granger.*(?:wood|#?1)|wood (?:road|street)'),1939:('IN',r'rolls.?royce|south.?side'),2207:('WV',r'charleston')}


def main():
    start=time.perf_counter();p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);a=p.parse_args()
    out=(ROOT/a.run_dir).resolve();assert out.is_relative_to(ROOT/'outputs');out.mkdir(parents=True,exist_ok=False)
    root=ROOT/'inputs/public/eia923_annual_2015_2024_2026-10-26/workbooks';rows=[];checks=[];inputs={}
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    cfg=json.loads((ROOT/'config/rng_pilot.json').read_text(encoding='utf-8'))
    for year in range(2015,2025):
        paths=list(root.glob(f'*_{year}_Final*.xlsx'));assert len(paths)==1;src=paths[0];inputs[str(src.relative_to(ROOT))]=sha(src)
        wb=openpyxl.load_workbook(src,read_only=True,data_only=True);ws=wb['Page 6 Plant Frame'];headers=None;scanned=0
        for n,row in enumerate(ws.iter_rows(values_only=True),1):
            if headers is None:
                h={' '.join(str(v).split()):i for i,v in enumerate(row) if v is not None}
                if 'Plant Id' in h:headers=h
                continue
            if row[headers['Plant Id']] is None:continue
            scanned+=1;name=str(row[headers['Plant Name']]);state=str(row[headers['Plant State']]);code=int(row[headers['Plant Id']])
            for fid,(needed_state,regex) in RULES.items():
                if state==needed_state and re.search(regex,name,re.I):
                    rows.append(dict(landfill_id=fid,year=year,plant_code=code,plant_name=name,state=state,
                        original_lead=cfg['cases'][str(fid)]['plant_lead'],is_different_candidate_code=code!=cfg['cases'][str(fid)]['plant_lead'],
                        source=str(src.relative_to(ROOT)),sheet=ws.title,excel_row=n,status='NAME_CANDIDATE_ONLY_NOT_ACCEPTED_PHYSICAL_RELATION'))
        wb.close();checks.append(dict(year=year,frame_rows_scanned=scanned));assert time.perf_counter()-start<150
    d=dict(scope='Same-state named-field fallback for8existingcases only; no generation outcome inspection for new facilities. No rule changes or replacements.',
        rules={str(k):dict(state=v[0],name_pattern=v[1]) for k,v in RULES.items()},rows=rows,coverage=checks,
        additional_candidate_codes=sorted({r['plant_code'] for r in rows if r['is_different_candidate_code']}),
        limits='No match does not exclude unknown aliases, renumbering or non-reporting. Exact source-ID absence is not whole-site absence.')
    (out/'FRAME_NAME_FALLBACK.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'CODE_SNAPSHOT.py').write_bytes(Path(__file__).read_bytes())
    record=dict(utc=datetime.now(timezone.utc).isoformat(),command=[sys.executable,*sys.argv],python=sys.version,openpyxl=openpyxl.__version__,
        input_sha256=inputs,code_sha256=sha(Path(__file__)),random_seed=20261020,split='No fitting or newoutcome evaluation',git_state='No rootGit',
        elapsed_machine_seconds=time.perf_counter()-start,human_hours=None,network_calls=0,paid_cost=0)
    (out/'RUN_RECORD.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({'run':str(out),'metadata_matches':len(rows),'additional_candidate_codes':d['additional_candidate_codes'],'seconds':record['elapsed_machine_seconds']}),flush=True)


if __name__=='__main__':main()
