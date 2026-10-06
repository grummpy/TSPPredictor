"""Transparent allocation rules. Each returns a weight matrix aligned to ``features``.

Missing inputs stay in the G Fund. These are hypotheses to test, not claims.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tsppredictor.backtest.walkforward import one_hot

FUNDS = ("G", "F", "C", "S", "I")


def _fill_fund(flags: pd.Series, when_true: str) -> np.ndarray:
    out = np.repeat(one_hot("G").reshape(1, -1), len(flags), axis=0)
    hot = one_hot(when_true)
    mask = flags.fillna(0).to_numpy() > 0.5
    out[mask] = hot
    return out


def sma_10m(features: pd.DataFrame) -> np.ndarray:
    """Hold C when its price is above the 10-month average, otherwise G."""
    return _fill_fund(features["c_above_sma10m"], "C")


def dual_momentum(features: pd.DataFrame) -> np.ndarray:
    """Hold the 12-month leader among C, S, and I when it also beat G, else G."""
    out = np.repeat(one_hot("G").reshape(1, -1), len(features), axis=0)
    for fund in ("c", "s", "i"):
        mask = features[f"{fund}_dual_mom"].fillna(0).to_numpy() > 0.5
        out[mask] = one_hot(fund.upper())
    return out


def curve_trend(features: pd.DataFrame) -> np.ndarray:
    """Hold C only when the lagged curve is not inverted and C is above its 200-session average."""
    ok = (features["curve_inverted"].fillna(1) < 0.5) & (features["c_above_sma200"].fillna(0) > 0.5)
    return _fill_fund(ok.astype(float), "C")


def vol_target(features: pd.DataFrame, target_vol: float = 0.15, band: float = 0.10) -> np.ndarray:
    """Monthly volatility target between C and G.

    Weight on C is target_vol / realized vol, clipped to [0, 1]. The weight is
    refreshed on the first session of each month and only when it moves by at
    least ``band`` (10 percentage points) versus the last posted target.
    """
    n = len(features)
    out = np.repeat(one_hot("G").reshape(1, -1), n, axis=0)
    rv = features["c_rv63"].to_numpy(dtype=float)
    raw = np.clip(np.where(np.isfinite(rv) & (rv > 1e-6), target_vol / rv, 0.0), 0.0, 1.0)
    index = features.index
    last = None
    posted = 0.0
    for i in range(n):
        ts = pd.Timestamp(index[i])
        is_first = i == 0 or (ts.year, ts.month) != (pd.Timestamp(index[i - 1]).year, pd.Timestamp(index[i - 1]).month)
        if is_first and np.isfinite(raw[i]):
            if last is None or abs(raw[i] - posted) >= band:
                posted = float(raw[i])
                last = posted
        weight_c = 0.0 if last is None else posted
        row = np.zeros(5)
        row[0] = 1.0 - weight_c
        row[2] = weight_c
        out[i] = row
    return out


def sell_in_may(features: pd.DataFrame) -> np.ndarray:
    """Straw man: hold C from November through April, otherwise G."""
    return _fill_fund(features["nov_apr"], "C")


RULES = {
    "sma_10m": ("10-month SMA", sma_10m),
    "dual_momentum": ("Dual momentum", dual_momentum),
    "curve_trend": ("Yield curve plus trend", curve_trend),
    "vol_target": ("Volatility target", vol_target),
    "sell_in_may": ("Sell in May", sell_in_may),
}


def all_rules(features: pd.DataFrame) -> dict[str, np.ndarray]:
    return {key: fn(features) for key, (_name, fn) in RULES.items()}
