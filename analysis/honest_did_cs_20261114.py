"""HonestDiD / Rambachan-Roth (2023) relative-magnitudes sensitivity for the
Callaway-Sant'Anna (CS) event study (Tier-1 port).

Why: the manuscript's primary secondary analysis is the CS never-treated DiD
(additionality_cs_did_20261109.py), but the existing HonestDiD sensitivity
(honest_did_relative_magnitudes_20261109.py) was computed on the TWFE event study.
This script applies the same relative-magnitudes bound to the CS event-time ATTs,
using the facility-block bootstrap covariance already saved in
event_study_covariance_summary.json (cs_event_study block).

Target (matches the manuscript headline):
  CS:  theta = observation-weighted average of post event-time ATTs
       = overall_att (the manuscript's +3.97 pp for the all group).
       Weights l_post = n_obs(e) / sum(n_obs(e)) over e in {0,1,2,3,4}, read from
       additionality_cs_did_summary.json (att_event_time.n_treated_obs).
  TWFE: theta = equal-weighted average of post event-time bins (matching the
       earlier HonestDiD convention).

Method (target-as-scalar form, Rambachan & Roth 2023 Sec 4.3):
  theta_hat     = l_post' beta[post]
  sigma_post    = sqrt(l_post' Sigma[post,post] l_post)
  pre coefs     = beta[pre]  (point-identified pre-trend violations)
  Under Delta^RM(Mbar) = {delta : |delta_post| <= Mbar * max_s |delta_pre_s|},
  the honest (1-alpha) CI is
      theta_hat +/- sigma_post * c_alpha(Mbar),
      c_alpha(Mbar) = q_{1-alpha}( |Z_theta| + Mbar * max_s |Z_pre_s| ),
      (Z_theta, Z_pre) ~ N( (0, beta[pre]/sigma_post), S_std ),
      S_std = reduced covariance of (theta, beta[pre]) / sigma_post^2.

Note on the earlier script: honest_did_relative_magnitudes_20261109.py aggregated
the post term as mean(|Z_post|) over post coordinates. Here we use the
target-as-scalar form |Z_theta| = |l_post' Z_post|, which matches the paper. This
script reports (a) the CS bound (primary), and (b) the TWFE bound recomputed under
the SAME form for apples-to-apples comparison; the earlier coordinate-averaged
TWFE Mbar* is also read back for reference.

Read-only: consumes the saved covariance + CS summaries; writes to a new run dir.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COV_SUM = ROOT / 'outputs/2026-11-09_rng_event_study_covariance/run_001/event_study_covariance_summary.json'
CS_SUM = ROOT / 'outputs/2026-11-09_rng_cs_did/run_001/additionality_cs_did_summary.json'
OLD_HONEST = ROOT / 'outputs/2026-11-09_rng_honest_did/run_001/honest_did_relative_magnitudes_summary.json'

CS_EVENTS = [-4, -3, -2, -1, 0, 1, 2, 3, 4]
CS_PRE = [0, 1, 2]          # e = -4, -3, -2
CS_POST = [4, 5, 6, 7, 8]   # e = 0, 1, 2, 3, 4
CS_POST_EVENTS = [0, 1, 2, 3, 4]

TWFE_LEVELS = ['pre_le_-5', 'k-4', 'k-3', 'k-2', 'k0', 'k1', 'k2', 'k3', 'post_ge_4']
TWFE_PRE = [0, 1, 2, 3]
TWFE_POST = [4, 5, 6, 7, 8]

GROUPS = ['all_ever_operational', 'new_rng', 'use_switch']
BASE_MBAR = [0.0, 0.5, 1.0, 2.0, 3.0]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def psd_clip(S, jitter=1e-12):
    S = (S + S.T) / 2.0
    e, V = np.linalg.eigh(S)
    e = np.clip(e, jitter, None)
    return (V * e) @ V.T


def rr_bounds(beta, cov, pre_idx, post_idx, l_post, B=200000, seed=12345, alpha=0.05):
    beta = np.asarray(beta, dtype=float)
    cov = np.asarray(cov, dtype=float)
    l_post = np.asarray(l_post, dtype=float)
    l_post = l_post / l_post.sum()
    theta_hat = float(l_post @ beta[post_idx])
    sigma_post = float(np.sqrt(l_post @ cov[np.ix_(post_idx, post_idx)] @ l_post))
    beta_pre = beta[pre_idx]

    # reduced covariance of (theta, beta_pre)
    cov_theta_pre = l_post @ cov[np.ix_(post_idx, pre_idx)]   # (p,)
    cov_pre_pre = cov[np.ix_(pre_idx, pre_idx)]               # (p, p)
    p = len(pre_idx)
    S_red = np.zeros((p + 1, p + 1))
    S_red[0, 0] = sigma_post ** 2
    S_red[0, 1:] = cov_theta_pre
    S_red[1:, 0] = cov_theta_pre
    S_red[1:, 1:] = cov_pre_pre
    S_std = psd_clip(S_red / sigma_post ** 2)

    m = np.zeros(p + 1)
    m[0] = 0.0
    m[1:] = beta_pre / sigma_post

    rng = np.random.default_rng(seed)
    w = rng.multivariate_normal(m, S_std, size=B)
    a = np.abs(w[:, 0])               # |Z_theta|
    b = np.abs(w[:, 1:]).max(axis=1)  # max_s |Z_pre_s|

    def c_alpha(Mbar):
        return float(np.quantile(a + Mbar * b, 1 - alpha))

    t_ratio = theta_hat / sigma_post
    c0 = c_alpha(0.0)  # sanity: ~1.96

    if c0 >= t_ratio:
        Mstar = 0.0
    else:
        lo, hi = 0.0, 50.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if c_alpha(mid) < t_ratio:
                lo = mid
            else:
                hi = mid
        Mstar = 0.5 * (lo + hi)

    grid = list(BASE_MBAR) + [round(Mstar, 2)]
    ci = {}
    for Mb in sorted(set(grid)):
        cc = c_alpha(Mb)
        ci[str(Mb)] = {'c_alpha': cc, 'ci95': [theta_hat - sigma_post * cc, theta_hat + sigma_post * cc]}

    return {
        'target': 'observation-weighted average post effect' if l_post.shape[0] == 5 and not np.allclose(l_post, 1/5) else 'equal-weighted average post effect',
        'theta_hat': theta_hat,
        'sigma_post': sigma_post,
        't_ratio': t_ratio,
        'beta_pre': beta_pre.tolist(),
        'max_abs_pre_trend': float(np.max(np.abs(beta_pre))),
        'c_alpha_Mbar0': c0,
        'breakdown_Mbar': Mstar,
        'ci_by_Mbar': ci,
        'n_pre_coefs': int(p),
        'post_weights': l_post.tolist(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--draws', type=int, default=200000)
    ap.add_argument('--seed', type=int, default=12345)
    args = ap.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'outputs'):
        raise ValueError('output must stay under outputs/')
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    B, seed = args.draws, args.seed

    d = json.loads(COV_SUM.read_text(encoding='utf-8'))
    cs_sum = json.loads(CS_SUM.read_text(encoding='utf-8'))

    cs_res, twfe_res = {}, {}
    for g in GROUPS:
        # CS: observation-weighted target (matches manuscript overall_att)
        cs = d['cs_event_study'][g]
        beta_cs = np.array(cs['att'], dtype=float)
        cov_cs = np.array(cs['bootstrap_cov'], dtype=float)
        n_obs = np.array([cs_sum['results'][g]['att_event_time'][str(e)]['n_treated_obs']
                          for e in CS_POST_EVENTS], dtype=float)
        l_cs = n_obs / n_obs.sum()
        r = rr_bounds(beta_cs, cov_cs, CS_PRE, CS_POST, l_cs, B, seed)
        r['events'] = CS_EVENTS
        r['pre_events'] = [CS_EVENTS[i] for i in CS_PRE]
        r['post_events'] = CS_POST_EVENTS
        r['n_treated_obs_post'] = n_obs.tolist()
        r['manuscript_overall_att'] = cs_sum['results'][g]['overall_att']
        r['sanity_theta_matches_overall_att'] = bool(abs(r['theta_hat'] - cs_sum['results'][g]['overall_att']) < 1e-9)
        cs_res[g] = r

        # TWFE: equal-weighted target (matches earlier HonestDiD convention)
        tw = d['twfe_event_study'][g]
        beta_tw = np.array(tw['beta'], dtype=float)
        cov_tw = np.array(tw['cov'], dtype=float)
        l_tw = np.full(len(TWFE_POST), 1.0 / len(TWFE_POST))
        r2 = rr_bounds(beta_tw, cov_tw, TWFE_PRE, TWFE_POST, l_tw, B, seed)
        r2['event_levels'] = TWFE_LEVELS
        r2['pre_levels'] = [TWFE_LEVELS[i] for i in TWFE_PRE]
        r2['post_levels'] = [TWFE_LEVELS[i] for i in TWFE_POST]
        twfe_res[g] = r2

    # read back the earlier coordinate-averaged TWFE Mbar* for reference
    earlier = {}
    if OLD_HONEST.exists():
        old = json.loads(OLD_HONEST.read_text(encoding='utf-8'))
        for g in GROUPS:
            earlier[g] = old['results'][g]['breakdown_Mbar']

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy']},
        'covariance_summary_sha256': sha(COV_SUM),
        'cs_summary_sha256': sha(CS_SUM),
        'earlier_honest_did_sha256': sha(OLD_HONEST) if OLD_HONEST.exists() else None,
        'script_sha256': sha(__file__),
        'random_seed': seed, 'synthetic_data_used': False, 'draws': B,
        'method': 'Rambachan-Roth (2023) relative magnitudes, max norm; target-as-scalar; '
                  'honest CI = theta_hat +/- sigma_post * c_alpha(Mbar), '
                  'c_alpha = q_{0.95}(|Z_theta| + Mbar*max_s|Z_pre|), '
                  '(Z_theta, Z_pre) ~ N((0, beta_pre/sigma_post), S_std).',
        'post_term_form': '|Z_theta| = |l_post Z_post| (target-as-scalar), NOT mean(|Z_post|)',
        'targets': {
            'cs': 'observation-weighted average post effect = manuscript overall_att (+3.97 pp all group)',
            'twfe': 'equal-weighted average post effect (matches earlier HonestDiD convention)',
        },
        'note_cs_minus1': 'CS e=-1 column is normalised to 0 by construction and is excluded from pre and post.',
        'note_earlier_twfe': 'earlier_twfe_breakdown_Mbar_coordinate_averaged is read back from '
                             'honest_did_relative_magnitudes_20261109.py, which used mean(|Z_post|).',
        'earlier_twfe_breakdown_Mbar_coordinate_averaged': earlier,
        'cs_event_study_honest_did': cs_res,
        'twfe_event_study_honest_did_recomputed_target_scalar': twfe_res,
    }
    (out / 'honest_did_cs_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({
        g: {'cs_theta': round(cs_res[g]['theta_hat'], 4),
            'cs_sigma': round(cs_res[g]['sigma_post'], 4),
            'cs_t': round(cs_res[g]['t_ratio'], 3),
            'cs_Mbar': round(cs_res[g]['breakdown_Mbar'], 3),
            'twfe_Mbar_recomputed': round(twfe_res[g]['breakdown_Mbar'], 3),
            'earlier_twfe_Mbar': earlier.get(g)}
        for g in GROUPS
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
