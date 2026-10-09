"""Block-bootstrap intervals, deflated Sharpe, calibration, and verdicts."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from tsppredictor.backtest.metrics import cagr


def block_bootstrap_excess_cagr(
    strategy_returns: np.ndarray,
    baseline_returns: np.ndarray,
    dates: pd.DatetimeIndex,
    block: int = 21,
    n_boot: int = 400,
    seed: int = 0,
) -> dict:
    """90% interval for CAGR(strategy) minus CAGR(baseline) on block-resampled paths.

    Each path keeps the original calendar span, so the CAGR exponent matches the
    reported point estimate.
    """
    rs = np.asarray(strategy_returns, dtype=float)
    rb = np.asarray(baseline_returns, dtype=float)
    n = len(rs)
    point_s = cagr(np.cumprod(1.0 + _zero_first(rs)), dates)
    point_b = cagr(np.cumprod(1.0 + _zero_first(rb)), dates)
    point = point_s - point_b
    if n < block + 2:
        return {"excess_cagr": point, "ci90": [point, point], "n_boot": 0}
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(n_boot, n_blocks))
    excess = np.empty(n_boot)
    days = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    for i in range(n_boot):
        idx = np.concatenate([np.arange(s, s + block) for s in starts[i]])[:n]
        growth_s = np.prod(1.0 + rs[idx])
        growth_b = np.prod(1.0 + rb[idx])
        excess[i] = growth_s ** (365.25 / days) - growth_b ** (365.25 / days)
    low, high = np.quantile(excess, [0.05, 0.95])
    return {"excess_cagr": float(point), "ci90": [float(low), float(high)], "n_boot": n_boot}


def _zero_first(rets: np.ndarray) -> np.ndarray:
    out = np.asarray(rets, dtype=float).copy()
    out[0] = 0.0
    return out


def period_sharpe(excess: np.ndarray) -> float:
    x = np.asarray(excess, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return 0.0
    sd = np.std(x, ddof=1)
    if sd <= 0:
        return 0.0
    return float(np.mean(x) / sd)


def deflated_sharpe_ratio(excess: np.ndarray, n_trials: int) -> float:
    """Probability that the Sharpe exceeds the expected maximum under N trials.

    Bailey and Lopez de Prado (2014). The Sharpe is per observation, not annualized.
    """
    x = np.asarray(excess, dtype=float)
    x = x[np.isfinite(x)]
    t = len(x)
    if t < 10:
        return 0.0
    sr = period_sharpe(x)
    skew = float(pd.Series(x).skew())
    kurt = float(pd.Series(x).kurt() + 3.0)  # pandas kurtosis is excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0
    n_trials = max(int(n_trials), 1)
    euler = 0.5772156649015329
    if n_trials == 1:
        sr0 = 0.0
    else:
        z1 = norm.ppf(1.0 - 1.0 / n_trials)
        z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        var_factor = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
        var_sr = max(var_factor, 1e-12) / (t - 1)
        sr0 = np.sqrt(var_sr) * ((1 - euler) * z1 + euler * z2)
    denom = np.sqrt(max(1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2, 1e-12))
    stat = (sr - sr0) * np.sqrt(t - 1) / denom
    return float(norm.cdf(stat))


def verdict(excess_cagr: float, ci90: list[float], dsr: float | None) -> str:
    """Beat only when the point estimate and the 90% interval are positive and DSR >= 0.95.

    A negative point estimate whose interval lies entirely below zero is
    Underperformed. Everything else is Inconclusive, including a loss that
    is not distinguishable from noise.
    """
    low, high = ci90
    if excess_cagr > 0 and low > 0 and dsr is not None and dsr >= 0.95:
        return "Beat"
    if excess_cagr < 0 and high < 0:
        return "Underperformed"
    return "Inconclusive"


def reliability(probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> dict:
    """Reliability table for the probability of the chosen class, plus multiclass scores.

    ``probabilities`` is either a 1-d confidence or a 2-d probability matrix.
    ``outcomes`` is 1 when the decision was right, aligned to each row.
    When a matrix is passed, Brier and log loss use the matrix and ``y_class``.
    """
    conf = np.asarray(probabilities, dtype=float)
    right = np.asarray(outcomes, dtype=float)
    mask = np.isfinite(conf) & np.isfinite(right)
    conf = conf[mask]
    right = right[mask]
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = []
    counts = []
    for i in range(n_bins):
        if i == n_bins - 1:
            sel = (conf >= edges[i]) & (conf <= edges[i + 1])
        else:
            sel = (conf >= edges[i]) & (conf < edges[i + 1])
        n = int(sel.sum())
        counts.append(n)
        bins.append(
            {
                "low": float(edges[i]),
                "high": float(edges[i + 1]),
                "n": n,
                "mean_predicted": float(conf[sel].mean()) if n else None,
                "empirical_rate": float(right[sel].mean()) if n else None,
            }
        )
    return {"bins": bins, "n": int(len(conf)), "count_sum": int(sum(counts))}


def brier_skill_binary(prob: np.ndarray, outcome: np.ndarray, base_rate: float | None = None) -> dict:
    p = np.asarray(prob, dtype=float)
    y = np.asarray(outcome, dtype=float)
    mask = np.isfinite(p) & np.isfinite(y)
    p = np.clip(p[mask], 0.0, 1.0)
    y = y[mask]
    if len(y) == 0:
        return {"brier": None, "log_loss": None, "brier_skill": None, "n": 0}
    brier = float(np.mean((p - y) ** 2))
    rate = float(y.mean()) if base_rate is None else float(base_rate)
    brier_ref = float(np.mean((rate - y) ** 2))
    skill = float(1.0 - brier / brier_ref) if brier_ref > 0 else 0.0
    pp = np.clip(p, 1e-6, 1 - 1e-6)
    logloss = float(-np.mean(y * np.log(pp) + (1 - y) * np.log(1 - pp)))
    return {"brier": brier, "log_loss": logloss, "brier_skill": skill, "n": int(len(y)), "base_rate": rate}


def multiclass_brier(proba: np.ndarray, y: np.ndarray, classes: list[str]) -> float:
    proba = np.asarray(proba, dtype=float)
    y = np.asarray(y)
    one = np.zeros_like(proba)
    index = {name: i for i, name in enumerate(classes)}
    for row, label in enumerate(y):
        if label in index:
            one[row, index[label]] = 1.0
    return float(np.mean(np.sum((proba - one) ** 2, axis=1)))
