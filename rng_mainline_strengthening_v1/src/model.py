"""Logistic likelihood and site-score spatial uncertainty for deployment comparisons."""

from dataclasses import dataclass
from math import log, sqrt

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.special import expit
from scipy.spatial.distance import cdist
from scipy.stats import norm

from common import EARLY, PERIODS, SITE

LN2 = log(2)
CUTOFFS = (25, 50, 100, 200, 400)


@dataclass
class Fit:
    stats: dict
    influence: pd.Series


class SpatialWeights:
    def __init__(self, sites):
        self.ids = sites[SITE].to_numpy()
        self.positions = pd.Series(np.arange(len(self.ids)), index=self.ids)
        lat, lon = np.radians(sites[["lat", "lon"]].to_numpy()).T
        xyz = np.column_stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)))
        self.distance = 2 * 6371.0088 * np.arcsin(np.minimum(1, cdist(xyz, xyz) / 2))
        self.kernel100 = np.maximum(1 - self.distance / 100, 0)

    def variance(self, influence, cutoff=100):
        weight = self.kernel100 if cutoff == 100 else np.maximum(1 - self.distance / cutoff, 0)
        vector = influence.reindex(self.ids, fill_value=0).to_numpy()
        value = float(vector @ weight @ vector)
        if value < -1e-12:
            raise ValueError(f"Negative spatial variance {value}")
        return max(0, value)


def support(sites, event_map, end):
    year = sites[SITE].map(event_map)
    event = year.between(sites["entry"], end)
    return set(sites.loc[event, "state"])


def make_risk(sites, event_map, end, periods=PERIODS):
    # A row with n years has n Bernoulli trials with an identical design vector.
    # Its likelihood and site score equal those of the corresponding annual rows.
    year = sites[SITE].map(event_map)
    stop = year.clip(upper=end).fillna(end).astype(int)
    risk = []
    for first, last in periods:
        if first > end:
            break
        last = min(last, end)
        n = np.minimum(stop, last) - np.maximum(sites["entry"], first) + 1
        mask = n.gt(0)
        group = sites.loc[mask].copy()
        group["period"] = first
        group["n"] = n[mask]
        group["y"] = year[mask].between(np.maximum(sites.loc[mask, "entry"], first), last).astype(int)
        risk.append(group)
    return pd.concat(risk, ignore_index=True)


def fit_logit(X, y, n, ridge=0):
    p = X.shape[1]
    beta = np.zeros(p)
    rate = y.sum() / n.sum()
    if not 0 < rate < 1:
        raise ValueError("The model requires events and non-events")
    beta[0] = log(rate / (1 - rate))
    penalty = np.diag([0.0] + [ridge] * (p - 1))

    def loss(b):
        eta = X @ b
        return np.sum(n * np.logaddexp(0, eta) - y * eta) + 0.5 * b @ penalty @ b

    for iteration in range(1, 101):
        mu = expit(X @ beta)
        residual = y - n * mu
        information = X.T @ (X * (n * mu * (1 - mu))[:, None])
        gradient = X.T @ residual - penalty @ beta
        if np.max(np.abs(gradient)) < 1e-7:
            return beta, information, penalty, residual, iteration, float(np.max(np.abs(gradient)))
        step = np.linalg.solve(information + penalty, gradient)
        multiplier = 1.0
        current = loss(beta)
        while loss(beta + multiplier * step) > current + 1e-9:
            multiplier *= 0.5
            if multiplier < 2**-20:
                raise RuntimeError("Newton line search did not converge")
        beta += multiplier * step
    raise RuntimeError("Newton fit did not converge in 100 iterations")


def separation(X, y, n):
    # A direction with nonnegative signed margins everywhere and a positive
    # margin somewhere certifies complete or quasi-complete separation.
    scale = np.maximum(1, np.max(np.abs(X), axis=0))
    signed = np.vstack((X[y > 0], -X[n > y])) / scale
    result = linprog(
        -signed.mean(axis=0), A_ub=-signed, b_ub=np.zeros(len(signed)),
        bounds=[(-1.0, 1.0)] * X.shape[1], method="highs",
    )
    if not result.success:
        raise RuntimeError(f"Separation LP failed: {result.message}")
    margins = signed @ result.x
    if margins.min() > 1e-8:
        return "complete"
    return "quasi_complete" if margins.max() > 1e-7 else "no_direction_detected"


def fit(risk, spatial, *, state_fe=True, controls=("log_dist", "log_waste"),
        calendar=True, diagnose=False, ridge=0):
    names = list(controls)
    design = risk[list(controls)].astype(float).copy()
    for term in (["period"] if calendar else []) + (["state"] if state_fe else []):
        indicators = pd.get_dummies(risk[term], prefix=term, drop_first=True, dtype=float)
        design = pd.concat([design, indicators], axis=1)
        names.extend(indicators.columns)
    X = np.column_stack([np.ones(len(risk)), design.to_numpy()])
    y = risk["y"].to_numpy()
    n = risk["n"].to_numpy()
    sep = separation(X, y, n) if diagnose else "not_run"
    if sep in {"complete", "quasi_complete"} and not ridge:
        raise RuntimeError(f"Unpenalized model is separated ({sep})")
    beta, H, penalty, residual, iterations, max_gradient = fit_logit(X, y, n, ridge)
    # Project scores onto the log-distance contrast before spatial aggregation.
    contrast = np.eye(X.shape[1])[:, 1]
    influence = pd.Series(residual * (X @ np.linalg.solve(H + penalty, contrast)))
    influence = influence.groupby(risk[SITE].to_numpy()).sum()
    coef = float(beta[1])
    se = sqrt(spatial.variance(influence))
    coef_lower = coef - norm.ppf(0.975) * se
    coef_upper = coef + norm.ppf(0.975) * se
    return Fit({
        "n_landfills": int(risk[SITE].nunique()),
        "n_states": int(risk["state"].nunique()),
        "risk_years": int(n.sum()),
        "n_events": int(y.sum()),
        "ln_distance": coef,
        "cluster_se": sqrt(float(influence @ influence)),
        "conley100_se": se,
        "ln_distance_ci_low": float(coef_lower),
        "ln_distance_ci_high": float(coef_upper),
        "doubling_or": float(np.exp(LN2 * coef)),
        "doubling_or_low": float(np.exp(LN2 * coef_lower)),
        "doubling_or_high": float(np.exp(LN2 * coef_upper)),
        "parameters": X.shape[1],
        "rank": int(np.linalg.matrix_rank(X)),
        "info_condition": float(np.linalg.cond(H)),
        "max_abs_gradient": max_gradient,
        "iterations": iterations,
        "separation": sep,
        "ridge": ridge,
        "state_fe": state_fe,
        "calendar": calendar,
        "controls": "+".join(controls),
    }, influence)


def paired_difference(a, b, spatial):
    value = b.stats["ln_distance"] - a.stats["ln_distance"]
    se = sqrt(spatial.variance(b.influence.subtract(a.influence, fill_value=0)))
    return {
        "delta_ln_distance": value,
        "paired_conley100_se": se,
        "delta_ci_low": float(value - norm.ppf(0.975) * se),
        "delta_ci_high": float(value + norm.ppf(0.975) * se),
    }
