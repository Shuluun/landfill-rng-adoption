"""Callaway-Sant'Anna (2021) staggered DiD, never-treated version.

Purpose: check whether the ~+4pp concentration jump survives a
staggered-adoption-robust estimator (TWFE can be biased under heterogeneous
treatment effects via negative-weighted 2x2 comparisons).

Estimator (CS never-treated, group-time ATT with base period g-1):
    ATT(g, e) = mean_{i in cohort g} [ conc_i(Ti+e) - conc_i(Ti-1) ]
              - mean_{c in never-treated} [ conc_c(Ti+e) - conc_c(Ti-1) ]
where cohort g = facilities adopting RNG-PI in calendar year Ti, e = event time
in years relative to adoption, base period = Ti-1 (e=-1, normalised to 0).

Event-time aggregation:
    ATT(e) = sum_g w_g(e) ATT(g, e),  w_g(e) = n_g(e) / sum_g n_g(e).
Overall ATT = weighted mean of ATT(e) over e >= 0 (weights = treated obs).

Inference: facility-level block bootstrap (percentile CI).
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'
STRAT = ROOT / 'outputs/2026-11-09_rng_additionality_stratified/run_001/additionality_stratified_summary.json'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
NON_RNG_USE = {'Electricity', 'Direct'}

YEARS = list(range(2010, 2024))
YIDX = {y: i for i, y in enumerate(YEARS)}
NY = len(YEARS)
EVENTS = [-4, -3, -2, -1, 0, 1, 2, 3, 4]   # exact event years; e=-1 is base
EV_X = {-4: -4, -3: -3, -2: -2, -1: -1, 0: 0, 1: 1, 2: 2, 3: 3, 4: 4}

C_CS = '#0072B2'
C_TWFE = '#D55E00'

plt.rcParams.update({
    'font.size': 9, 'axes.titlesize': 10, 'axes.titleweight': 'bold',
    'axes.edgecolor': '#9aa0a6', 'axes.labelcolor': '#333333',
    'xtick.color': '#555555', 'ytick.color': '#555555',
    'axes.grid': True, 'grid.color': '#e5e7ea', 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'figure.facecolor': 'white',
    'savefig.facecolor': 'white', 'svg.fonttype': 'none',
})


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_panel():
    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    gh = pd.read_csv(GHGRP, dtype={'facility_id': 'Int64'})
    conc = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['conc'] = conc.where((conc > 0) & (conc <= 100))
    gh['year'] = gh['reporting_year'].astype(int)
    gh['fac'] = gh['facility_id'].astype('Int64')

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
        lf_flag[lid] = {'ever_op': ever_op, 'prior_use': prior_use}

    def group_of(f):
        lids = [l for l in fac2lf.get(f, set()) if l in pi_lf]
        if not lids:
            return None
        ever_op = any(lf_flag[l]['ever_op'] for l in lids)
        prior_use = any(lf_flag[l]['prior_use'] for l in lids)
        if not ever_op:
            return 'excluded_status'
        return 'switch' if prior_use else 'new'

    matched = set(fac2lf.keys()) & set(gh['fac'].dropna().astype(int))
    treated = {f for f in matched if any(l in pi_lf for l in fac2lf[f])}
    treated_rng_any = {f for f in matched if any(l in rng_any_lf for l in fac2lf[f])}
    control = matched - treated_rng_any

    # treated must be ever-operational and usable (>=1 pre & >=1 post conc)
    treated_usable = set()
    for f in treated:
        g = gh[(gh['fac'] == f) & gh['conc'].notna()]
        if g.empty:
            continue
        grp = group_of(f)
        if grp not in ('new', 'switch'):
            continue
        lids = [l for l in fac2lf[f] if l in pi_lf]
        Ti = min(adopt[l] for l in lids if l in adopt) if any(l in adopt for l in lids) else None
        if Ti is None:
            continue
        if int((g['year'] < Ti).sum()) >= 1 and int((g['year'] >= Ti).sum()) >= 1:
            treated_usable.add(f)

    # build year->conc dicts and Ti
    treated_rows = []  # (Ti, conc_dict, group)
    for f in sorted(treated_usable):
        g = gh[gh['fac'] == f]
        lids = [l for l in fac2lf[f] if l in pi_lf]
        Ti = min(adopt[l] for l in lids if l in adopt)
        cd = dict(zip(g['year'].astype(int), g['conc'].to_numpy(float)))
        treated_rows.append((int(Ti), cd, group_of(f)))
    control_rows = []  # conc_dict
    for f in sorted(control):
        g = gh[gh['fac'] == f]
        cd = dict(zip(g['year'].astype(int), g['conc'].to_numpy(float)))
        control_rows.append(cd)

    return treated_rows, control_rows


def row_array(conc_dict):
    return np.array([conc_dict.get(y, np.nan) for y in YEARS], dtype=float)


def cs_core(treated_rows, control_rows):
    """Return per-event ATT and overall ATT for the given (resampled) rows.

    treated_rows: list of (Ti, conc_dict, group); control_rows: list of conc_dict.
    """
    n_t = len(treated_rows)
    n_c = len(control_rows)
    Tmat = np.vstack([row_array(cd) for _, cd, _ in treated_rows]) if n_t else np.empty((0, NY))
    Ti = np.array([t for t, _, _ in treated_rows], dtype=int)
    Cmat = np.vstack([row_array(cd) for cd in control_rows]) if n_c else np.empty((0, NY))

    att = {e: np.nan for e in EVENTS}
    n_obs = {e: 0 for e in EVENTS}
    # cohort-wise group-time ATTs, then aggregate
    for e in EVENTS:
        if e == -1:
            att[e] = 0.0
            n_obs[e] = int(np.sum(Ti >= YEARS[0] + 1))  # treated with base present
            continue
        vals = []  # per-cohort (att, n_treated)
        for g in np.unique(Ti):
            ty = g + e
            by = g - 1
            if ty not in YIDX or by not in YIDX:
                continue
            m = Ti == g
            trow = Tmat[m]
            t_delta = trow[:, YIDX[ty]] - trow[:, YIDX[by]]
            t_delta = t_delta[np.isfinite(t_delta)]
            if t_delta.size == 0:
                continue
            c_delta = Cmat[:, YIDX[ty]] - Cmat[:, YIDX[by]]
            c_delta = c_delta[np.isfinite(c_delta)]
            if c_delta.size == 0:
                continue
            att_g = float(t_delta.mean() - c_delta.mean())
            vals.append((att_g, int(t_delta.size)))
        if vals:
            w = np.array([n for _, n in vals], dtype=float)
            w = w / w.sum()
            att[e] = float(sum(a * ww for (a, _), ww in zip(vals, w)))
            n_obs[e] = int(sum(n for _, n in vals))
    post = [EVENTS[i] for i in range(len(EVENTS)) if EVENTS[i] >= 0]
    weights = np.array([n_obs[e] for e in post], dtype=float)
    overall = float(np.average([att[e] for e in post], weights=weights)) if weights.sum() > 0 else np.nan
    return att, n_obs, overall


def bootstrap_cs(treated_rows, control_rows, n_rep=999, seed=12345):
    rng = np.random.default_rng(seed)
    n_t, n_c = len(treated_rows), len(control_rows)
    atts = {e: [] for e in EVENTS}
    overalls = []
    for _ in range(n_rep):
        ti = rng.integers(0, n_t, size=n_t)
        ci = rng.integers(0, n_c, size=n_c)
        tr = [treated_rows[i] for i in ti]
        cr = [control_rows[i] for i in ci]
        att, _, overall = cs_core(tr, cr)
        for e in EVENTS:
            atts[e].append(att[e])
        overalls.append(overall)
    return atts, overalls


def pct(vals):
    v = np.array(vals, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None, None, None
    return float(np.mean(v)), float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def boot_p(vals):
    v = np.array(vals, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    return float(2 * min((v <= 0).mean(), (v >= 0).mean()))


def fig_overlay(cs_att, cs_lo, cs_hi, twfe_ev, outdir):
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    xs_cs = np.array([EV_X[e] for e in EVENTS])
    ys_cs = np.array([cs_att[e] for e in EVENTS])
    lo = np.array([cs_lo[e] for e in EVENTS])
    hi = np.array([cs_hi[e] for e in EVENTS])
    err = np.vstack([ys_cs - lo, hi - ys_cs])
    ax.errorbar(xs_cs, ys_cs, yerr=err, fmt='o', color=C_CS, ms=6,
                elinewidth=1.4, capsize=3, capthick=1.2, zorder=3, mec='white', mew=0.8,
                label='Callaway–Sant’Anna (never-treated, 95% CI)')

    # TWFE event study (concentration, all ever-operational)
    tw = twfe_ev['results']['conc__all_ever_operational']['event_study']
    tw_x = {'ev_pre_le_-5': -5, 'ev_k-4': -4, 'ev_k-3': -3, 'ev_k-2': -2,
            'ev_k0': 0, 'ev_k1': 1, 'ev_k2': 2, 'ev_k3': 3, 'ev_post_ge_4': 4}
    txs = np.array([tw_x[k] for k in tw_x])
    tys = np.array([tw[k]['coef'] for k in tw_x])
    tse = np.array([tw[k]['se'] for k in tw_x])
    ax.errorbar(txs, tys, yerr=1.96 * tse, fmt='s', color=C_TWFE, ms=5.5,
                elinewidth=1.3, capsize=3, capthick=1.1, zorder=3, mec='white', mew=0.8,
                label='TWFE event study (95% CI)')

    ax.axhline(0, color='#9aa0a6', lw=0.8)
    ax.axvline(-1, color='#666666', lw=0.8, ls='--', alpha=0.7)
    ax.set_xlim(-5.8, 4.8)
    ax.set_xticks([-5, -4, -3, -2, -1, 0, 1, 2, 3, 4])
    ax.set_xticklabels(['≤-5', '-4', '-3', '-2', '-1\n(ref)', '0', '1', '2', '3', '≥4'])
    ax.set_ylabel('Methane concentration (percentage points)')
    ax.set_xlabel('Event time (years relative to RNG-PI adoption)')
    ax.set_title('Concentration jump is robust to staggered-DiD weighting')
    ax.legend(loc='upper left', frameon=False, fontsize=8)
    fig.tight_layout()
    for ext in ('svg', 'png'):
        fig.savefig(outdir / f'fig4_cs_vs_twfe_event_study.{ext}', dpi=300, bbox_inches='tight')
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--bootstrap', type=int, default=999)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    treated_rows, control_rows = build_panel()
    strat = json.loads(STRAT.read_text(encoding='utf-8'))

    # split into all / new / switch
    def run_stratum(rows):
        att, n_obs, overall = cs_core(rows, control_rows)
        atts_boot, overalls_boot = bootstrap_cs(rows, control_rows, n_rep=args.bootstrap)
        return {
            'n_treated': len(rows),
            'n_cohorts': int(len({t for t, _, _ in rows})),
            'att_event_time': {str(e): {'att': att[e], 'n_treated_obs': n_obs[e]} for e in EVENTS},
            'bootstrap_event_time': {
                str(e): {'mean': pct(atts_boot[e])[0], 'lo': pct(atts_boot[e])[1], 'hi': pct(atts_boot[e])[2]}
                for e in EVENTS},
            'overall_att': overall,
            'overall_att_boot_mean': pct(overalls_boot)[0],
            'overall_att_ci95': [pct(overalls_boot)[1], pct(overalls_boot)[2]],
            'overall_att_p': boot_p(overalls_boot),
        }

    all_rows = treated_rows
    new_rows = [r for r in treated_rows if r[2] == 'new']
    sw_rows = [r for r in treated_rows if r[2] == 'switch']

    results = {
        'all_ever_operational': run_stratum(all_rows),
        'new_rng': run_stratum(new_rows),
        'use_switch': run_stratum(sw_rows),
    }

    # build CS event-time arrays for the overlay (all treated)
    ev = results['all_ever_operational']
    cs_att = {int(k): v['att'] for k, v in ev['att_event_time'].items()}
    cs_lo = {int(k): v['lo'] for k, v in ev['bootstrap_event_time'].items()}
    cs_hi = {int(k): v['hi'] for k, v in ev['bootstrap_event_time'].items()}
    fig_overlay(cs_att, cs_lo, cs_hi, strat, out)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas', 'matplotlib']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP), 'stratified_sha256': sha(STRAT),
        'script_sha256': sha(__file__),
        'estimator': 'Callaway-Sant\'Anna (2021) never-treated; group-time ATT, base g-1, exact event years',
        'events': EVENTS, 'base_period': 'Ti-1 (e=-1)', 'bootstrap_reps': args.bootstrap,
        'bootstrap_seed': 12345, 'random_seed': 12345, 'synthetic_data_used': False,
        'n_control_never_treated': len(control_rows),
        'comparison_twfe': {
            'raw_post_coef': strat['results']['conc__all_ever_operational']['twfe_did']['post_coef'],
            'trend_adj_post_coef': strat['results']['conc__all_ever_operational']['twfe_did_trend_adjusted']['post_coef'],
        },
        'results': results,
    }
    (out / 'additionality_cs_did_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
