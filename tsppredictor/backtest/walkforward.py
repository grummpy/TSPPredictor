"""Execution lag, IFT limits, purge/embargo, and path simulation.

A signal at decision index t posts ``lag`` sessions later and earns its first
return at index t+lag+1. The engine never earns the new mix on the signal day.
Training labels whose price window reaches the test start are purged, and an
extra embargo of h+lag decision rows is dropped on top of that.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from tsppredictor.rules.ift import is_g_only_move

FUNDS = ("G", "F", "C", "S", "I")


def one_hot(fund: str) -> np.ndarray:
    weights = np.zeros(len(FUNDS), dtype=float)
    weights[FUNDS.index(fund)] = 1.0
    return weights


def _validated_target(target: np.ndarray) -> np.ndarray | None:
    """Return a valid target allocation, retaining all-NaN as no request."""
    target = np.asarray(target, dtype=float)
    if np.isnan(target).all():
        return None
    if target.shape != (len(FUNDS),):
        raise ValueError("target weights must have one weight for each fund")
    if not np.isfinite(target).all() or np.any(target < 0):
        raise ValueError("target weights must be finite and non-negative")
    total = float(target.sum())
    if total <= 0:
        raise ValueError("target weights must sum to a positive number")
    return target / total


def last_train_index(test_start: int, h: int, lag: int) -> int:
    """Last decision index allowed in the training fold.

    Purge drops any sample whose label still uses a price at or after
    ``test_start`` (the label's last price is at ``s + lag + h``). Embargo
    drops another ``h + lag`` decision rows beyond that purge.
    """
    return test_start - 2 * (h + lag) - 1


def label_price_end(decision_index: int, h: int, lag: int) -> int:
    """Last price index used by the label of a decision."""
    return decision_index + lag + h


def forward_excess(prices: pd.DataFrame, h: int, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Excess return over G from price[t+lag] to price[t+lag+h], and the winning fund.

    G's excess is 0. The label is G when every risky fund has a negative excess.
    """
    px = prices.loc[:, list(FUNDS)].to_numpy(dtype=float)
    n = len(px)
    excess = np.full((n, len(FUNDS)), np.nan)
    labels = np.empty(n, dtype=object)
    labels[:] = None
    last = n - lag - h
    if last <= 0:
        return labels, excess
    start = px[lag : lag + last]
    end = px[lag + h : lag + h + last]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = end / start - 1.0
    ex = ret - ret[:, [0]]
    ex[:, 0] = 0.0
    excess[:last] = ex
    # Funds that do not exist yet are ignored. G remains a choice whenever its price exists.
    masked = np.where(np.isfinite(ex), ex, -np.inf)
    g_ok = np.isfinite(start[:, 0]) & np.isfinite(end[:, 0])
    choice = np.argmax(masked, axis=1)
    names = np.array(FUNDS, dtype=object)
    chosen = names[choice]
    labels[:last] = np.where(g_ok, chosen, None)
    return labels, excess


def simulate_targets(
    dates: pd.DatetimeIndex,
    targets: np.ndarray,
    lag: int,
    min_hold: int = 0,
    enforce_ift: bool = True,
    initial: np.ndarray | None = None,
) -> dict:
    """Turn a target-weight series into the weights that earn each session's return.

    ``targets[t]`` is the mix requested after the close of session t. A non-finite
    row means "no new request". The initial mix is an investment election and
    does not count as a transfer.
    """
    dates = pd.DatetimeIndex(dates)
    n = len(dates)
    targets = np.asarray(targets, dtype=float)
    if initial is None:
        if np.isfinite(targets[0]).all():
            initial = targets[0].copy()
        else:
            initial = one_hot("G")
    initial = np.asarray(initial, dtype=float)
    effective = initial.copy()
    posts: dict[int, np.ndarray] = {}
    last_switch = -10**9
    month_used: dict[str, int] = {}
    post_dates: list[pd.Timestamp] = []
    day_keys = [pd.Timestamp(ts).date() for ts in dates]

    for t in range(n):
        desired = _validated_target(targets[t])
        if desired is None:
            continue
        if np.allclose(desired, effective, atol=1e-6):
            continue
        to_g = desired[0] >= 0.999 and np.allclose(desired[1:], 0.0, atol=1e-8)
        if min_hold and (t - last_switch) < min_hold and not to_g:
            continue
        post_idx = t + lag
        if post_idx >= n:
            continue
        if enforce_ift:
            posted_on: date = day_keys[post_idx]
            month = f"{posted_on.year:04d}-{posted_on.month:02d}"
            used = month_used.get(month, 0)
            if used >= 2 and not is_g_only_move(effective, desired):
                continue
            if used < 2:
                month_used[month] = used + 1
        posts[post_idx] = desired.copy()
        # Fixed lag preserves posting order, so the latest queued mix is effective.
        effective = desired.copy()
        last_switch = t
        post_dates.append(dates[post_idx])

    holding = np.repeat(initial.reshape(1, -1), n, axis=0)
    current = initial.copy()
    for i in range(n):
        holding[i] = current
        if i in posts:
            current = posts[i]
    return {"weights": holding, "post_dates": post_dates, "n_transfers": len(post_dates), "month_used": month_used}


def portfolio_returns(prices: pd.DataFrame, weights: np.ndarray) -> np.ndarray:
    px = prices.loc[:, list(FUNDS)].to_numpy(dtype=float)
    rets = np.zeros_like(px)
    with np.errstate(divide="ignore", invalid="ignore"):
        rets[1:] = px[1:] / px[:-1] - 1.0
    # A fund with no price contributes nothing. Callers must not allocate to it.
    rets = np.where(np.isfinite(rets), rets, 0.0)
    port = (weights * rets).sum(axis=1)
    port[0] = 0.0
    return port


def wealth_from_prices(prices: pd.Series) -> np.ndarray:
    """Wealth indexed at 1 on the first valid price. Earlier rows are NaN."""
    px = prices.to_numpy(dtype=float)
    valid = np.isfinite(px) & (px > 0)
    wealth = np.full(len(px), np.nan)
    last = None
    started = False
    for i, (price, ok) in enumerate(zip(px, valid, strict=False)):
        if not ok:
            continue
        if not started:
            last = price
            started = True
            wealth[i] = 1.0
            continue
        wealth[i] = wealth[i - 1] * (price / last)
        last = price
    return wealth


def static_mix_wealth(prices: pd.DataFrame, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Buy and hold a mix. Share counts never change, so weights drift. No transfers."""
    px = prices.loc[:, list(FUNDS)].to_numpy(dtype=float)
    target = np.asarray(target, dtype=float)
    shares = np.zeros(len(FUNDS))
    for i, weight in enumerate(target):
        if weight > 0 and np.isfinite(px[0, i]) and px[0, i] > 0:
            shares[i] = weight / px[0, i]
    values = np.where(np.isfinite(px), px, 0.0) * shares
    wealth = values.sum(axis=1)
    wealth = wealth / wealth[0]
    totals = values.sum(axis=1, keepdims=True)
    totals[totals == 0] = np.nan
    weights = values / totals
    return wealth, weights


def rebalanced_mix(
    prices: pd.DataFrame,
    dates: pd.DatetimeIndex,
    target: np.ndarray,
    lag: int,
) -> dict:
    """Reset to ``target`` once a month, with the same execution lag and IFT limit."""
    px = prices.loc[:, list(FUNDS)].to_numpy(dtype=float)
    n = len(px)
    target = np.asarray(target, dtype=float)
    shares = np.zeros(len(FUNDS))
    for i, weight in enumerate(target):
        if weight > 0 and np.isfinite(px[0, i]) and px[0, i] > 0:
            shares[i] = weight / px[0, i]
    px_filled = np.where(np.isfinite(px), px, 0.0)
    wealth = np.ones(n)
    weights = np.repeat(target.reshape(1, -1), n, axis=0)
    decisions = []
    for i in range(1, n):
        prev = pd.Timestamp(dates[i - 1])
        cur = pd.Timestamp(dates[i])
        if prev.year != cur.year or prev.month != cur.month:
            decisions.append(i)
    pending: dict[int, int] = {}
    for t in decisions:
        post = t + lag
        earn = post + 1
        if earn < n:
            pending[earn] = post
    month_used: dict[str, int] = {}
    post_dates: list[pd.Timestamp] = []
    for i in range(1, n):
        if i in pending:
            post = pending[i]
            value = px_filled[i - 1] * shares
            total = float(value.sum())
            drifted = value / total if total else target
            if np.abs(drifted - target).sum() > 0.02:
                month = pd.Timestamp(dates[post]).strftime("%Y-%m")
                used = month_used.get(month, 0)
                allowed = used < 2 or is_g_only_move(drifted, target)
                if allowed:
                    if used < 2:
                        month_used[month] = used + 1
                    safe = np.where(px[i - 1] > 0, px[i - 1], np.nan)
                    shares = np.where(target > 0, target * total / safe, 0.0)
                    shares = np.where(np.isfinite(shares), shares, 0.0)
                    post_dates.append(pd.Timestamp(dates[post]))
        start_value = px_filled[i - 1] * shares
        start_total = float(start_value.sum())
        if start_total > 0:
            weights[i] = start_value / start_total
            wealth[i] = wealth[i - 1] * float((px_filled[i] * shares).sum()) / start_total
    return {"wealth": wealth, "weights": weights, "post_dates": post_dates, "n_transfers": len(post_dates)}


def constant_fund_path(prices: pd.DataFrame, fund: str) -> dict:
    weights = np.repeat(one_hot(fund).reshape(1, -1), len(prices), axis=0)
    px = prices[fund].to_numpy(dtype=float)
    wealth = px / px[0]
    rets = np.zeros(len(px))
    with np.errstate(divide="ignore", invalid="ignore"):
        rets[1:] = px[1:] / px[:-1] - 1.0
    rets = np.where(np.isfinite(rets), rets, 0.0)
    return {"wealth": wealth, "weights": weights, "returns": rets, "post_dates": [], "n_transfers": 0}
