"""Week-1 denominator gate for RNG-adoption study (Direction 1).

Read-only over the registered Sep2024 LMOP workbook. Establishes, for the
proposed registry-wide RNG adoption regression:
  - population denominator (unique landfills) and its analyzable subset
  - coordinate / gas / waste coverage
  - RNG adoption numerator (binary + adoption year) under a pre-stated definition

No download, no model fitting, no randomness, no causal claim. New run dir each time.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
ADOPT_STATUS = {'Operational', 'Construction', 'Planned'}  # RNG project exists or is committed
ANY_PROJECT_CATEGORY = {'Electricity', 'Direct', 'Renewable Natural Gas'}
POTENTIAL_STATUS = {'Candidate', 'Future Potential', 'Low Potential'}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    lmop_hash = sha(LMOP)

    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    n_rows = len(df)
    n_landfill = df['Landfill ID'].nunique()

    # --- per-landfill aggregates ---
    g = df.groupby('Landfill ID', sort=True).agg(
        state=('State', 'first'),
        county=('County', 'first'),
        lat=('Latitude', 'first'),
        lon=('Longitude', 'first'),
        landfill_status=('Current Landfill Status', 'first'),
        ownership=('Ownership Type', 'first'),
        opened=('Year Landfill Opened', 'first'),
        closure=('Landfill Closure Year', 'first'),
        waste_tons=('Waste in Place (tons)', 'max'),          # one value per landfill; max guards duplicates
        waste_year=('Waste in Place Year', 'first'),
        lfg_collected=('LFG Collected (mmscfd)', 'max'),
        lfg_flared=('LFG Flared (mmscfd)', 'max'),
        lfg_flow_to_project=('LFG Flow to Project (mmscfd)', 'max'),
        n_project_rows=('Project ID', 'count'),
    )
    # RNG flags per landfill
    is_rng_cat = df['Project Type Category'].eq(RNG_CATEGORY)
    is_rng_method = df['RNG Delivery Method'].isin(RNG_METHODS)
    rng_mask = is_rng_cat | is_rng_method
    rng_adopted_mask = rng_mask & df['Current Project Status'].isin(ADOPT_STATUS)
    rng_any_mask = rng_mask & df['Current Project Status'].notna()
    any_project_mask = df['Project Type Category'].isin(ANY_PROJECT_CATEGORY)

    rng = df[rng_mask].groupby('Landfill ID').agg(
        rng_adopted=('Current Project Status', lambda s: bool(set(s) & ADOPT_STATUS)),
        rng_any_status=('Current Project Status', lambda s: bool(set(s.dropna()))),
        rng_statuses=('Current Project Status', lambda s: sorted(set(s.dropna()))),
        rng_delivery=('RNG Delivery Method', lambda s: sorted(set(s.dropna()))),
    )
    rng_year = df[rng_mask].assign(
        yr=pd.to_datetime(df[rng_mask]['Project Start Date'], errors='coerce').dt.year
    ).groupby('Landfill ID')['yr'].min()

    g = g.join(rng, how='left').join(rng_year.rename('rng_start_year'), how='left')
    g['rng_adopted'] = g['rng_adopted'].fillna(False).astype(bool)
    g['rng_any_status'] = g['rng_any_status'].fillna(False).astype(bool)
    g['any_project'] = df[any_project_mask].groupby('Landfill ID')['Project ID'].count().reindex(g.index).notna().astype(bool)

    # coverage
    g['has_coord'] = g[['lat', 'lon']].notna().all(axis=1)
    g['has_waste'] = g['waste_tons'].notna() & (g['waste_tons'] > 0)
    g['has_gas'] = g[['lfg_collected', 'lfg_flow_to_project']].notna().any(axis=1)
    g['has_opened'] = g['opened'].notna()

    # analyzable denominator: drop pure-Unknown sites with no project, no potential, no waste/gas/coord
    has_potential = df[df['Current Project Status'].isin(POTENTIAL_STATUS)].groupby('Landfill ID')['Project ID'].size().reindex(g.index).notna()
    g['analyzable'] = g['any_project'] | has_potential | g['has_waste'] | g['has_gas'] | g['has_coord']

    total = len(g)
    analyzable = g[g['analyzable']]
    rng_adopted = g[g['rng_adopted']]
    rng_adopted_analyzable = analyzable[analyzable['rng_adopted']]

    gate = {
        'rows': n_rows,
        'unique_landfills': total,
        'analyzable_landfills': len(analyzable),
        'coordinate_coverage_all_pct': round(100 * g['has_coord'].mean(), 2),
        'coordinate_coverage_analyzable_pct': round(100 * analyzable['has_coord'].mean(), 2),
        'waste_coverage_all_pct': round(100 * g['has_waste'].mean(), 2),
        'gas_coverage_all_pct': round(100 * g['has_gas'].mean(), 2),
        'opened_year_coverage_all_pct': round(100 * g['has_opened'].mean(), 2),
        'rng_adopted_landfills': int(rng_adopted['rng_adopted'].sum()),
        'rng_adopted_landfills_analyzable': int(rng_adopted_analyzable['rng_adopted'].sum()),
        'rng_any_status_landfills': int(g['rng_any_status'].sum()),
        'rng_landfills_with_start_year': int(rng_year.notna().sum()),
        'non_rng_analyzable_controls': int((analyzable['rng_adopted'] == False).sum()),
        'gate_denominator_pass': bool(len(analyzable) >= 150),
        'gate_coordinate_pass': bool(analyzable['has_coord'].mean() >= 0.70),
        'definition': {
            'rng': f"Project Type Category == '{RNG_CATEGORY}' OR RNG Delivery Method in {sorted(RNG_METHODS)}",
            'adopted_statuses': sorted(ADOPT_STATUS),
            'analyzable': 'any_project OR potential-status OR has_waste OR has_gas OR has_coord',
        },
    }

    # status composition of RNG-adopted sites
    rng_status_rows = df[rng_adopted_mask].groupby('Current Project Status').size().to_dict()
    rng_year_hist = {int(k): int(v) for k, v in rng_year.value_counts().sort_index().items()}
    project_category_rows = df['Project Type Category'].value_counts().to_dict()

    (out / 'landfill_level.csv').write_text(
        g.reset_index().to_csv(index=False), encoding='utf-8-sig')
    summary = {
        'started_utc': started, 'finished_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['pandas', 'numpy', 'openpyxl']},
        'lmop_path': str(LMOP), 'lmop_sha256': lmop_hash,
        'script_sha256': sha(__file__), 'workspace_git_state': 'not_a_git_repository',
        'random_seed': None, 'model_run': False, 'synthetic_data_used': False,
        'input_read_only': True,
        'gate': gate,
        'rng_adopted_status_composition': rng_status_rows,
        'rng_start_year_histogram': rng_year_hist,
        'project_category_row_counts': project_category_rows,
    }
    (out / 'gate_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(gate, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
