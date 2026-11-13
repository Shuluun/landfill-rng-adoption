"""Extract the full never_operational roster (36) with local worksheet context,
flag the 10 already externally verified, and emit the 26 to-verify list.

Read-only. Reuses the exact frame-classification logic from
build_adoption_date_validation_sample_20261109.py so the roster matches the
sampling frame (145 RNG pipeline-injection adoption set, valid start year
1995-2024, min start year per Landfill ID).
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import io, zipfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
AGG = ROOT / 'data/raw/2026-10-06_public_inputs/opprjslmopdata-aggregated.xlsx'
ZIP = ROOT / 'inputs/public/topic_selection_2026-10-20/root_sources/national_lmopdata_files_2001-2023.zip'
SNAP = ['2013Aug_lmopdata.xlsx', '2018Sep_lmopdata.xlsx', '2023Jul_lmopdata.xlsx']

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
NON_RNG_USE = {'Electricity', 'Direct'}

# the 10 never_operational facilities already verified in the 30-facility sample
VERIFIED_10 = {688, 816, 1223, 1819, 2001, 2048, 2323, 2429, 10407, 12144}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def s(v):
    return None if pd.isna(v) else str(v)


def rng_pi_rows_of(dframe, lid):
    sub = dframe[dframe['Landfill ID'].astype(int) == lid]
    is_pi = sub['RNG Delivery Method'].eq('Pipeline Injection') if 'RNG Delivery Method' in sub.columns else pd.Series(False, index=sub.index)
    is_rng = sub['Project Type Category'].eq(RNG_CATEGORY) if 'Project Type Category' in sub.columns else pd.Series(False, index=sub.index)
    if 'RNG Delivery Method' in sub.columns:
        is_rng = is_rng | sub['RNG Delivery Method'].isin(RNG_METHODS)
    return sub[is_rng & is_pi]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    agg = pd.read_excel(AGG, sheet_name='LMOP Database')
    agg['Landfill ID'] = pd.to_numeric(agg['Landfill ID'], errors='coerce')

    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda x: int(min(x)))

    zf = zipfile.ZipFile(ZIP)
    hist_frames = {}
    for name in SNAP:
        try:
            h = pd.read_excel(io.BytesIO(zf.read(name)), sheet_name='LMOP Database')
            h['Landfill ID'] = pd.to_numeric(h['Landfill ID'], errors='coerce')
            hist_frames[name] = h
        except Exception as e:
            hist_frames[name] = None

    rows = []
    for lid in adopt.index:
        lid = int(lid)
        Ti = int(adopt[lid])
        r = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = r[r['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = sorted(set(pi_rows['Current Project Status'].astype(str).str.strip()))
        ever_op = bool(set(statuses) & {'Operational', 'Shutdown'})
        other = r[r['Project Type Category'].isin(NON_RNG_USE)]
        oy = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((oy < Ti).any())
        if ever_op:
            continue  # we only want never_operational
        prior_use_desc = None
        if prior_use:
            pu = other[pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year < Ti]
            prior_use_desc = '; '.join(
                f"{s(x['Project Type Category'])}@{int(pd.to_datetime(x['Project Start Date'], errors='coerce').year)}"
                for _, x in pu.iterrows())
        first = r.iloc[0]
        snap_years = {}
        for name in SNAP:
            h = hist_frames[name]
            if h is None:
                snap_years[name] = 'unreadable'
                continue
            rr = rng_pi_rows_of(h, lid)
            if len(rr) == 0:
                snap_years[name] = 'none'
            else:
                yrs = pd.to_datetime(rr['Project Start Date'], errors='coerce').dt.year.dropna()
                sts = ','.join(sorted(set(rr['Current Project Status'].astype(str).str.strip())))
                snap_years[name] = f"{','.join(str(int(y)) for y in sorted(set(yrs)))} [{sts}]" if len(yrs) else f"no-date [{sts}]"
        agg_rows = []
        if lid in set(agg['Landfill ID']):
            for _, a in agg[agg['Landfill ID'] == lid].iterrows():
                agg_rows.append(f"{s(a.get('Parent Project ID'))}|{s(a.get('Initial Project Start Date'))}|{s(a.get('Project Type Category'))}")
        pid_start = '; '.join(
            f"{s(x.get('Project ID'))}={s(x.get('Project Start Date'))}" for _, x in pi_rows.iterrows())
        rows.append({
            'Landfill ID': lid,
            'GHGRP ID': None if pd.isna(first.get('GHGRP ID')) else int(first['GHGRP ID']),
            'Landfill Name': first.get('Landfill Name'),
            'State': first.get('State'),
            'County': first.get('County'),
            'Year Landfill Opened': None if pd.isna(first.get('Year Landfill Opened')) else int(first['Year Landfill Opened']),
            'Ti': Ti, 'type': 'never_operational',
            'rng_pi_statuses': ','.join(statuses),
            'rng_pi_pid_start': pid_start,
            'prior_use': prior_use_desc,
            'historical_rng_pi_2013Aug': snap_years[SNAP[0]],
            'historical_rng_pi_2018Sep': snap_years[SNAP[1]],
            'historical_rng_pi_2023Jul': snap_years[SNAP[2]],
            'aggregated_parent_rows': '; '.join(agg_rows),
        })

    fr = pd.DataFrame(rows).sort_values('Landfill ID').reset_index(drop=True)
    fr['already_verified_in_30'] = fr['Landfill ID'].isin(VERIFIED_10)

    # external verification columns (empty for the 26 to-verify)
    for c in ['ext_first_gas_year', 'ext_first_gas_date', 'ext_source_type',
              'ext_source_url', 'ext_verdict', 'ext_contamination_type', 'ext_notes']:
        fr[c] = ''

    fr.to_csv(out / 'never_operational_full_36.csv', index=False, encoding='utf-8-sig')
    to_verify = fr[~fr['already_verified_in_30']].copy().reset_index(drop=True)
    to_verify.to_csv(out / 'never_operational_to_verify_26.csv', index=False, encoding='utf-8-sig')

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'agg_sha256': sha(AGG), 'zip_sha256': sha(ZIP),
        'script_sha256': sha(__file__), 'synthetic_data_used': False,
        'n_never_operational_frame': int(len(fr)),
        'n_already_verified': int(fr['already_verified_in_30'].sum()),
        'n_to_verify': int(len(to_verify)),
        'to_verify_ids': [int(x) for x in to_verify['Landfill ID']],
        'already_verified_ids': sorted(int(x) for x in fr[fr['already_verified_in_30']]['Landfill ID']),
    }
    (out / 'never_operational_26_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    md = ['# never_operational 全名单（36 场）与待核验 26 场工作底稿', '',
          f'- 抽样框 never_operational 格共 **{len(fr)}** 场（全部 late>=2019，Ti=2024）。',
          f'- 已核验 {int(fr["already_verified_in_30"].sum())} 场（30 场样本内），待核验 **{len(to_verify)}** 场。', '']
    for _, r in to_verify.iterrows():
        md.append(f"## LF {r['Landfill ID']} — {r['Landfill Name']} ({r['State']}, {r['County']})  ·  GHGRP {r['GHGRP ID']}")
        md.append(f"- Ti = {r['Ti']}  ·  场址开业 {r['Year Landfill Opened']}  ·  当前 RNG-PI 状态 = {r['rng_pi_statuses']}")
        md.append(f"- 项目行 = {r['rng_pi_pid_start']}")
        if r['prior_use'] and str(r['prior_use']) != 'nan':
            md.append(f"- 此前非 RNG 用途 = {r['prior_use']}")
        md.append(f"- 历史快照：2013Aug {r['historical_rng_pi_2013Aug']} · 2018Sep {r['historical_rng_pi_2018Sep']} · 2023Jul {r['historical_rng_pi_2023Jul']}")
        if r['aggregated_parent_rows'] and str(r['aggregated_parent_rows']) != 'nan':
            md.append(f"- 聚合项目(Parent Project ID=扩建)：{r['aggregated_parent_rows']}")
        md.append('')
    (out / 'never_operational_to_verify_26_worksheet.md').write_text('\n'.join(md), encoding='utf-8')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
