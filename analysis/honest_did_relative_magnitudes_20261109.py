"""HonestDiD / Rambachan-Roth (2023) relative-magnitudes sensitivity (#2).

Answers: how large could the post-treatment violation of parallel trends be,
relative to the observed pre-trend, before the concentration effect stops being
significant? Under the relative-magnitudes class
    Delta^RM(Mbar) = { delta : |delta_post| <= Mbar * max_{s<0} |delta_s| },
the honest (1-alpha) CI for the target post effect is
    tau_hat_post +/- sigma_post * c_alpha(Mbar),
where c_alpha(Mbar) is the (1-alpha) quantile of
    |Z_post| + Mbar * max_{s<0} |Z_s|,
and (Z_post, Z_pre) ~ N( (0, beta_hat_pre/sigma_post), Sigma_hat / sigma_post^2 ).

Target = simple average of the post-period event-study coefficients.
Pre-trend coefs are the event-study coefficients for event time <= -2 (base = -1).
Built-in check: at Mbar=0, c_alpha(0) must equal ~1.96 (standard CI, no adjustment).

Read-only. Uses the Sigma-hat saved by save_event_study_covariance_20261109.py.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
COV_SUM = ROOT / 'outputs/2026-11-09_rng_event_study_covariance/run_001/event_study_covariance_summary.json'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def honest_interval(beta, cov, pre_idx, post_idx, Mbar, B=200000, alpha=0.05, seed=12345):
    """Honest CI for the average post effect under Delta^RM(Mbar)."""
    l_post = np.full(len(post_idx), 1.0 / len(post_idx))          # average post effect
    tau_hat = float(l_post @ beta[post_idx])
    sigma_post = float(np.sqrt(l_post @ cov[np.ix_(post_idx, post_idx)] @ l_post))
    beta_pre = beta[pre_idx]
    cov_std = cov / (sigma_post ** 2)                              # standardized covariance
    m = np.zeros(len(beta))
    m[pre_idx] = beta_pre / sigma_post
    m[post_idx] = 0.0
    rng = np.random.default_rng(seed)
    w = rng.multivariate_normal(m, cov_std, size=B)                # (B, 9)
    a = np.abs(w[:, post_idx]).mean(axis=1)                         # |Z_post|
    b = np.abs(w[:, pre_idx]).max(axis=1)                           # max_s |Z_s|
    q = np.quantile(a + Mbar * b, 1 - alpha)
    c_alpha = float(q)
    return tau_hat, sigma_post, c_alpha, beta_pre


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

    cov = json.loads(COV_SUM.read_text(encoding='utf-8'))
    pre_idx = [0, 1, 2, 3]          # pre_le_-5, k-4, k-3, k-2  (base = k-1)
    post_idx = [4, 5, 6, 7, 8]      # k0, k1, k2, k3, post_ge_4

    results = {}
    for gname in ['all_ever_operational', 'new_rng', 'use_switch']:
        g = cov['twfe_event_study'][gname]
        beta = np.array(g['beta'], dtype=float)
        C = np.array(g['cov'], dtype=float)
        l_post = np.full(len(post_idx), 1.0 / len(post_idx))
        tau_hat = float(l_post @ beta[post_idx])
        sigma_post = float(np.sqrt(l_post @ C[np.ix_(post_idx, post_idx)] @ l_post))
        beta_pre = beta[pre_idx]
        max_pre = float(np.abs(beta_pre).max())

        # c_alpha(Mbar) = quantile of (a + Mbar*b); precompute a, b once
        cov_std = C / (sigma_post ** 2)
        m = np.zeros(len(beta)); m[pre_idx] = beta_pre / sigma_post; m[post_idx] = 0.0
        rng = np.random.default_rng(seed)
        w = rng.multivariate_normal(m, cov_std, size=B)
        a = np.abs(w[:, post_idx]).mean(axis=1)
        b = np.abs(w[:, pre_idx]).max(axis=1)

        c0 = float(np.quantile(a, 0.95))                      # Mbar=0 -> should be ~1.96
        # breakdown: smallest Mbar where lower bound touches 0  <=>  c_alpha(Mbar) = tau_hat/sigma_post
        def c_alpha(Mb):
            return float(np.quantile(a + Mb * b, 0.95))

        # grid + refinement for breakdown Mbar*
        t_ratio = tau_hat / sigma_post
        lo, hi = 0.0, 8.0
        for _ in range(200):                                   # bisection on c_alpha(Mb)=t_ratio
            mid = 0.5 * (lo + hi)
            if c_alpha(mid) < t_ratio:
                lo = mid
            else:
                hi = mid
        Mstar = float(0.5 * (lo + hi))

        # CI at benchmark Mbar values
        ci = {}
        for Mb in [0.0, 0.5, 1.0, 2.0, 3.0, round(Mstar, 2)]:
            cc = c_alpha(Mb)
            ci[str(Mb)] = {'c_alpha': cc, 'ci95': [tau_hat - sigma_post * cc, tau_hat + sigma_post * cc]}

        results[gname] = {
            'target': 'average post-period effect (k0..post_ge_4)',
            'tau_hat_post_avg': tau_hat, 'sigma_post': sigma_post, 't_ratio': tau_hat / sigma_post,
            'beta_pre': beta_pre.tolist(), 'max_abs_pre_trend': max_pre,
            'c_alpha_Mbar0': c0, 'breakdown_Mbar': Mstar,
            'ci_by_Mbar': ci,
            'n_clusters': g['n_clusters'],
        }

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version, 'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy']},
        'covariance_summary_sha256': sha(COV_SUM), 'script_sha256': sha(__file__),
        'random_seed': seed, 'synthetic_data_used': False, 'draws': B,
        'method': 'Rambachan-Roth (2023) relative magnitudes, max norm; target = average post effect; '
                  'honest CI = tau +/- sigma_post * c_alpha(Mbar), c_alpha = q_{0.95}(|Z_post| + Mbar*max|Z_pre|), '
                  'Z ~ N((0, beta_pre/sigma_post), Sigma/sigma_post^2).',
        'pre_levels': ['pre_le_-5', 'k-4', 'k-3', 'k-2'], 'post_levels': ['k0', 'k1', 'k2', 'k3', 'post_ge_4'],
        'results': results,
    }
    (out / 'honest_did_relative_magnitudes_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
