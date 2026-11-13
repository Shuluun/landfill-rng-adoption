"""Convergence / gradient / separation diagnostics for the final reconciled
discrete-time logit (2026-11-10).

Motivation: the backfill summary records coefficient, SE and p but not whether the
hand-rolled IRLS actually converged, nor the final gradient, nor a separation check.
This script re-fits the single final model (ev_opshut_corr, T2 state-FE) with a
convergence-tracking IRLS and reports the diagnostics. It reuses the exact input
building and correction logic from driver_consequence_backfill_20261109.py so the
fit is bit-for-bit comparable, and writes to a NEW output dir (does not touch the
frozen backfill outputs).

Read-only inputs; deterministic; new run dir.
"""
import argparse, datetime as dt, hashlib, importlib.metadata, json, platform, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver_consequence_backfill_20261109 import (
    build_inputs, correct_event_map, build_py, CENSOR_YEAR, _sigmoid, sha,
)

ROOT = Path(__file__).resolve().parents[1]


def _norm_cdf(x):
    from math import erf
    return 0.5 * (1 + erf(x / np.sqrt(2)))


def irls_logit_diag(X, y, maxiter=300, tol=1e-10, ridge=1e-6):
    """IRLS with convergence tracking. Returns beta, se, and diagnostic dict."""
    n, p = X.shape
    beta = np.zeros(p)
    converged = False
    iters = 0
    for it in range(1, maxiter + 1):
        eta = X @ beta
        mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
        W = mu * (1 - mu)
        z = eta + (y - mu) / W
        Xw = X * np.sqrt(W)[:, None]
        zw = z * np.sqrt(W)
        A = Xw.T @ Xw + ridge * np.eye(p)
        b = Xw.T @ zw
        try:
            bn = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            bn = np.linalg.lstsq(A, b, rcond=None)[0]
        if np.max(np.abs(bn - beta)) < tol:
            beta = bn
            converged = True
            iters = it
            break
        beta = bn

    eta = X @ beta
    mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
    W = mu * (1 - mu)
    # final gradient of the ridge-penalized log-likelihood: X'(y-mu) - ridge*beta
    grad = X.T @ (y - mu) - ridge * beta
    grad_max = float(np.max(np.abs(grad)))
    # unpenalized information matrix for condition number
    H = X.T @ (X * W[:, None])
    eig = np.linalg.eigvalsh(H + 1e-12 * np.eye(p))
    cond = float(eig.max() / max(float(eig.min()), 1e-300))
    vcov = np.linalg.inv(H + ridge * np.eye(p))
    se = np.sqrt(np.diag(vcov))

    # unpenalized fit for comparison (ridge -> 0)
    unpen_ok = False
    unpen_beta = None
    try:
        ub = np.zeros(p)
        for it in range(1, maxiter + 1):
            eta = X @ ub
            mu = np.clip(_sigmoid(eta), 1e-12, 1 - 1e-12)
            W = mu * (1 - mu)
            z = eta + (y - mu) / W
            Xw = X * np.sqrt(W)[:, None]
            zw = z * np.sqrt(W)
            ub2 = np.linalg.solve(Xw.T @ Xw, Xw.T @ zw)
            if np.max(np.abs(ub2 - ub)) < tol:
                ub = ub2
                unpen_ok = True
                break
            ub = ub2
        unpen_beta = ub
    except np.linalg.LinAlgError:
        unpen_ok = False

    diag = {
        'converged': bool(converged),
        'iterations': int(iters if converged else maxiter),
        'max_abs_gradient_ridge': grad_max,
        'info_matrix_cond_number': cond,
        'max_abs_beta': float(np.max(np.abs(beta))),
        'n_params': int(p),
        'ridge': ridge,
    }
    if unpen_ok:
        diag['unpenalized_log_dist_coef'] = float(unpen_beta[1])
        diag['unpenalized_vs_ridge_log_dist_diff'] = float(unpen_beta[1] - beta[1])
    else:
        diag['unpenalized_log_dist_coef'] = None
        diag['unpenalized_vs_ridge_log_dist_diff'] = None
        diag['unpenalized_singular'] = True
    return beta, se, diag


def fit_T2_diag(py):
    y = py['y'].to_numpy()
    event_years = sorted(py.loc[py['y'] == 1, 'year'].unique())
    for t in event_years:
        py[f'yr_{t}'] = (py['year'] == t).astype(int)
    year_dummies = [f'yr_{t}' for t in event_years]

    per_state = py.groupby('state')['y'].agg(events='sum', size='size')
    drop = per_state[(per_state['events'] == 0) | (per_state['events'] == per_state['size'])].index.tolist()
    py2 = py[~py['state'].isin(drop)].copy()
    states2 = sorted(py2['state'].unique())
    ref = states2[0]
    for s in states2:
        if s != ref:
            py2[f'st_{s}'] = (py2['state'] == s).astype(int)
    state_cols = [f'st_{s}' for s in states2 if s != ref]
    cols2 = ['log_dist', 'log_waste'] + year_dummies + state_cols
    y2 = py2['y'].to_numpy()
    X2 = np.column_stack([np.ones(len(py2))] + [py2[c].to_numpy(float) for c in cols2])
    beta2, se2, diag = irls_logit_diag(X2, y2)
    p = float(2 * (1 - _norm_cdf(abs(beta2[1] / se2[1]))))
    names = ['intercept', 'log_dist', 'log_waste'] + year_dummies + state_cols
    order = np.argsort(-np.abs(beta2))
    top_abs = [
        {'name': names[i], 'beta': float(beta2[i]), 'se': float(se2[i]),
         'abs_beta': float(abs(beta2[i]))}
        for i in order[:8]
    ]
    return {
        'coef_log_dist': float(beta2[1]),
        'se': float(se2[1]),
        'p': p,
        'n_py': int(len(y2)),
        'n_events': int(y2.sum()),
        'n_landfills': int(py2['Landfill ID'].nunique()),
        'dropped_states': drop,
        'n_dropped_states': len(drop),
        'n_event_year_dummies': len(event_years),
        'top_abs_beta': top_abs,
        'diagnostics': diag,
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

    df, cohort, event_map, local_ev, bad_date_only, ever_op = build_inputs()
    ev_opshut_corr = correct_event_map(event_map['ev_opshut'], corrected_for_evall=False)
    py, _ = build_py(cohort, ev_opshut_corr)
    result = fit_T2_diag(py)

    summary = {
        'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'duration_seconds': round(time.monotonic() - start, 3),
        'command': subprocess.list2cmdline([sys.executable, *sys.argv]),
        'python': sys.version,
        'platform': platform.platform(),
        'packages': {k: importlib.metadata.version(k) for k in ['numpy', 'pandas']},
        'backfill_script_sha256': sha(ROOT / 'scripts/driver_consequence_backfill_20261109.py'),
        'script_sha256': sha(__file__),
        'workspace_git_state': 'not_a_git_repository',
        'random_seed': None,
        'model_run': True,
        'synthetic_data_used': False,
        'model': 'ev_opshut_corr, T2 state-FE, ridge-penalized IRLS (ridge=1e-6)',
        'result': result,
    }
    (out / 'driver_logit_diagnostics_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
