"""Build the adoption-date external-validation SAMPLE + worksheet (>=30 facilities).

Purpose (reviewer priority #1): the treatment/adoption dates in BOTH research lines
(driver-side hazard model AND consequence-side DiD) come from the LMOP registry start
date, which the 6-facility blind audit already showed is contaminated three ways
(Planned/Construction-as-adopted; prior-use switch counted as new adoption; date drift
across snapshots). This script draws a reproducible, outcome-blind, stratified random
sample of the RNG pipeline-injection adoption set, and emits (a) a CSV sample list,
(b) a per-facility worksheet pre-filled with the LOCAL LMOP records (current + historical
snapshots + expansion/aggregated table) so an external verifier has everything in hand,
and (c) a design summary. External verification (operator press release, permit, first
gas-injection) is NOT performed here — those are empty columns to fill in later.

Selection is outcome-blind: no concentration/recovery/flow value is consulted. Read-only.
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

SEED = 20261109
TARGET_N = 30
MIN_PER_STRATUM = 3


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sanitize(o):
    if isinstance(o, dict):
        return {k: sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
        return None
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def s(v):
    """compact str, None for NA"""
    return None if pd.isna(v) else str(v)


def rng_pi_rows_of(dframe, lid):
    """RNG pipeline-injection project rows for a landfill (current or historical)."""
    sub = dframe[dframe['Landfill ID'].astype(int) == lid]
    is_pi = sub['RNG Delivery Method'].eq('Pipeline Injection') if 'RNG Delivery Method' in sub.columns else pd.Series(False, index=sub.index)
    is_rng = sub['Project Type Category'].eq(RNG_CATEGORY) if 'Project Type Category' in sub.columns else pd.Series(False, index=sub.index)
    if 'RNG Delivery Method' in sub.columns:
        is_rng = is_rng | sub['RNG Delivery Method'].isin(RNG_METHODS)
    mask = is_rng & is_pi
    return sub[mask]


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

    # ---- adoption set (RNG pipeline-injection, valid year, min per landfill) ----
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda x: int(min(x)))

    # ---- per-landfill classification ----
    records = []
    for lid in adopt.index:
        lid = int(lid)
        Ti = int(adopt[lid])
        rows = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = rows[rows['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = sorted(set(pi_rows['Current Project Status'].astype(str).str.strip()))
        ever_op = bool(set(statuses) & {'Operational', 'Shutdown'})
        other = rows[rows['Project Type Category'].isin(NON_RNG_USE)]
        oy = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((oy < Ti).any())
        prior_use_desc = None
        if prior_use:
            pu = other[pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year < Ti]
            prior_use_desc = '; '.join(
                f"{s(r['Project Type Category'])}@{int(pd.to_datetime(r['Project Start Date'], errors='coerce').year)}"
                for _, r in pu.iterrows())
        if not ever_op:
            typ = 'never_operational'
        elif prior_use:
            typ = 'switch'
        else:
            typ = 'new'
        era = 'early<=2014' if Ti <= 2014 else ('mid2015-2018' if Ti <= 2018 else 'late>=2019')
        first = rows.iloc[0]
        rng_pi_cur = pi_rows
        pid_start = '; '.join(
            f"{s(r.get('Project ID'))}={s(r.get('Project Start Date'))}"
            for _, r in rng_pi_cur.iterrows())
        records.append({
            'Landfill ID': lid,
            'GHGRP ID': None if pd.isna(first.get('GHGRP ID')) else int(first['GHGRP ID']),
            'Landfill Name': first.get('Landfill Name'),
            'State': first.get('State'),
            'County': first.get('County'),
            'Year Landfill Opened': None if pd.isna(first.get('Year Landfill Opened')) else int(first['Year Landfill Opened']),
            'Ti': Ti, 'era': era, 'type': typ,
            'rng_pi_statuses': ','.join(statuses),
            'rng_pi_pid_start': pid_start,
            'prior_use': prior_use_desc,
        })

    fr = pd.DataFrame(records)
    fr['stratum'] = fr['era'] + ' / ' + fr['type']

    # ---- stratified random sample (outcome-blind) ----
    rng = np.random.default_rng(SEED)
    strata = sorted(fr['stratum'].unique())
    sizes = {st: int((fr['stratum'] == st).sum()) for st in strata}

    # allocation: min per non-empty stratum, then proportional fill to TARGET_N
    alloc = {st: min(MIN_PER_STRATUM, sizes[st]) for st in strata}
    while sum(alloc.values()) < TARGET_N:
        # add one to the largest stratum still under its size (largest-remainder-ish)
        candidates = [st for st in strata if alloc[st] < sizes[st]]
        if not candidates:
            break
        st = max(candidates, key=lambda s: (sizes[s] - alloc[s], sizes[s]))
        alloc[st] += 1

    sampled = []
    for st in strata:
        g = fr[fr['stratum'] == st].sort_values('Landfill ID')
        idx = rng.choice(g.index.to_numpy(), size=alloc[st], replace=False)
        sampled.append(g.loc[np.sort(idx)])
    sample = pd.concat(sampled).reset_index(drop=True)
    sample = sample.sort_values(['era', 'type', 'Landfill ID']).reset_index(drop=True)
    sample['sample_rank'] = sample.index + 1

    # ---- historical snapshot context (drift detection) for sampled facilities ----
    zf = zipfile.ZipFile(ZIP)
    hist_frames = {}
    for name in SNAP:
        try:
            h = pd.read_excel(io.BytesIO(zf.read(name)), sheet_name='LMOP Database')
            h['Landfill ID'] = pd.to_numeric(h['Landfill ID'], errors='coerce')
            hist_frames[name] = h
        except Exception as e:
            hist_frames[name] = None

    agg['Landfill ID'] = pd.to_numeric(agg['Landfill ID'], errors='coerce')

    sample_rows = []
    for _, r in sample.iterrows():
        lid = int(r['Landfill ID'])
        # historical RNG-PI start years (drift)
        snap_years = {}
        for name, h in hist_frames.items():
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
        # aggregated (expansion) rows
        agg_rows = []
        if lid in set(agg['Landfill ID']):
            for _, a in agg[agg['Landfill ID'] == lid].iterrows():
                agg_rows.append(f"{s(a.get('Parent Project ID'))}|{s(a.get('Initial Project Start Date'))}|{s(a.get('Project Type Category'))}")
        sample_rows.append({
            **{k: r[k] for k in ['sample_rank', 'Landfill ID', 'GHGRP ID', 'Landfill Name', 'State', 'County',
                                  'Year Landfill Opened', 'Ti', 'era', 'type', 'rng_pi_statuses', 'rng_pi_pid_start', 'prior_use']},
            'historical_rng_pi_2013Aug': snap_years.get(SNAP[0], ''),
            'historical_rng_pi_2018Sep': snap_years.get(SNAP[1], ''),
            'historical_rng_pi_2023Jul': snap_years.get(SNAP[2], ''),
            'aggregated_parent_rows': '; '.join(agg_rows),
            # external verification columns (to fill in later; empty now)
            'ext_first_gas_year': '', 'ext_first_gas_date': '', 'ext_source_type': '',
            'ext_source_url': '', 'ext_verdict': '', 'ext_contamination_type': '', 'ext_notes': '',
        })

    out_csv = pd.DataFrame(sample_rows)
    out_csv.to_csv(out / 'adoption_date_validation_sample.csv', index=False, encoding='utf-8-sig')

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'agg_sha256': sha(AGG), 'zip_sha256': sha(ZIP),
        'script_sha256': sha(__file__),
        'random_seed': SEED, 'synthetic_data_used': False,
        'frame_note': 'RNG pipeline-injection adoption set (valid start year 1995-2024, min per Landfill ID)',
        'frame_size': int(len(fr)),
        'stratum_sizes': sizes,
        'allocation': alloc,
        'target_n': TARGET_N, 'min_per_stratum': MIN_PER_STRATUM,
        'actual_n': int(len(sample)),
        'type_counts_frame': {t: int((fr['type'] == t).sum()) for t in sorted(fr['type'].unique())},
        'era_counts_frame': {e: int((fr['era'] == e).sum()) for e in sorted(fr['era'].unique())},
        'sampled_ids': [int(x) for x in sample['Landfill ID']],
        'external_verification_checklist': [
            'operator / RNG developer press release with actual first-gas or commercial-operation date',
            'state environmental agency permit / construction-to-operation record',
            'pipeline interconnection agreement / first gas-injection date',
            'EPA GHGRP Subpart HH first reported year (for consequence line)',
            'cross-check whether facility had PRIOR gas use (electricity/flare) before Ti',
            'NOT performed here - local records only',
        ],
    }
    (out / 'adoption_date_validation_sample_summary.json').write_text(
        json.dumps(sanitize(summary), ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')

    # human-readable worksheet
    md = ['# 采纳日期外部核验 · 抽样清单与逐场工作表',
          '',
          f'- 抽样框：RNG 管道注入采纳集合（有效起始年 1995–2024，按 Landfill ID 取最早年）= {len(fr)} 场',
          f"- 分层：era(3) × type(3: new / switch / never_operational)，stratum 大小 {sizes}",
          f"- 分配：每非空 stratum 至少 {MIN_PER_STRATUM} 场 + 按规模比例补足至 {TARGET_N} 场；seed={SEED}",
          f"- 实际抽样：{len(sample)} 场（outcome-blind，未看任何浓度/回收/气量结局）",
          f"- 本地 LMOP 记录已预填；外部核验列为空待填。",
          '']
    for _, r in out_csv.iterrows():
        md.append(f"## {r['sample_rank']}. {r['Landfill Name']} (LF {r['Landfill ID']}, GHGRP {r['GHGRP ID']}) — {r['State']}, {r['County']}")
        md.append(f"- LMOP Ti = {r['Ti']}  ·  era = {r['era']}  ·  type = {r['type']}  ·  场址开业 {r['Year Landfill Opened']}")
        md.append(f"- 当前 RNG-PI 状态 = {r['rng_pi_statuses']}  ·  项目行 = {r['rng_pi_pid_start']}")
        if r['prior_use'] and str(r['prior_use']) != 'nan':
            md.append(f"- 此前非 RNG 用途 = {r['prior_use']}")
        md.append(f"- 历史快照 RNG-PI 起始年：2013Aug {r['historical_rng_pi_2013Aug']} · 2018Sep {r['historical_rng_pi_2018Sep']} · 2023Jul {r['historical_rng_pi_2023Jul']}")
        if r['aggregated_parent_rows'] and str(r['aggregated_parent_rows']) != 'nan':
            md.append(f"- 聚合项目(Parent Project ID=扩建)：{r['aggregated_parent_rows']}")
        md.append(f"- 外部核验（待填）：first-gas 年/日期=__ · 来源=__ · 判定=__ · 污染类型=__")
        md.append('')
    (out / 'adoption_date_validation_worksheet.md').write_text('\n'.join(md), encoding='utf-8')

    print(json.dumps(sanitize(summary), ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
