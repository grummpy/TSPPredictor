"""Event studies, seasonality, stress windows, and the stretch panels.

These are descriptions of the historical sample. They are not forecasts, and
the event studies are small samples in which each event is different.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from tsppredictor.backtest.metrics import max_drawdown

FUNDS = ("G", "F", "C", "S", "I")
SMALL_SAMPLE = "Small samples; each event is different."


def _cumpath(returns: np.ndarray) -> np.ndarray:
    out = np.ones(len(returns))
    for i in range(1, len(returns)):
        prev = out[i - 1]
        step = returns[i]
        out[i] = prev * (1.0 + step) if np.isfinite(step) else prev
    return out


def event_window_study(prices: pd.DataFrame, events: pd.DataFrame, pre: int = 20, post: int = 120) -> dict:
    """Median cumulative path from -pre to +post sessions, by category and fund."""
    index = pd.DatetimeIndex(prices.index)
    reaction = pd.to_datetime(events["first_reaction_tsp_date"], errors="coerce")
    usable = events.loc[reaction.notna()].copy()
    usable["reaction"] = pd.to_datetime(usable.loc[reaction.notna(), "first_reaction_tsp_date"])
    categories = []
    for category, group in usable.groupby("category"):
        locs = []
        for stamp in group["reaction"]:
            loc = int(index.searchsorted(pd.Timestamp(stamp), side="left"))
            if loc < pre or loc + post >= len(index):
                continue
            locs.append(loc)
        funds = {}
        for fund in FUNDS:
            rets = prices[fund].pct_change().to_numpy(dtype=float)
            paths = []
            for loc in locs:
                window = rets[loc - pre : loc + post + 1]
                if np.isfinite(window).sum() < pre:
                    continue
                window = np.where(np.isfinite(window), window, 0.0)
                window[0] = 0.0
                paths.append(_cumpath(window) - 1.0)
            if not paths:
                funds[fund] = {"n": 0, "median": [], "q25": [], "q75": []}
                continue
            mat = np.vstack(paths)
            funds[fund] = {
                "n": int(mat.shape[0]),
                "median": [None if not np.isfinite(v) else round(float(v), 6) for v in np.nanmedian(mat, axis=0)],
                "q25": [None if not np.isfinite(v) else round(float(v), 6) for v in np.nanpercentile(mat, 25, axis=0)],
                "q75": [None if not np.isfinite(v) else round(float(v), 6) for v in np.nanpercentile(mat, 75, axis=0)],
            }
        categories.append(
            {
                "category": str(category),
                "n_events": int(len(locs)),
                "offsets": list(range(-pre, post + 1)),
                "funds": funds,
            }
        )
    return {"pre": pre, "post": post, "note": SMALL_SAMPLE, "categories": categories}


def gpr_spike_study(prices: pd.DataFrame, gpr_spike: pd.Series, pre: int = 20, post: int = 60) -> dict:
    """Paths around days the lagged GPR z-score first crosses 2."""
    flag = gpr_spike.fillna(0).to_numpy(dtype=float)
    starts = [i for i in range(1, len(flag)) if flag[i] == 1 and flag[i - 1] == 0]
    index_ok = [i for i in starts if i >= pre and i + post < len(prices)]
    funds = {}
    rets = {fund: prices[fund].pct_change().to_numpy(dtype=float) for fund in ("G", "C", "F")}
    for fund, series in rets.items():
        paths = []
        for loc in index_ok:
            window = np.where(np.isfinite(series[loc - pre : loc + post + 1]), series[loc - pre : loc + post + 1], 0.0)
            window[0] = 0.0
            paths.append(_cumpath(window) - 1.0)
        if not paths:
            funds[fund] = {"n": 0, "median": []}
            continue
        mat = np.vstack(paths)
        funds[fund] = {
            "n": int(mat.shape[0]),
            "median": [round(float(v), 6) for v in np.nanmedian(mat, axis=0)],
        }
    return {
        "note": SMALL_SAMPLE + " GPR spikes use the lagged Caldara-Iacoviello index.",
        "n": int(len(index_ok)),
        "offsets": list(range(-pre, post + 1)),
        "funds": funds,
    }


def _ttest_mean(values: np.ndarray) -> tuple[float | None, float | None, int]:
    sample = values[np.isfinite(values)]
    n = int(len(sample))
    if n < 3:
        return None, None, n
    mean = float(sample.mean())
    sd = float(sample.std(ddof=1))
    t_stat = float(mean / (sd / np.sqrt(n))) if sd > 0 else None
    return mean, t_stat, n


def seasonality(prices: pd.DataFrame) -> dict:
    """Month-of-year excess over G, turn-of-month, and the November–April split.

    More than 10 cells are tested, so a multiple-testing warning is attached.
    """
    rets = prices[list(FUNDS)].pct_change()
    months = pd.DatetimeIndex(prices.index).month
    cells = []
    period = pd.DatetimeIndex(prices.index).to_period("M")
    for month in range(1, 13):
        mask = months == month
        for fund in ("F", "C", "S", "I"):
            excess_series = (rets[fund] - rets["G"]).where(mask)
            monthly = excess_series.groupby(period).sum(min_count=1)
            monthly = monthly[monthly.index.month == month]
            mean, t_stat, n = _ttest_mean(monthly.to_numpy(dtype=float))
            cells.append(
                {
                    "month": month,
                    "fund": fund,
                    "mean_excess": None if mean is None else round(mean, 6),
                    "t_stat": None if t_stat is None else round(t_stat, 3),
                    "n": n,
                }
            )
    # Turn of month: last session plus first three, versus the other sessions. Descriptive.
    index = pd.DatetimeIndex(prices.index)
    order = pd.Series(np.arange(len(index)), index=index).groupby(index.to_period("M")).cumcount()
    # The next session's month labels history. It is not used as a model feature.
    next_month = pd.Series(index.month, index=index).shift(-1)
    is_last = next_month.notna() & (next_month.to_numpy() != index.month)
    tom = (order.to_numpy() < 3) | is_last.to_numpy()
    tom_rows = []
    for fund in ("C", "S", "I", "F"):
        excess = (rets[fund] - rets["G"]).to_numpy(dtype=float)
        mean_in, t_in, n_in = _ttest_mean(excess[tom])
        mean_out, t_out, n_out = _ttest_mean(excess[~tom])
        tom_rows.append(
            {
                "fund": fund,
                "turn_mean": None if mean_in is None else round(mean_in, 6),
                "turn_n": n_in,
                "turn_t": None if t_in is None else round(t_in, 3),
                "other_mean": None if mean_out is None else round(mean_out, 6),
                "other_n": n_out,
                "other_t": None if t_out is None else round(t_out, 3),
            }
        )
    half = []
    nov_apr = np.isin(index.month, [11, 12, 1, 2, 3, 4])
    for fund in ("C", "S", "I", "F"):
        excess = (rets[fund] - rets["G"]).to_numpy(dtype=float)
        mean_w, t_w, n_w = _ttest_mean(excess[nov_apr])
        mean_s, t_s, n_s = _ttest_mean(excess[~nov_apr])
        half.append(
            {
                "fund": fund,
                "nov_apr_mean": None if mean_w is None else round(mean_w, 6),
                "nov_apr_t": None if t_w is None else round(t_w, 3),
                "nov_apr_n": n_w,
                "may_oct_mean": None if mean_s is None else round(mean_s, 6),
                "may_oct_t": None if t_s is None else round(t_s, 3),
                "may_oct_n": n_s,
            }
        )
    return {
        "cells": cells,
        "turn_of_month": tom_rows,
        "halves": half,
        "multiple_testing_warning": len(cells) > 10,
        "warning": (
            f"{len(cells)} month-by-fund cells are shown. Testing that many cells will "
            "produce large t-statistics by chance. These are descriptions, not a trading calendar."
        ),
    }


def _window_stats(wealth: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    wealth = np.asarray(wealth, dtype=float)
    if len(wealth) < 2 or not np.isfinite(wealth[0]) or wealth[0] == 0:
        return {"n": int(len(wealth)), "total_return": None, "max_drawdown": None}
    path = wealth / wealth[0]
    dd, peak_i, trough_i = max_drawdown(path)
    recovery = None
    if dd < 0:
        peak_value = path[peak_i]
        after = path[trough_i:]
        hits = np.where(after >= peak_value - 1e-12)[0]
        if len(hits):
            recovery = int(hits[0])
    return {
        "n": int(len(path)),
        "start": pd.Timestamp(dates[0]).strftime("%Y-%m-%d"),
        "end": pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
        "total_return": round(float(path[-1] - 1.0), 6),
        "max_drawdown": round(float(dd), 6),
        "recovery_sessions": recovery,
    }


def stress_report(prices: pd.DataFrame, monthly: pd.DataFrame, l_prices: pd.DataFrame) -> dict:
    """Replay named historical windows. Monthly data covers 2000–02."""
    daily_windows = [
        ("gfc_2007_2009", "2007-10-09", "2009-03-09"),
        ("covid_2020", "2020-02-19", "2020-08-31"),
        ("calendar_2022", "2021-12-31", "2022-12-30"),
        ("iran_2026", "2026-03-02", "2026-05-05"),
        ("taper_2013", "2013-05-22", "2013-12-31"),
        ("hiking_2022", "2022-01-03", "2022-12-30"),
    ]
    index = pd.DatetimeIndex(prices.index)
    panels = []
    series = {fund: prices[fund] for fund in FUNDS}
    for col in l_prices.columns:
        series[col] = l_prices[col]
    for name, start, end in daily_windows:
        mask = (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))
        funds = {}
        for fund, values in series.items():
            wealth = values.to_numpy(dtype=float)[mask]
            dates = index[mask]
            finite = np.isfinite(wealth)
            if finite.sum() < 2:
                continue
            first = int(np.argmax(finite))
            funds[fund] = _window_stats(wealth[first:], dates[first:])
        panels.append({"id": name, "cadence": "daily", "funds": funds})
    # Monthly windows, compounded from percent returns.
    month = monthly["month"].astype(str).str.slice(0, 7)
    monthly_windows = [
        ("dotcom_2000_2002", "2000-03", "2002-10"),
        ("rate_shock_1994", "1994-01", "1994-12"),
    ]
    for name, start, end in monthly_windows:
        mask = (month >= start) & (month <= end)
        funds = {}
        for src, dest in (("G Fund", "G"), ("F Fund", "F"), ("C Fund", "C"), ("S Fund", "S"), ("I Fund", "I")):
            rets = pd.to_numeric(monthly.loc[mask, src], errors="coerce").to_numpy(dtype=float) / 100.0
            if np.isfinite(rets).sum() < 2:
                continue
            wealth = np.cumprod(1.0 + np.where(np.isfinite(rets), rets, 0.0))
            dates = pd.to_datetime(month[mask] + "-01")
            funds[dest] = _window_stats(wealth, pd.DatetimeIndex(dates))
        panels.append({"id": name, "cadence": "monthly", "funds": funds, "note": "Compounded official monthly returns."})
    return {
        "windows": panels,
        "note": (
            "These are historical sequences applied to a buy-and-hold of each fund, "
            "including the G Fund and the F Fund. The F Fund lost money in the 2022 rate rise. "
            "Recovery is the number of sessions after the trough until the window's own peak is regained, "
            "and it is empty when that did not happen inside the window."
        ),
    }


def missed_best_days(c_returns: np.ndarray, weights: np.ndarray, ks: tuple[int, ...] = (10, 20, 50)) -> dict:
    """How many of the best C Fund sessions were spent in the G Fund."""
    rets = np.asarray(c_returns, dtype=float)
    weights = np.asarray(weights, dtype=float)
    valid = np.isfinite(rets)
    order = np.argsort(np.where(valid, rets, -np.inf))
    ranked = [int(i) for i in order[::-1] if valid[i]]
    worst = [int(i) for i in order if valid[i]]
    rows = []
    for k in ks:
        chosen = ranked[:k]
        in_g = [i for i in chosen if weights[i, 0] >= 0.5]
        missed_sum = float(np.sum(rets[in_g])) if in_g else 0.0
        rows.append({"k": k, "missed": int(len(in_g)), "sum_of_missed_simple_returns": round(missed_sum, 6)})
    best50 = set(ranked[:50])
    worst50 = set(worst[:50])
    near = 0
    for b in best50:
        if any(abs(b - w) <= 10 for w in worst50):
            near += 1
    return {
        "rows": rows,
        "best50_within_10_sessions_of_a_worst50": near,
        "note": (
            "A session counts as missed when the allocation earning that session's return "
            "had at least half its weight in G. The sum is of simple returns, not a compounded gap. "
            f"{near} of the 50 best C Fund sessions fell within 10 sessions of one of the 50 worst."
        ),
    }


def cost_of_being_wrong(
    chosen: np.ndarray,
    labels: np.ndarray,
    excess: np.ndarray,
    fund: str,
    balance: float = 100_000.0,
) -> dict:
    """Historical h-day excess versus G when this fund was chosen and was not the winner."""
    fund_i = FUNDS.index(fund)
    rows = []
    for i, (pick, label) in enumerate(zip(chosen, labels, strict=False)):
        if pick != fund or label is None or label == fund:
            continue
        value = excess[i, fund_i]
        if np.isfinite(value):
            rows.append(float(value))
    sample = np.asarray(rows, dtype=float)
    if len(sample) == 0:
        return {
            "fund": fund,
            "n_wrong": 0,
            "median_excess_vs_g": None,
            "worst_10pct_excess_vs_g": None,
            "mean_excess_vs_g": None,
            "hypothetical_balance": balance,
            "hypothetical_dollar_at_worst_10pct": None,
            "note": "No comparable out-of-sample misses were found for this fund.",
        }
    median = float(np.median(sample))
    worst = float(np.quantile(sample, 0.10))
    mean = float(np.mean(sample))
    return {
        "fund": fund,
        "n_wrong": int(len(sample)),
        "n_total_comparable": int(np.sum((chosen == fund) & np.array([lab is not None for lab in labels]))),
        "median_excess_vs_g": round(median, 6),
        "worst_10pct_excess_vs_g": round(worst, 6),
        "mean_excess_vs_g": round(mean, 6),
        "hypothetical_balance": balance,
        "hypothetical_dollar_at_median": round(balance * median, 2),
        "hypothetical_dollar_at_worst_10pct": round(balance * worst, 2),
        "note": (
            "These are h-day excess returns versus the G Fund on out-of-sample dates when the policy "
            "chose this fund and a different fund had the higher excess. The dollar figures apply that "
            "historical excess to a hypothetical balance. They are not a forecast."
        ),
    }


def l_fund_xray(prices: pd.DataFrame, l_prices: pd.Series, window: int = 252) -> dict:
    """Nonnegative least squares of L Fund daily returns on G, F, C, S, and I.

    Weights are rescaled to sum to 1. This is an estimate of the mix, not the holdings.
    """
    joined = pd.DataFrame({fund: prices[fund] for fund in FUNDS})
    joined["L"] = l_prices
    joined = joined.dropna()
    if len(joined) < window + 5:
        return {"available": False, "note": "Not enough overlapping L Fund prices."}
    rets = joined.pct_change().dropna()
    tail = rets.iloc[-window:]
    x = tail[list(FUNDS)].to_numpy(dtype=float)
    y = tail["L"].to_numpy(dtype=float)
    coef, _residual = nnls(x, y)
    total = float(coef.sum())
    weights = coef / total if total > 0 else coef
    return {
        "available": True,
        "fund": str(l_prices.name),
        "window_sessions": window,
        "start": tail.index[0].strftime("%Y-%m-%d"),
        "end": tail.index[-1].strftime("%Y-%m-%d"),
        "weights": {name: round(float(weights[i]), 4) for i, name in enumerate(FUNDS)},
        "note": "Estimate from nonnegative least squares on daily returns. Weights are forced to sum to 1. Not the published L Fund holdings.",
    }


def g_versus_f(prices: pd.DataFrame, monthly: pd.DataFrame) -> dict:
    """G and F through rate-rise windows. F can lose money when yields rise."""
    windows = stress_report(prices, monthly, l_prices=pd.DataFrame(index=prices.index))
    wanted = {"calendar_2022", "hiking_2022", "taper_2013", "rate_shock_1994"}
    rows = [row for row in windows["windows"] if row["id"] in wanted]
    return {
        "windows": rows,
        "note": (
            "The G Fund's share price has not fallen in this sample. The F Fund has. "
            "In the 1994 and 2022 rate rises, F was the fund that lost money. "
            "Parking in F is a different risk from parking in G."
        ),
    }


def fan_chart(fund_returns: np.ndarray, dates: pd.DatetimeIndex, n_boot: int = 300, seed: int = 0) -> dict:
    """Block-bootstrap terminal wealth at 1, 3, and 5 years. Resampled history, not a forecast."""
    rets = np.asarray(fund_returns, dtype=float)
    rets = rets[np.isfinite(rets)]
    horizons = {"1y": 252, "3y": 252 * 3, "5y": 252 * 5}
    block = 21
    rng = np.random.default_rng(seed)
    out = {}
    if len(rets) < block + 5:
        return {"available": False}
    n_blocks = {name: int(np.ceil(h / block)) for name, h in horizons.items()}
    for name, horizon in horizons.items():
        starts = rng.integers(0, len(rets) - block + 1, size=(n_boot, n_blocks[name]))
        terminals = np.empty(n_boot)
        for i in range(n_boot):
            idx = np.concatenate([np.arange(s, s + block) for s in starts[i]])[:horizon]
            terminals[i] = float(np.prod(1.0 + rets[idx]))
        qs = np.quantile(terminals, [0.1, 0.25, 0.5, 0.75, 0.9])
        out[name] = {
            "horizon_sessions": horizon,
            "p10": round(float(qs[0]), 4),
            "p25": round(float(qs[1]), 4),
            "p50": round(float(qs[2]), 4),
            "p75": round(float(qs[3]), 4),
            "p90": round(float(qs[4]), 4),
        }
    return {
        "available": True,
        "as_of": pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
        "paths": out,
        "note": "Resampled history of this fund's own daily returns. Not a forecast and not a probability of future returns.",
    }


def scarcity_upper_bound(raw_targets: np.ndarray, limited_weights: np.ndarray, fund_returns: np.ndarray) -> dict:
    """A labeled upper bound on the transfer limit. It ignores execution lag."""
    raw = np.asarray(raw_targets, dtype=float)
    held = np.asarray(limited_weights, dtype=float)
    rets = np.asarray(fund_returns, dtype=float)
    if len(raw) != len(held):
        return {"available": False}
    # Days the unconstrained target wanted less G than the limited book actually held.
    wanted_less_g = np.isfinite(raw).all(axis=1) & (raw[:, 0] + 1e-8 < held[:, 0])
    worst = np.isfinite(rets) & (rets <= np.nanquantile(rets[np.isfinite(rets)], 0.05))
    both = wanted_less_g & worst
    return {
        "available": True,
        "worst_decile_sessions": int(worst.sum()),
        "of_which_limit_kept_more_g": int(both.sum()),
        "note": (
            "Upper bound that ignores execution lag. It counts worst-decile C Fund sessions on which "
            "the unconstrained target wanted less G than the transfer-limited book held. "
            "It is not an estimate of the value of saving a move."
        ),
    }
