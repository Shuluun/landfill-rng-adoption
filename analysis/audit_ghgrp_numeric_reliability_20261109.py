"""GHGRP Subpart HH numeric-reliability audit (item 2 in the consequence line).

The consequence (additionality) line rests on three GHGRP fields:
  annl_avg_methane_concentration  (%)
  annual_landfill_gas_flow        (volume)
  annual_qty_recoverd_ch4_eq_hh4  (recovered CH4)
Prior audits covered completeness, wet/dry basis, and the identity residual
(recovered != flow x conc exactly). This script audits the VALUES themselves:
  1. units / mass-conservation constant (pin flow=scf, rec=mt CH4, conc=%);
  2. physical plausibility bounds (concentration range, implied efficiency in [0,1]);
  3. whether implausible rows concentrate in treated (adopter) vs control facilities;
  4. the HH-6 "generated" model field vs measured recovery (model under-prediction
     is a known GHGRP artifact, NOT a recovery-field error).

Read-only; deterministic; new run dir. Stdlib + numpy/pandas.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
NON_RNG_USE = {'Electricity', 'Direct'}

# CH4 density at standard conditions: 0.717 kg/m3 = 0.0203 kg/scf = 2.03e-5 mt/scf
CH4_DENSITY_MT_PER_SCF = 2.03e-5
# log(rec) - log(flow_scf) - log(conc_pct) = log(density/100) + log(eff)
# = ln(2.03e-7) = -15.41  for eff=1
MASS_CONST_EXPECTED = float(np.log(CH4_DENSITY_MT_PER_SCF / 100.0))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def basis_of(s):
    s = s.astype(str).str.strip().str.upper()
    out = pd.Series('missing', index=s.index)
    out[s.eq('Y')] = 'wet'
    out[s.eq('N')] = 'dry'
    out[s.isin(['NAN', 'NONE', 'NULL', '', '<NA>'])] = 'missing'
    return out


def build_treated_control(df):
    """Map each GHGRP facility_id to treated / control / excluded, reusing the
    consequence-line logic (ever-operational PI-RNG adopter = treated; no RNG at all
    = control; RNG but not PI, or non-operational, = excluded)."""
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))
    pi_lf = set(adopt.index.astype(int))
    rng_any_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))

    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    # ever-operational status per landfill (treated must be Operational/Shutdown)
    lf_flag = {}
    for lid in pi_lf:
        rows = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = rows[rows['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = set(pi_rows['Current Project Status'].astype(str).str.strip())
        ever_op = bool(statuses & {'Operational', 'Shutdown'})
        lf_flag[lid] = ever_op

    fac_role = {}
    for f, lids in fac2lf.items():
        treated = any(l in pi_lf and lf_flag.get(l, False) for l in lids)
        rng_any = any(l in rng_any_lf for l in lids)
        if treated:
            fac_role[f] = 'treated'
        elif rng_any:
            fac_role[f] = 'excluded'
        else:
            fac_role[f] = 'control'
    return fac_role


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
    gh = pd.read_csv(GHGRP, dtype={'facility_id': 'Int64'})

    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['hh6'] = pd.to_numeric(gh['equation_hh6_result'], errors='coerce')
    gh['basis'] = basis_of(gh['ch4_conc_measured_wet_basis'])
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    fac_role = build_treated_control(df)
    gh['role'] = gh['fac'].map(fac_role).fillna('unmapped')

    n = len(gh)

    # ---- 1. units / mass-conservation constant ----
    ok_mass = (gh['conc'] > 0) & (gh['flow'] > 0) & (gh['rec'] > 0)
    resid = np.log(gh.loc[ok_mass, 'rec']) - np.log(gh.loc[ok_mass, 'flow']) - np.log(gh.loc[ok_mass, 'conc'])
    mass_conservation = {
        'n_rows': int(ok_mass.sum()),
        'resid_mean': float(resid.mean()),
        'resid_median': float(resid.median()),
        'resid_std': float(resid.std()),
        'resid_p1': float(resid.quantile(0.01)),
        'resid_p99': float(resid.quantile(0.99)),
        'expected_constant_ln(density/100)': MASS_CONST_EXPECTED,
        'implied_efficiency_at_mean': float(np.exp(resid.mean() - MASS_CONST_EXPECTED)),
        'units_verdict': ('flow=scf/yr, rec=mt CH4/yr, conc=%' if abs(resid.mean() - MASS_CONST_EXPECTED) < 0.5
                          else 'MISMATCH - inspect units'),
    }

    # ---- 2. concentration bounds ----
    c = gh['conc']
    conc_bounds = {
        'n_total': int(c.notna().sum()),
        'in_20_60': int(((c >= 20) & (c <= 60)).sum()),
        'frac_in_20_60': float(((c >= 20) & (c <= 60)).mean()),
        'gt_70_implausible': int((c > 70).sum()),
        'le_5_near_zero': int(((c >= 0) & (c <= 5)).sum()),
        'max': float(c.max()),
    }
    conc_implausible_rows = gh[c > 70][['fac', 'facility_name', 'year', 'conc', 'basis', 'role']].to_dict('records')

    # ---- 3. implied efficiency bounds ----
    eff = gh.loc[ok_mass, 'rec'] / (gh.loc[ok_mass, 'flow'] * gh.loc[ok_mass, 'conc'] / 100 * CH4_DENSITY_MT_PER_SCF)
    eff_bounds = {
        'n_rows': int(ok_mass.sum()),
        'median': float(eff.median()),
        'p90': float(eff.quantile(0.90)),
        'p99': float(eff.quantile(0.99)),
        'max': float(eff.max()),
        'eff_gt_1_impossible': int((eff > 1).sum()),
        'eff_gt_1_5': int((eff > 1.5).sum()),
        'eff_lt_0_01': int((eff < 0.01).sum()),
    }
    # dirty rows = implied efficiency physically impossible (eff > 1) or near-zero (eff < 0.01)
    dirty_mask = (eff > 1) | (eff < 0.01)
    gh_dirty = gh.loc[ok_mass].copy()
    gh_dirty['eff'] = eff
    gh_dirty['dirty'] = dirty_mask

    # ---- 4. dirty-row concentration in treated vs control ----
    dirty_by_role = {}
    role_rows = {}
    for role in ['treated', 'control', 'excluded', 'unmapped']:
        r = gh_dirty[gh_dirty['role'] == role]
        role_rows[role] = int(len(r))
        dirty_by_role[role] = {
            'n_facility_years': int(len(r)),
            'n_dirty': int(r['dirty'].sum()),
            'frac_dirty': float(r['dirty'].mean()) if len(r) else None,
        }

    # ---- 5. HH-6 generated-model field vs measured recovery ----
    ok66 = (gh['rec'] > 0) & (gh['hh6'] > 0)
    ratio = gh.loc[ok66, 'rec'] / gh.loc[ok66, 'hh6']
    hh6_analysis = {
        'n_rows': int(ok66.sum()),
        'frac_rec_gt_generated': float((gh.loc[ok66, 'rec'] > gh.loc[ok66, 'hh6']).mean()),
        'ratio_median': float(ratio.median()),
        'ratio_p90': float(ratio.quantile(0.90)),
        'ratio_max': float(ratio.max()),
        'interpretation': ('HH-6 is the HH-1 MODEL generation; recovery is MEASURED. '
                           'rec>generated is the known model-underprediction artifact, '
                           'not a recovery-field error.'),
    }

    # ---- 6. flow upper tail plausibility ----
    f = gh['flow']
    flow_bounds = {
        'median_scf': float(f.median()),
        'p99_scf': float(f.quantile(0.99)),
        'max_scf': float(f.max()),
        'gt_5e9_scf': int((f > 5e9).sum()),
        'max_m3_per_yr': float(f.max() / 35.315),
    }

    # ---- 7. does basis explain eff>1? (wet-basis conc is ~5% lower than dry, biasing eff up) ----
    gh_dirty['basis'] = gh.loc[ok_mass, 'basis'].to_numpy()
    basis_vs_eff = {}
    for b in ['wet', 'dry', 'missing']:
        sub = gh_dirty[gh_dirty['basis'] == b]
        basis_vs_eff[b] = {
            'n': int(len(sub)),
            'frac_eff_gt_1': float((sub['eff'] > 1).mean()) if len(sub) else None,
            'median_eff': float(sub['eff'].median()) if len(sub) else None,
        }

    # ---- write dirty rows table (facility, year, conc, flow, rec, eff, basis, role) ----
    dirty_cols = ['fac', 'facility_name', 'year', 'conc', 'flow', 'rec', 'eff', 'basis', 'role']
    gh_dirty[dirty_cols].sort_values('eff', ascending=False).to_csv(
        out / 'dirty_rows_sorted_by_eff.csv', index=False, encoding='utf-8-sig')

    # concentration implausible rows
    pd.DataFrame(conc_implausible_rows).to_csv(
        out / 'concentration_implausible_rows.csv', index=False, encoding='utf-8-sig')

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'ch4_density_mt_per_scf': CH4_DENSITY_MT_PER_SCF,
        'n_total_rows': int(n),
        'mass_conservation': mass_conservation,
        'concentration_bounds': conc_bounds,
        'implied_efficiency': eff_bounds,
        'dirty_rows_by_role': dirty_by_role,
        'role_facility_year_counts': role_rows,
        'hh6_generated_model': hh6_analysis,
        'flow_bounds': flow_bounds,
        'basis_vs_eff': basis_vs_eff,
    }
    (out / 'ghgrp_numeric_reliability_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
