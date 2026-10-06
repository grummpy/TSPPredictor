"""Rule hit rates, the probability average, and the allocation policy.

A rule becomes a probability by giving its chosen fund the hit rate measured
on the purged past only. The ensemble averages whichever of the logistic model,
the gradient-boosting model, and that rule probability are finite. The policy
then multiplies those probabilities by the in-fold mean excess over G.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tsppredictor.backtest.walkforward import last_train_index
from tsppredictor.models.ml import policy_from_proba

FUNDS = ("G", "F", "C", "S", "I")


def chosen_index(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    idx = np.argmax(weights, axis=1)
    top = np.nanmax(weights, axis=1)
    # A split without a 50% fund is not a single-fund call.
    idx = np.where(np.isfinite(top) & (top + 1e-9 >= 0.5), idx, 0)
    return idx.astype(int)


def best_rule_probabilities(
    rule_weights: dict[str, np.ndarray],
    labels: np.ndarray,
    h: int,
    lag: int,
    min_count: int = 50,
) -> tuple[np.ndarray, list]:
    """Map the best purged rule into a 5-fund probability on each row.

    The chosen fund receives the historical hit rate, clipped to [0.05, 0.95].
    The rest is spread across the other four funds. Which rule is "best" is
    decided only from decision rows whose label window ends before t.
    """
    n = len(labels)
    names = list(rule_weights)
    chosen = {name: chosen_index(rule_weights[name]) for name in names}
    fund_index = {name: i for i, name in enumerate(FUNDS)}
    lab = np.full(n, -1, dtype=int)
    for i, label in enumerate(labels):
        if label in fund_index:
            lab[i] = fund_index[label]
    valid = lab >= 0
    hit_cum = {}
    cnt_cum = {}
    for name, picks in chosen.items():
        hit_cum[name] = np.cumsum((picks == lab) & valid)
        cnt_cum[name] = np.cumsum(valid)
    proba = np.full((n, len(FUNDS)), np.nan)
    which: list = [None] * n
    gap = h + lag + 1
    for t in range(n):
        end = t - gap
        if end < min_count:
            continue
        rates = []
        for name in names:
            count = int(cnt_cum[name][end])
            if count < min_count:
                rates.append(-1.0)
            else:
                rates.append(float(hit_cum[name][end] / count))
        if max(rates) < 0:
            continue
        name = names[int(np.argmax(rates))]
        rate = float(np.clip(rates[names.index(name)], 0.05, 0.95))
        vec = np.full(len(FUNDS), (1.0 - rate) / (len(FUNDS) - 1))
        vec[int(chosen[name][t])] = rate
        proba[t] = vec
        which[t] = name
    return proba, which


def average_probabilities(*arrays: np.ndarray) -> np.ndarray:
    """Average finite probability rows. A missing model does not dilute the others."""
    stack = np.stack([np.asarray(a, dtype=float) for a in arrays], axis=0)
    finite = np.isfinite(stack).all(axis=2)
    filled = np.where(np.isfinite(stack), stack, 0.0)
    count = finite.sum(axis=0)
    total = filled.sum(axis=0)
    out = np.full(stack.shape[1:], np.nan)
    ok = count > 0
    out[ok] = total[ok] / count[ok, None]
    return out


def _listed_mask(prices: pd.DataFrame, index: int) -> np.ndarray:
    row = prices.iloc[index]
    out = np.zeros(len(FUNDS), dtype=bool)
    for i, name in enumerate(FUNDS):
        value = row[name] if name in prices.columns else np.nan
        out[i] = bool(np.isfinite(value) and value > 0)
    return out


def policy_over_folds(
    proba: np.ndarray,
    excess: np.ndarray,
    retrain_points: list[int],
    h: int,
    lag: int,
    prices: pd.DataFrame,
    min_prob: float = 0.34,
) -> tuple[np.ndarray, list[dict]]:
    """Apply the probability × mean-excess policy inside each walk-forward segment.

    Mean excess is the average on the purged training rows of that segment.
    A fund with no price on the posting date is not selected.
    """
    n = len(proba)
    out = np.full((n, len(FUNDS)), np.nan)
    folds: list[dict] = []
    if not retrain_points:
        return out, folds
    bounds = list(retrain_points) + [n]
    px_len = len(prices)
    for i, start in enumerate(retrain_points):
        stop = bounds[i + 1]
        s_max = last_train_index(int(start), h, lag)
        s_max = min(max(s_max, 0), n - 1)
        block = np.asarray(excess[: s_max + 1], dtype=float)
        with np.errstate(all="ignore"):
            mu = np.nanmean(block, axis=0)
        mu = np.where(np.isfinite(mu), mu, 0.0)
        mu[0] = 0.0
        seg_p = proba[start:stop]
        seg = policy_from_proba(seg_p, mu, min_prob=min_prob)
        bad = ~np.isfinite(seg_p).all(axis=1)
        seg[bad] = np.nan
        for k in range(stop - start):
            if not np.isfinite(seg[k]).all():
                continue
            ref = min(start + k + lag, px_len - 1)
            alive = _listed_mask(prices, ref)
            pick = int(np.argmax(seg[k]))
            if not alive[pick]:
                if alive[0]:
                    seg[k] = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
                else:
                    seg[k] = np.nan
        out[start:stop] = seg
        folds.append(
            {
                "start_index": int(start),
                "stop_index": int(stop),
                "mean_excess": [float(v) for v in mu],
            }
        )
    return out, folds
