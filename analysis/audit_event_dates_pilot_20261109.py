"""Event-date audit PILOT (6 facilities): verify RNG adoption dates and expansion status
from local LMOP records + historical snapshots, selected BLIND to any outcome.

Selection is deterministic and outcome-blind: treated (pipeline-injection RNG) landfills
are stratified by adoption year into three eras, sorted by Landfill ID, and the first two
of each era are chosen. No concentration/recovery value is consulted.

For each selected landfill we report:
  - current (2024-09) LMOP record: project start date, status, type, delivery method,
    landfill opened year, LFG collection in place;
  - aggregated project file: Parent Project ID (=> expansion) and Initial Project Start Date;
  - historical snapshots (2013/2018/2023, .xlsx only): whether an RNG project appears and
    its reported start date/status, to expose event-date drift.

External verification (operator announcement, permit, first gas-injection) is NOT performed
here and is listed as a checklist only. Read-only.
"""
import argparse, datetime as dt, hashlib, json, subprocess, sys, time
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


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def is_rng_project(row):
    cat = str(row.get('Project Type Category', ''))
    meth = str(row.get('RNG Delivery Method', ''))
    etype = str(row.get('LFG Energy Project Type', ''))
    return ('natural gas' in cat.lower()) or (meth.strip() in RNG_METHODS) or \
           ('rng' in cat.lower()) or ('natural gas' in etype.lower())


def sanitize(o):
    """Recursively replace NaN/Inf floats with None so the result is strict JSON."""
    if isinstance(o, dict):
        return {k: sanitize(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [sanitize(v) for v in o]
    if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
        return None
    if o is pd.NA or o is pd.NaT:
        return None
    return o


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

    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))

    # ---- selection (blind to outcome) ----
    lf = pd.DataFrame({'Landfill ID': adopt.index.astype(int), 'Ti': adopt.to_numpy(int)})
    lf['era'] = pd.cut(lf['Ti'], bins=[-1, 2014, 2018, 2100], labels=['early<=2014', 'mid2015-2018', 'late>=2019'])
    selected = []
    for era, g in lf.groupby('era', observed=True):
        for lid in sorted(g['Landfill ID'])[:2]:
            selected.append((int(lid), int(g.loc[g['Landfill ID'] == lid, 'Ti'].iloc[0]), str(era)))
    era_counts = {str(k): int(v) for k, v in lf['era'].value_counts().items()}

    # ---- aggregated lookup by Landfill ID ----
    agg['Landfill ID'] = pd.to_numeric(agg['Landfill ID'], errors='coerce')
    agg_by_lf = {}
    for lid, g in agg.groupby('Landfill ID'):
        agg_by_lf.setdefault(int(lid), []).append(g)

    # ---- historical snapshots ----
    zf = zipfile.ZipFile(ZIP)
    hist = {}
    for name in SNAP:
        try:
            h = pd.read_excel(io.BytesIO(zf.read(name)), sheet_name='LMOP Database')
            h['Landfill ID'] = pd.to_numeric(h['Landfill ID'], errors='coerce')
            hist[name] = h
        except Exception as e:
            hist[name] = None
            print(f'[warn] snapshot {name} unreadable: {e}', file=sys.stderr)

    records = []
    for lid, ti, era in selected:
        cur = df[df['Landfill ID'].astype(int) == lid]
        # RNG project row(s) in current snapshot
        cur_rng = cur[cur.apply(is_rng_project, axis=1)]
        first = cur.iloc[0]
        rng_rows = []
        for _, r in cur_rng.iterrows():
            rng_rows.append({
                'Project ID': None if pd.isna(r.get('Project ID')) else str(r.get('Project ID')),
                'Project Start Date': None if pd.isna(r.get('Project Start Date')) else str(r.get('Project Start Date')),
                'status': r.get('Current Project Status'),
                'type': r.get('Project Type Category'),
                'method': r.get('RNG Delivery Method'),
            })
        # aggregated record for this landfill
        agg_rows = []
        if lid in agg_by_lf:
            for g in agg_by_lf[lid]:
                for _, r in g.iterrows():
                    agg_rows.append({
                        'Parent Project ID': None if pd.isna(r.get('Parent Project ID')) else str(r.get('Parent Project ID')),
                        'Initial Project Start Date': None if pd.isna(r.get('Initial Project Start Date')) else str(r.get('Initial Project Start Date')),
                        'type': r.get('Project Type Category'),
                        'method': r.get('RNG Delivery Method'),
                    })
        # historical presence
        hist_presence = []
        for name, h in hist.items():
            if h is None:
                hist_presence.append({'snapshot': name, 'note': 'unreadable (.xls needs xlrd)'})
                continue
            hh = h[h['Landfill ID'] == lid]
            projects = []
            for _, r in hh.iterrows():
                projects.append({
                    'type': r.get('Project Type Category'),
                    'method': r.get('RNG Delivery Method') if 'RNG Delivery Method' in hh.columns else None,
                    'start': None if pd.isna(r.get('Project Start Date')) else str(r.get('Project Start Date')),
                    'status': r.get('Current Project Status'),
                })
            hist_presence.append({'snapshot': name, 'n_projects': int(len(projects)), 'projects': projects})

        records.append({
            'Landfill ID': lid,
            'GHGRP ID': None if pd.isna(first.get('GHGRP ID')) else int(first['GHGRP ID']),
            'Landfill Name': first.get('Landfill Name'),
            'State': first.get('State'),
            'County': first.get('County'),
            'Year Landfill Opened': None if pd.isna(first.get('Year Landfill Opened')) else int(first['Year Landfill Opened']),
            'LFG Collection In Place (current)': first.get('LFG Collection System In Place?'),
            'adoption_year_Ti': ti, 'era': era,
            'current_rng_project_rows': rng_rows,
            'aggregated_project_rows': agg_rows,
            'historical': hist_presence,
        })

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version,
        'lmop_sha256': sha(LMOP), 'agg_sha256': sha(AGG), 'zip_sha256': sha(ZIP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'selection_note': 'outcome-blind: stratified by adoption era, sorted by Landfill ID, first 2 per era',
        'era_counts_treated': era_counts,
        'selected': records,
        'external_verification_checklist': [
            'operator announcement / press release with actual first-gas or commercial-operation date',
            'permit / construction records (state environmental agency)',
            'pipeline interconnection agreement / first gas-injection date',
            'confirm metering point and report scope (which gas stream is reported to GHGRP)',
            'NOT performed here - local records only',
        ],
    }
    (out / 'audit_event_dates_pilot_summary.json').write_text(
        json.dumps(sanitize(summary), ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')

    # human-readable markdown
    md = ['# Event-date audit pilot (6 facilities, outcome-blind selection)', '',
          f"- selection: stratified by adoption era, sorted by Landfill ID, first 2 per era",
          f"- era counts (treated): {era_counts}",
          f"- external verification checklist: {summary['external_verification_checklist'][:4]} (NOT done)", '']
    for r in records:
        md.append(f"## {r['Landfill Name']} (LF {r['Landfill ID']}, GHGRP {r['GHGRP ID']}) — {r['State']}, {r['County']}")
        md.append(f"- adoption year Ti = {r['adoption_year_Ti']} ({r['era']}); landfill opened {r['Year Landfill Opened']}; LFG collection now: {r['LFG Collection In Place (current)']}")
        md.append("- current RNG project rows:")
        for x in r['current_rng_project_rows']:
            md.append(f"    - PID={x['Project ID']} start={x['Project Start Date']} status={x['status']} type={x['type']} method={x['method']}")
        md.append("- aggregated project rows (Parent Project ID = expansion):")
        for x in r['aggregated_project_rows']:
            md.append(f"    - parent={x['Parent Project ID']} init_start={x['Initial Project Start Date']} type={x['type']} method={x['method']}")
        md.append("- historical snapshots:")
        for h in r['historical']:
            md.append(f"    - {h['snapshot']}: {h.get('note') or (str(h.get('n_projects')) + ' projects ' + str(h.get('projects')))}")
        md.append('')
    (out / 'audit_event_dates_pilot_evidence.md').write_text('\n'.join(md), encoding='utf-8')

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
