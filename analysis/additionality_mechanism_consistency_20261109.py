"""Mechanism channel + physical-consistency audit for the concentration jump.

Uses the SAME tightened treated definition as additionality_stratified_20261109.py
(ever-operational RNG-PI only, split new vs use-switch). Adds three diagnostics:

  1. Missingness of the mechanism columns (number_of_wells, gas_collection_system_capacity,
     est_gas_collection_efficiency, annual_landfill_gas_flow) — printed FIRST, because if
     these are sparse the mechanism channel shrinks and we fall back to (2)/(3).

  2. Mechanism channel (P1): event-study DiD on log(number_of_wells), log(capacity),
     and collection efficiency. If infrastructure/efficiency ALSO jump at adoption,
     the concentration jump is plausibly physical (upgraded collection); if concentration
     jumps alone, it points to a reporting/measurement artifact.

  3. Physical consistency (P2): within-facility the recovered CH4 should equal
     flow x concentration x constant (units/GWP). In logs this identity is units-free:
         demeaned log(rec) == demeaned log(flow) + demeaned log(conc).
     We report the event-study "identity gap"
         gap_k = ev(log_rec)_k - ev(log_flow)_k - ev(log_conc)_k
     and compare it against ev(log_efficiency)_k. A large |gap| at post periods means the
     recovered/flow/concentration relationship breaks at adoption — i.e. the +6.6pp
     concentration jump does not survive into recovered CH4, so it must be explained.

Read-only (LMOP + GHGRP). Association, not causal.
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

# flow(scf) * conc(%) * 5.074e-6 = recovered CH4 (t CO2e), assuming GWP=25 and
# CH4 density 0.7168 kg/m3 at STP. Constant is only for the level sanity check;
# the headline identity check works in logs where the constant cancels.
IMPLIED_CONST = 5.074e-6


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def demean(df, cols, group):
    g = df.groupby(group)[cols].transform('mean')
    return df[cols].to_numpy(float) - g.to_numpy(float)


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_se(X, y, beta, clusters, g=1.0):
    e = y - X @ beta
    score = X * e[:, None]
    H = X.T @ X
    meat = np.zeros((X.shape[1], X.shape[1]))
    for c in np.unique(clusters):
        sc = score[clusters == c].sum(axis=0)
        meat += np.outer(sc, sc)
    Hinv = np.linalg.pinv(H)
    v = Hinv @ meat @ Hinv
    dof = (len(np.unique(clusters)) / (len(np.unique(clusters)) - 1.0)) * g
    return np.sqrt(np.clip(np.diag(v) * dof, 0, None))


def residualize_slope(df, cols, group, time_col):
    df = df.reset_index(drop=True)
    out = demean(df, cols, group)
    t = df[time_col].to_numpy(float)
    res = np.zeros_like(out)
    dfd = df.copy()
    for c in cols:
        dfd[c] = out[:, cols.index(c)]
    for name, g in dfd.groupby(group):
        idx = g.index.to_numpy()
        tg = t[idx] - t[idx].mean()
        tt = float((tg * tg).sum())
        if tt <= 1e-12:
            res[idx, :] = g[cols].to_numpy(float)
            continue
        for j, c in enumerate(cols):
            col = g[c].to_numpy(float)
            b = float(col @ tg) / tt
            res[idx, j] = col - b * tg
    return res


def basis_of(s):
    s = s.astype(str).str.strip().str.upper()
    out = pd.Series('missing', index=s.index)
    out[s.eq('Y')] = 'wet'
    out[s.eq('N')] = 'dry'
    out[s.isin(['NAN', 'NONE', 'NULL', '', '<NA>'])] = 'missing'
    return out


def ev_bin(k):
    if k is None or (isinstance(k, float) and np.isnan(k)):
        return None
    k = int(k)
    if k <= -5: return 'pre_le_-5'
    if k == -1: return 'ref'
    if k >= 4: return 'post_ge_4'
    return f'k{k}'


EV_LEVELS = ['pre_le_-5', 'k-4', 'k-3', 'k-2', 'k0', 'k1', 'k2', 'k3', 'post_ge_4']


def run_models(panel, outcome, with_wet, wet_col='wet'):
    """panel: facility-year rows with facility_id, year, wet, treated, post, event_time, control, and `outcome` col."""
    from math import erf
    norm_cdf = lambda x: 0.5 * (1 + erf(x / np.sqrt(2)))
    keep = panel.copy()
    years_sorted = sorted(keep['year'].unique())
    yr_dummies = [f'yr_{t}' for t in years_sorted[1:]]
    for t in years_sorted[1:]:
        keep[f'yr_{t}'] = (keep['year'] == t).astype(int)
    base = ([wet_col] if with_wet else []) + yr_dummies

    # TWFE
    X_cols = base + ['post']
    d = demean(keep, X_cols + [outcome], 'facility_id')
    X = d[:, :len(X_cols)]; yw = d[:, len(X_cols)]
    beta = ols(X, yw); se = cluster_se(X, yw, beta, keep['facility_id'].to_numpy())
    tau = float(beta[X_cols.index('post')]); tau_se = float(se[X_cols.index('post')])
    tau_p = float(2 * (1 - norm_cdf(abs(tau / tau_se))))

    # event study
    keep['ev'] = keep['event_time'].apply(ev_bin)
    for lv in EV_LEVELS:
        keep[f'ev_{lv}'] = ((keep['ev'] == lv) & (keep['treated'] == 1)).astype(int)
    ev_cols = [f'ev_{lv}' for lv in EV_LEVELS]
    cols2 = base + ev_cols
    d2 = demean(keep, cols2 + [outcome], 'facility_id')
    X2 = d2[:, :len(cols2)]; yw2 = d2[:, len(cols2)]
    beta2 = ols(X2, yw2); se2 = cluster_se(X2, yw2, beta2, keep['facility_id'].to_numpy())
    ev = {c: {'coef': float(beta2[cols2.index(c)]), 'se': float(se2[cols2.index(c)])} for c in ev_cols}

    # trend-adjusted
    cols3 = base + ['post']
    Z = residualize_slope(keep, cols3 + [outcome], 'facility_id', 'year')
    X3 = Z[:, :len(cols3)]; y3 = Z[:, len(cols3)]
    beta3 = ols(X3, y3); se3 = cluster_se(X3, y3, beta3, keep['facility_id'].to_numpy())
    tau3 = float(beta3[cols3.index('post')]); tau3_se = float(se3[cols3.index('post')])
    tau3_p = float(2 * (1 - norm_cdf(abs(tau3 / tau3_se))))

    return {
        'n_treated_facilities': int(keep[keep['treated'] == 1]['facility_id'].nunique()),
        'n_control_facilities': int(keep[keep['control'] == 1]['facility_id'].nunique()),
        'n_facility_years': int(len(keep)),
        'twfe_did': {'post_coef': tau, 'post_se_clustered': tau_se, 'post_p': tau_p},
        'twfe_did_trend_adjusted': {'post_coef': tau3, 'post_se_clustered': tau3_se, 'post_p': tau3_p},
        'event_study': ev,
    }


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

    # ---- outcome + mechanism columns ----
    gh['conc'] = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['rec'] = pd.to_numeric(gh['annual_qty_recoverd_ch4_eq_hh4'], errors='coerce')
    gh['flow'] = pd.to_numeric(gh['annual_landfill_gas_flow'], errors='coerce')
    gh['wells'] = pd.to_numeric(gh['number_of_wells'], errors='coerce')
    gh['capacity'] = pd.to_numeric(gh['gas_collection_system_capacity'], errors='coerce')
    gh['efficiency'] = pd.to_numeric(gh['est_gas_collection_efficiency'], errors='coerce')
    gh['basis'] = basis_of(gh['ch4_conc_measured_wet_basis'])
    gh['wet'] = (gh['basis'] == 'wet').astype(int)
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

    # ---- classification (identical to stratified script) ----
    is_rng = df['Project Type Category'].eq(RNG_CATEGORY) | df['RNG Delivery Method'].isin(RNG_METHODS)
    is_pi = df['RNG Delivery Method'].eq('Pipeline Injection')
    rng_pi = df[is_rng & is_pi].copy()
    rng_pi['sy'] = pd.to_datetime(rng_pi['Project Start Date'], errors='coerce').dt.year
    valid = rng_pi[(rng_pi['sy'] >= 1995) & (rng_pi['sy'] <= 2024)]
    adopt = valid.dropna(subset=['sy']).groupby('Landfill ID')['sy'].agg(lambda s: int(min(s)))

    lf2fac = df[df['GHGRP ID'].notna()].groupby('Landfill ID')['GHGRP ID'].agg(
        lambda s: sorted(set(s.astype('int64'))))
    rng_any_lf = set(df.loc[is_rng, 'Landfill ID'].astype(int))
    pi_lf = set(adopt.index.astype(int))
    fac2lf = {}
    for lid, facs in lf2fac.items():
        for f in facs:
            fac2lf.setdefault(int(f), set()).add(int(lid))

    lf_flag = {}
    for lid in pi_lf:
        rows = df[df['Landfill ID'].astype(int) == lid]
        pi_rows = rows[rows['RNG Delivery Method'].eq('Pipeline Injection')]
        statuses = set(pi_rows['Current Project Status'].astype(str).str.strip())
        ever_op = bool(statuses & {'Operational', 'Shutdown'})
        other = rows[rows['Project Type Category'].isin(NON_RNG_USE)]
        other_years = pd.to_datetime(other['Project Start Date'], errors='coerce').dt.year.dropna()
        prior_use = bool((other_years < adopt[lid]).any())
        lf_flag[lid] = {'ever_op': ever_op, 'prior_use': prior_use, 'statuses': sorted(statuses)}

    def group_of(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        if not lids:
            return None
        ever_op = any(lf_flag[l]['ever_op'] for l in lids)
        prior_use = any(lf_flag[l]['prior_use'] for l in lids)
        if not ever_op:
            return 'excluded_status'
        return 'switch' if prior_use else 'new'

    # ---- panel ----
    rows = []
    for f, lids in fac2lf.items():
        is_treated = any(l in pi_lf for l in lids)
        is_rng_any = any(l in rng_any_lf for l in lids)
        is_control = (not is_treated) and (not is_rng_any)
        tys = [adopt.get(l) for l in lids if l in adopt]
        Ti = min(tys) if tys else None
        grp = group_of(f) if is_treated else None
        for _, r in gh[gh['fac'] == f].iterrows():
            y = int(r['year'])
            post = 1 if (is_treated and Ti is not None and y >= Ti) else 0
            conc = r['conc']; rec = r['rec']; flow = r['flow']
            wells = r['wells']; cap = r['capacity']; eff = r['efficiency']
            row = {
                'facility_id': f, 'year': y,
                'conc': float(conc) if (pd.notna(conc) and 0 < conc <= 100) else np.nan,
                'log_conc': float(np.log(conc)) if (pd.notna(conc) and 0 < conc <= 100) else np.nan,
                'rec': float(rec) if (pd.notna(rec) and rec > 0) else np.nan,
                'log_rec': float(np.log(rec)) if (pd.notna(rec) and rec > 0) else np.nan,
                'flow': float(flow) if (pd.notna(flow) and flow > 0) else np.nan,
                'log_flow': float(np.log(flow)) if (pd.notna(flow) and flow > 0) else np.nan,
                'wells': float(wells) if (pd.notna(wells) and wells > 0) else np.nan,
                'log_wells': float(np.log(wells)) if (pd.notna(wells) and wells > 0) else np.nan,
                'capacity': float(cap) if (pd.notna(cap) and cap > 0) else np.nan,
                'log_capacity': float(np.log(cap)) if (pd.notna(cap) and cap > 0) else np.nan,
                'efficiency': float(eff) if pd.notna(eff) else np.nan,
                'log_efficiency': float(np.log(eff)) if (pd.notna(eff) and eff > 0) else np.nan,
                'wet': int(r['wet']),
                'treated': int(is_treated), 'control': int(is_control),
                'group': grp,
                'Ti': Ti if is_treated else None, 'post': post,
                'event_time': (y - Ti) if (is_treated and Ti is not None) else None,
            }
            rows.append(row)
    pan = pd.DataFrame(rows)

    # ---- (1) missingness, printed first ----
    mech_cols = {
        'number_of_wells': 'wells',
        'gas_collection_system_capacity': 'capacity',
        'est_gas_collection_efficiency': 'efficiency',
        'annual_landfill_gas_flow': 'flow',
    }
    missing = {}
    for label, c in mech_cols.items():
        tot = int(len(gh))
        nn = int(gh[c].notna().sum())
        tp = pan[pan['treated'] == 1]
        t_tot = int(len(tp)); t_nn = int(tp[c].notna().sum())
        missing[label] = {
            'ghgrp_non_null': nn, 'ghgrp_total': tot, 'ghgrp_pct': round(100 * nn / tot, 2),
            'treated_panel_non_null': t_nn, 'treated_panel_total': t_tot,
            'treated_panel_pct': round(100 * t_nn / t_tot, 2) if t_tot else None,
        }
    print(json.dumps({'stage': 'missingness', 'mechanism_columns': missing},
                     ensure_ascii=False, indent=2), flush=True)

    # ---- level identity sanity check ----
    def ratio_stats(sub):
        d = sub[(sub['flow'].notna()) & (sub['conc'].notna()) & (sub['rec'].notna())].copy()
        if len(d) == 0:
            return None
        d['ratio'] = d['flow'] * d['conc'] * IMPLIED_CONST / d['rec']
        return {
            'n': int(len(d)),
            'median_implied_over_reported': float(d['ratio'].median()),
            'p25': float(d['ratio'].quantile(0.25)),
            'p75': float(d['ratio'].quantile(0.75)),
        }
    level_identity = {'all': ratio_stats(pan)}
    dtr = pan[pan['treated'] == 1].copy()
    dtr = dtr[(dtr['flow'].notna()) & (dtr['conc'].notna()) & (dtr['rec'].notna())].copy()
    if len(dtr):
        dtr['ratio'] = dtr['flow'] * dtr['conc'] * IMPLIED_CONST / dtr['rec']
        def _med(s):
            s = s.dropna()
            return float(s.median()) if len(s) else None
        level_identity['treated_pre_post'] = {
            'n_pre': int((dtr['post'] == 0).sum()),
            'median_ratio_pre': _med(dtr.loc[dtr['post'] == 0, 'ratio']),
            'n_post': int((dtr['post'] == 1).sum()),
            'median_ratio_post': _med(dtr.loc[dtr['post'] == 1, 'ratio']),
        }

    # ---- (2)+(3) run all outcomes x groups ----
    def usable(g):
        return (g['post'].sum() >= 1) and ((1 - g['post']).sum() >= 1)

    def build_subset(pan_out, group_filter):
        treated_fac = set()
        for f, g in pan_out[pan_out['treated'] == 1].groupby('facility_id'):
            if usable(g) and group_filter(g):
                treated_fac.add(f)
        control_fac = set(pan_out.loc[pan_out['control'] == 1, 'facility_id'])
        return pan_out[pan_out['facility_id'].isin(treated_fac | control_fac)].copy()

    groups = {
        'all_ever_operational': lambda g: (g['group'].isin(['new', 'switch'])).all(),
        'new_rng': lambda g: (g['group'] == 'new').all(),
        'use_switch': lambda g: (g['group'] == 'switch').all(),
    }

    outcome_specs = {
        'conc':           ('conc',           True,  'wet'),
        'log_conc':       ('log_conc',       True,  'wet'),
        'log_rec':        ('log_rec',        False, 'wet'),
        'log_rec_wet':    ('log_rec',        True,  'wet'),
        'log_flow':       ('log_flow',       True,  'wet'),
        'log_wells':      ('log_wells',      False, 'wet'),
        'log_capacity':   ('log_capacity',   False, 'wet'),
        'efficiency':     ('efficiency',     False, 'wet'),
        'log_efficiency': ('log_efficiency', False, 'wet'),
    }

    results = {}
    for oname, (ocol, with_wet, wet_col) in outcome_specs.items():
        pan_o = pan[pan[ocol].notna()]
        for gname, gfilter in groups.items():
            sub = build_subset(pan_o, gfilter)
            results[f'{oname}__{gname}'] = run_models(sub, ocol, with_wet, wet_col)

    # ---- physical identity gap (log space, units-free) ----
    identity_gap = {}
    for gname in groups:
        es_rec = results[f'log_rec_wet__{gname}']['event_study']
        es_flow = results[f'log_flow__{gname}']['event_study']
        es_conc = results[f'log_conc__{gname}']['event_study']
        es_eff = results[f'log_efficiency__{gname}']['event_study']
        gap = {}
        for lv in EV_LEVELS:
            key = f'ev_{lv}'
            gap[lv] = {
                'gap': round(es_rec[key]['coef'] - es_flow[key]['coef'] - es_conc[key]['coef'], 4),
                'log_efficiency_coef': round(es_eff[key]['coef'], 4),
            }
        identity_gap[gname] = gap

    class_counts = {}
    for f, g in pan[pan['treated'] == 1].groupby('facility_id'):
        grp = g['group'].iloc[0]
        class_counts[grp] = class_counts.get(grp, 0) + 1

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'treatment_rule': {
            'exclude': 'RNG-PI current status Planned/Construction (never built)',
            'new': 'ever-operational AND no prior Electricity/Direct project before RNG',
            'switch': 'ever-operational AND prior Electricity/Direct project before RNG',
        },
        'implied_recovered_const_note':
            'flow(scf)*conc(%)*5.074e-6 = recovered CH4 (t CO2e), GWP=25, CH4 density 0.7168 kg/m3 @STP. '
            'Level ratio is unit/GWP-sensitive; the log identity gap is units-free.',
        'mechanism_columns_missingness': missing,
        'level_identity_check': level_identity,
        'treated_classification_counts': class_counts,
        'results': results,
        'physical_identity_gap': identity_gap,
    }
    (out / 'additionality_mechanism_consistency_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
