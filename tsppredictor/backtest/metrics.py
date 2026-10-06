"""Portfolio metrics. CAGR uses the calendar span and a 365.25-day year."""

from __future__ import annotations

import numpy as np
import pandas as pd

FUNDS = ("G", "F", "C", "S", "I")


def wealth_from_returns(returns: np.ndarray) -> np.ndarray:
    rets = np.asarray(returns, dtype=float).copy()
    rets[0] = 0.0
    return np.cumprod(1.0 + rets)


def cagr(wealth: np.ndarray, dates: pd.DatetimeIndex | np.ndarray) -> float:
    wealth = np.asarray(wealth, dtype=float)
    if len(wealth) < 2 or wealth[0] <= 0 or wealth[-1] <= 0:
        return 0.0
    start = pd.Timestamp(dates[0])
    end = pd.Timestamp(dates[-1])
    days = (end - start).days
    if days <= 0:
        return 0.0
    return float((wealth[-1] / wealth[0]) ** (365.25 / days) - 1.0)


def max_drawdown(wealth: np.ndarray) -> tuple[float, int, int]:
    """Return (drawdown, peak_index, trough_index). Drawdown is zero when wealth never falls."""
    wealth = np.asarray(wealth, dtype=float)
    peak = wealth[0]
    peak_i = 0
    worst = 0.0
    worst_peak = 0
    worst_trough = 0
    for i, value in enumerate(wealth):
        if value >= peak:
            peak = value
            peak_i = i
        dd = value / peak - 1.0 if peak > 0 else 0.0
        if dd < worst:
            worst = float(dd)
            worst_peak = peak_i
            worst_trough = i
    return worst, worst_peak, worst_trough


def ulcer_index(wealth: np.ndarray) -> float:
    wealth = np.asarray(wealth, dtype=float)
    peak = np.maximum.accumulate(wealth)
    dd = np.where(peak > 0, wealth / peak - 1.0, 0.0)
    return float(np.sqrt(np.mean(dd**2)))


def annualized_vol(returns: np.ndarray, periods: int = 252) -> float:
    rets = np.asarray(returns, dtype=float)[1:]
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets, ddof=1) * np.sqrt(periods))


def sharpe_vs(returns: np.ndarray, baseline: np.ndarray, periods: int = 252) -> float:
    excess = np.asarray(returns, dtype=float)[1:] - np.asarray(baseline, dtype=float)[1:]
    if len(excess) < 2:
        return 0.0
    sd = np.std(excess, ddof=1)
    if sd <= 0:
        return 0.0
    return float(np.mean(excess) / sd * np.sqrt(periods))


def sortino_vs(returns: np.ndarray, baseline: np.ndarray, periods: int = 252) -> float:
    excess = np.asarray(returns, dtype=float)[1:] - np.asarray(baseline, dtype=float)[1:]
    downside = excess[excess < 0]
    if len(excess) < 2 or len(downside) == 0:
        return 0.0
    sd = np.sqrt(np.mean(downside**2))
    if sd <= 0:
        return 0.0
    return float(np.mean(excess) / sd * np.sqrt(periods))


def worst_12m(wealth: np.ndarray, dates: pd.DatetimeIndex, sessions: int = 252) -> float:
    wealth = np.asarray(wealth, dtype=float)
    if len(wealth) <= sessions:
        return float(wealth[-1] / wealth[0] - 1.0)
    window = wealth[sessions:] / wealth[:-sessions] - 1.0
    return float(np.min(window))


def one_way_turnover(weights: np.ndarray) -> float:
    """Sum of half the L1 weight changes. A full switch from one fund to another is 1."""
    weights = np.asarray(weights, dtype=float)
    if len(weights) < 2:
        return 0.0
    changes = np.abs(np.diff(weights, axis=0)).sum(axis=1)
    return float(0.5 * changes.sum())


def time_in_funds(weights: np.ndarray) -> dict[str, float]:
    weights = np.asarray(weights, dtype=float)
    means = weights.mean(axis=0) if len(weights) else np.zeros(5)
    return {name: float(means[i]) for i, name in enumerate(FUNDS)}


def dominant_fund(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    idx = np.argmax(weights, axis=1)
    names = np.array(FUNDS)
    out = names[idx]
    # Split allocations without a 50% fund are labeled MIX for whipsaw counting.
    top = weights.max(axis=1)
    out = np.where(top + 1e-9 >= 0.5, out, "MIX")
    return out


def count_whipsaws(fund_path: np.ndarray, window: int = 21) -> int:
    """Round trips that return to the prior fund within `window` sessions."""
    path = np.asarray(fund_path)
    switches: list[tuple[int, str, str]] = []
    for i in range(1, len(path)):
        if path[i] != path[i - 1]:
            switches.append((i, str(path[i - 1]), str(path[i])))
    count = 0
    for j, (i, frm, to) in enumerate(switches):
        for i2, frm2, to2 in switches[j + 1 :]:
            if i2 - i > window:
                break
            if to2 == frm and frm2 == to:
                count += 1
                break
    return count


def transfers_per_month(post_dates: list[pd.Timestamp]) -> tuple[float, int]:
    if not post_dates:
        return 0.0, 0
    months = pd.Series(1, index=pd.DatetimeIndex(post_dates)).groupby(lambda ts: (ts.year, ts.month)).sum()
    return float(months.mean()), int(months.max())


def slice_rebased(wealth: np.ndarray, dates: pd.DatetimeIndex, start, end) -> tuple[np.ndarray, pd.DatetimeIndex]:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    mask = (pd.DatetimeIndex(dates) >= start) & (pd.DatetimeIndex(dates) <= end)
    w = np.asarray(wealth, dtype=float)[mask]
    d = pd.DatetimeIndex(dates)[mask]
    if len(w) == 0:
        return w, d
    return w / w[0], d


def returns_from_wealth(wealth: np.ndarray) -> np.ndarray:
    wealth = np.asarray(wealth, dtype=float)
    rets = np.zeros(len(wealth))
    rets[1:] = wealth[1:] / wealth[:-1] - 1.0
    return rets


def summarize(
    wealth: np.ndarray,
    dates: pd.DatetimeIndex,
    weights: np.ndarray,
    g_returns: np.ndarray,
    post_dates: list | None = None,
    periods: int = 252,
) -> dict:
    rets = returns_from_wealth(wealth)
    dd, peak_i, trough_i = max_drawdown(wealth)
    growth = cagr(wealth, dates)
    vol = annualized_vol(rets, periods=periods)
    calmar = float(growth / abs(dd)) if dd < 0 else None
    mean_tpm, max_tpm = transfers_per_month(post_dates or [])
    dates = pd.DatetimeIndex(dates)
    return {
        "cagr": growth,
        "vol": vol,
        "sharpe_vs_g": sharpe_vs(rets, g_returns, periods=periods),
        "sortino_vs_g": sortino_vs(rets, g_returns, periods=periods),
        "max_drawdown": dd,
        "max_dd_peak": dates[peak_i].strftime("%Y-%m-%d") if len(dates) else None,
        "max_dd_trough": dates[trough_i].strftime("%Y-%m-%d") if len(dates) else None,
        "calmar": calmar,
        "ulcer": ulcer_index(wealth),
        "worst_12m": worst_12m(wealth, dates, sessions=periods),
        "turnover": one_way_turnover(weights),
        "time_in_fund": time_in_funds(weights),
        "whipsaws": count_whipsaws(dominant_fund(weights)),
        "transfers_per_month_mean": mean_tpm,
        "transfers_per_month_max": max_tpm,
        "n_days": int(len(wealth)),
        "hit_rate_vs_g": float(np.mean(rets[1:] > g_returns[1:])) if len(rets) > 1 else None,
    }
