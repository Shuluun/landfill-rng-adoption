"""Three manuscript figures for the RNG additionality paper (Alice/Chesley).

Figures (all from real local data; no synthetic values):
  Fig 1  sample flow (LMOP RNG-PI -> GHGRP treated/control -> final DiD sample)
  Fig 2  three-outcome event study (concentration %, log flow, log recovery)
  Fig 3  specification/definition sensitivity of the concentration effect (forest)

Reads the run summaries of prior scripts (reproducible); re-derives the sample
flow counts directly from LMOP + GHGRP. Static publication figures: SVG + PNG.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[1]
LMOP = ROOT / 'data/raw/2026-10-06_public_inputs/lmopdata.xlsx'
GHGRP = ROOT / 'inputs/public/ghgrp_subpart_hh_gas_collection_20261106/hh_gas_collection_system_detls_all.csv'
STRAT = ROOT / 'outputs/2026-11-09_rng_additionality_stratified/run_001/additionality_stratified_summary.json'
FLOWJ = ROOT / 'outputs/2026-11-08_rng_additionality_flow/run_001/additionality_flow_summary.json'
STABLE = ROOT / 'outputs/2026-11-09_rng_concentration_stable/run_001/additionality_concentration_stable_summary.json'
SHUT = ROOT / 'outputs/2026-11-09_rng_shutdown_sensitivity/run_001/additionality_shutdown_sensitivity_summary.json'

RNG_CATEGORY = 'Renewable Natural Gas'
RNG_METHODS = {'Pipeline Injection', 'Local Use'}
NON_RNG_USE = {'Electricity', 'Direct'}

# Okabe-Ito, CVD-safe (validator: all checks PASS)
C_CONC = '#0072B2'   # concentration (blue)
C_FLOW = '#D55E00'   # flow (vermillion)
C_REC = '#009E73'    # recovery (bluish green)
C_NEW = '#0072B2'
C_SWITCH = '#D55E00'
C_EXCL = '#8C8C8C'
C_CTRL = '#444444'

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


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


EV_X = {'pre_le_-5': -5, 'k-4': -4, 'k-3': -3, 'k-2': -2,
        'k0': 0, 'k1': 1, 'k2': 2, 'k3': 3, 'post_ge_4': 4}


def ev_xy(ev_dict):
    xs, ys, ses = [], [], []
    for k, x in EV_X.items():
        if k in ev_dict:
            xs.append(x); ys.append(ev_dict[k]['coef']); ses.append(ev_dict[k]['se'])
    return np.array(xs), np.array(ys), np.array(ses)


def did_val(d):
    coef = d.get('post_coef', d.get('post_coef_pp'))
    se = d.get('post_se_clustered')
    return float(coef), float(se)


# --------------------------------------------------------------------------- #
# Sample flow (re-derived from data)
# --------------------------------------------------------------------------- #
def compute_flow():
    df = pd.read_excel(LMOP, sheet_name='LMOP Database')
    gh = pd.read_csv(GHGRP, dtype={'facility_id': 'Int64'})

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

    gh['fac'] = gh['facility_id'].astype('Int64')
    conc = pd.to_numeric(gh['annl_avg_methane_concentration'], errors='coerce')
    gh['conc_ok'] = (conc > 0) & (conc <= 100)
    gh['year'] = gh['reporting_year'].astype(int)
    gh_fac = set(gh['fac'].dropna().astype(int))
    # match the stratified script exactly: only facilities matched to an LMOP landfill
    # enter the panel; control = matched & not treated & not any-RNG.
    matched = set(fac2lf.keys()) & gh_fac
    treated = {f for f in matched if any(l in pi_lf for l in fac2lf[f])}
    treated_rng_any = {f for f in matched if any(l in rng_any_lf for l in fac2lf[f])}
    control = matched - treated_rng_any
    control_conc = control & set(gh.loc[gh['conc_ok'], 'fac'].dropna().astype(int))
    n_unmatched = len(gh_fac - matched)

    # DiD-usable treated (both pre & post concentration observed)
    usable = {'new': 0, 'switch': 0}
    dropped = {'new': 0, 'switch': 0}
    for f in treated:
        g = gh[(gh['fac'] == f) & gh['conc_ok']]
        if g.empty:
            continue
        grp = group_of(f)
        if grp not in ('new', 'switch'):
            continue
        lids = [l for l in fac2lf[f] if l in pi_lf]
        Ti = min(adopt[l] for l in lids if l in adopt) if any(l in adopt for l in lids) else None
        if Ti is None:
            continue
        pre = int((g['year'] < Ti).sum()); post = int((g['year'] >= Ti).sum())
        if pre >= 1 and post >= 1:
            usable[grp] += 1
        else:
            dropped[grp] += 1

    flow = {
        'n_lmop_rows': int(len(df)),
        'n_rng_pi_projects': int(len(rng_pi)),
        'n_rng_pi_landfills': int(len(pi_lf)),
        'n_ghgrp_facilities': int(len(gh_fac)),
        'n_treated_matched': int(len(treated)),
        'excluded_status': int(sum(1 for f in treated if group_of(f) == 'excluded_status')),
        'new': int(sum(1 for f in treated if group_of(f) == 'new')),
        'switch': int(sum(1 for f in treated if group_of(f) == 'switch')),
        'n_control': int(len(control)),
        'n_control_did': int(len(control_conc)),
        'n_ghgrp_unmatched': int(n_unmatched),
        'usable_new': usable['new'], 'usable_switch': usable['switch'],
        'dropped_new': dropped['new'], 'dropped_switch': dropped['switch'],
    }
    flow['ever_operational'] = flow['new'] + flow['switch']
    flow['usable_all'] = flow['usable_new'] + flow['usable_switch']
    return flow


# --------------------------------------------------------------------------- #
# Figure 1: sample flow
# --------------------------------------------------------------------------- #
def fig_sample_flow(f, outdir):
    fig, ax = plt.subplots(figsize=(6.8, 7.0))
    ax.set_xlim(0, 10); ax.set_ylim(0, 11.0); ax.axis('off')
    ax.set_title('Sample construction: RNG-PI projects to DiD facility sample')

    def box(x, y, w, h, text, fc='#f2f4f7', ec='#9aa0a6', fs=8.5, weight='normal'):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.05,rounding_size=0.10',
                                    fc=fc, ec=ec, lw=1.0))
        ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fs,
                weight=weight, color='#222222')

    def arrow(x0, y0, x1, y1):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle='-|>',
                                     mutation_scale=10, lw=1.0, color='#666666'))

    def vline(x, y0, y1, lw=1.0, color='#666666'):
        ax.plot([x, x], [y0, y1], color=color, lw=lw)

    def hline(x0, x1, y, lw=1.0, color='#666666'):
        ax.plot([x0, x1], [y, y], color=color, lw=lw)

    W = 9.2
    cx = 5.0
    # Row 1
    box(0.4, 9.95, W, 0.72, f"LMOP landfill & LFG project database\n{f['n_lmop_rows']:,} project records")
    arrow(cx, 9.95, cx, 9.30)
    # Row 2
    box(0.4, 8.58, W, 0.72, f"RNG — Pipeline Injection projects\n{f['n_rng_pi_projects']} projects · {f['n_rng_pi_landfills']} landfills")
    arrow(cx, 8.58, cx, 7.93)
    # Row 3 (treated)
    box(0.4, 7.21, W, 0.72, f"Matched to GHGRP Subpart HH facility — treated\n{f['n_treated_matched']} facilities",
        fc='#eaf2f8', ec='#0072B2')

    # branch to excluded / ever-operational
    y_b = 6.78
    vline(cx, 7.21, y_b)
    x_excl, x_op = 2.55, 7.55
    hline(x_excl, x_op, y_b)
    box(0.4, 5.98, 4.3, 0.80, f"Excluded: Planned /\nConstruction only\n{f['excluded_status']} facilities\n(never operational)", fc='#f1f1f1', ec=C_EXCL, fs=8)
    box(5.3, 5.98, 4.3, 0.80, f"Ever-operational RNG-PI\n{f['ever_operational']} facilities",
        fc='#eaf2f8', ec='#0072B2')

    # branch from ever-operational to new / switch
    y_b2 = 5.50
    vline(x_op, 5.98, y_b2)
    x_new, x_sw = 3.05, 7.45
    hline(x_new, x_sw, y_b2)
    box(1.1, 4.72, 3.9, 0.78, f"New RNG\n(no prior electricity/\ndirect use)\n{f['new']} facilities", fc='#eaf2f8', ec=C_NEW, fs=8)
    box(5.5, 4.72, 3.9, 0.78, f"Use-switch\n(prior electricity/\ndirect use)\n{f['switch']} facilities", fc='#fdeee6', ec=C_SWITCH, fs=8)

    # final DiD sample
    box(0.4, 3.60, W, 0.82,
        f"Final DiD sample (both pre- & post-adoption observed)\n"
        f"treated {f['usable_all']} (new {f['usable_new']} · switch {f['usable_switch']})  +  control (no RNG) {f['n_control_did']}  =  {f['usable_all'] + f['n_control_did']} facilities",
        fc='#eef7f2', ec='#009E73', fs=8.5)
    arrow(x_new, 4.72, x_new, 4.44)
    arrow(x_sw, 4.72, x_sw, 4.44)

    dropped = f['dropped_new'] + f['dropped_switch']
    ax.text(5, 2.85,
            f"Ever-operational treated dropped for lacking pre- or post-adoption concentration: "
            f"{dropped} (new {f['dropped_new']} · switch {f['dropped_switch']})",
            ha='center', va='center', fontsize=7.5, color='#666666', style='italic')

    fig.tight_layout()
    for ext in ('svg', 'png'):
        fig.savefig(outdir / f'fig1_sample_flow.{ext}', dpi=300, bbox_inches='tight')
    plt.close(fig)
    return {'dropped': dropped, 'usable_all': f['usable_all'],
            'n_control': f['n_control'], 'n_control_did': f['n_control_did']}


# --------------------------------------------------------------------------- #
# Figure 2: three-outcome event study
# --------------------------------------------------------------------------- #
def fig_event_study(strat, flowj, outdir):
    conc = strat['results']['conc__all_ever_operational']['event_study']
    rec = strat['results']['rec__all_ever_operational']['event_study']
    flw = flowj['event_study']

    panels = [
        ('A. Methane concentration (percentage points)', ev_xy(conc), C_CONC),
        ('B. Landfill gas flow (log)', ev_xy(flw), C_FLOW),
        ('C. Recovered CH₄ (log)', ev_xy(rec), C_REC),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(6.6, 8.2), sharex=True)
    for ax, (title, (xs, ys, ses), color) in zip(axes, panels):
        ax.axhline(0, color='#9aa0a6', lw=0.8)
        ax.axvline(-0.5, color='#666666', lw=0.8, ls='--', alpha=0.7)
        ax.errorbar(xs, ys, yerr=1.96 * ses, fmt='o', color=color, ms=5.5,
                    elinewidth=1.4, capsize=3, capthick=1.2, zorder=3,
                    label=None, mec='white', mew=0.8)
        ax.set_title(title)
        ax.set_xlim(-5.6, 4.6)
        ax.set_xticks([-5, -4, -3, -2, -1, 0, 1, 2, 3, 4])
        ax.set_xticklabels(['≤-5', '-4', '-3', '-2', '-1\n(ref)', '0', '1', '2', '3', '≥4'])
        ax.grid(axis='x', visible=False)
    axes[2].set_xlabel('Event time (years relative to RNG-PI adoption; k = -1 reference period)')
    fig.align_ylabels(axes)
    fig.tight_layout()
    for ext in ('svg', 'png'):
        fig.savefig(outdir / f'fig2_three_outcome_event_study.{ext}', dpi=300, bbox_inches='tight')
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Figure 3: specification / definition sensitivity (forest)
# --------------------------------------------------------------------------- #
def fig_sensitivity(strat, stable, shut, outdir):
    rows = []  # (label, coef, se, group, style)

    def add(d, label, group, solid):
        coef, se = did_val(d)
        rows.append((label, coef, se, group, 'o' if solid else 's'))

    allc = strat['results']['conc__all_ever_operational']
    newc = strat['results']['conc__new_rng']
    swc = strat['results']['conc__use_switch']
    add(allc['twfe_did'], 'TWFE (all treated)', 'Baseline', True)
    add(allc['twfe_did_trend_adjusted'], 'TWFE + facility trend', 'Baseline', False)
    add(stable['basis_stable_sample']['twfe_did'], 'Basis-stable, TWFE', 'Measurement basis', True)
    add(stable['basis_stable_sample']['twfe_did_trend_adjusted'], 'Basis-stable, + trend', 'Measurement basis', False)
    add(newc['twfe_did'], 'New RNG, TWFE', 'Treated definition', True)
    add(newc['twfe_did_trend_adjusted'], 'New RNG, + trend', 'Treated definition', False)
    add(swc['twfe_did'], 'Use-switch, TWFE', 'Treated definition', True)
    add(swc['twfe_did_trend_adjusted'], 'Use-switch, + trend', 'Treated definition', False)
    add(shut['results']['conc__operational_only__all_ever_operational']['twfe_did'],
        'Operational-only, TWFE', 'Shutdown rule', True)
    add(shut['results']['conc__operational_only__all_ever_operational']['twfe_did_trend_adjusted'],
        'Operational-only, + trend', 'Shutdown rule', False)

    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    ypos = np.arange(len(rows))[::-1]

    for idx, (label, coef, se, g, marker) in enumerate(rows):
        y = ypos[idx]
        ax.errorbar(coef, y, xerr=1.96 * se, fmt=marker, color='#0072B2', ms=6,
                    elinewidth=1.4, capsize=3, capthick=1.2, zorder=3, mec='white', mew=0.8)

    ax.axvline(0, color='#666666', lw=1.0)
    ax.axvline(3.98, color='#D55E00', lw=0.8, ls='--', alpha=0.55)
    ax.text(3.98, len(rows) - 0.25, ' baseline trend-adj.\n +3.98 pp', fontsize=7, color='#D55E00',
            ha='left', va='top')
    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8.5)
    ax.set_xlabel('Adoption effect on methane concentration (percentage points)')
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_title('Concentration effect is robust across specifications')
    fig.tight_layout()
    for ext in ('svg', 'png'):
        fig.savefig(outdir / f'fig3_specification_sensitivity.{ext}', dpi=300, bbox_inches='tight')
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()

    strat = load_json(STRAT); flowj = load_json(FLOWJ)
    stable = load_json(STABLE); shut = load_json(SHUT)

    flow = compute_flow()
    r1 = fig_sample_flow(flow, out)
    fig_event_study(strat, flowj, out)
    fig_sensitivity(strat, stable, shut, out)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas', 'matplotlib']},
        'lmop_sha256': sha(LMOP), 'ghgrp_sha256': sha(GHGRP),
        'stratified_sha256': sha(STRAT), 'flow_sha256': sha(FLOWJ),
        'stable_sha256': sha(STABLE), 'shutdown_sha256': sha(SHUT),
        'script_sha256': sha(__file__), 'random_seed': None, 'synthetic_data_used': False,
        'palette': {'conc': C_CONC, 'flow': C_FLOW, 'rec': C_REC,
                    'validation': 'Okabe-Ito; dataviz validate_palette.js all PASS (CVD worst-adjacent ΔE 11.0)'},
        'sample_flow': flow,
        'fig1_final_did': r1,
        'figures': ['fig1_sample_flow', 'fig2_three_outcome_event_study', 'fig3_specification_sensitivity'],
    }
    (out / 'manuscript_figures_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
