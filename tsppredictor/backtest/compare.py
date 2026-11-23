"""Price-drift versus constant-target comparisons for the transparent rules."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from tsppredictor.backtest.metrics import cagr, max_drawdown
from tsppredictor.backtest.walkforward import one_hot, portfolio_returns, simulate_targets
from tsppredictor.models.rules import RULES


def _run(dates, prices, targets, lag, use_prices: bool) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        sim = simulate_targets(dates, targets, lag=lag, enforce_ift=True, initial=one_hot("G"),
                               prices=prices if use_prices else None)
    returns = portfolio_returns(prices, sim["weights"])
    wealth = np.cumprod(1.0 + np.nan_to_num(returns))
    return {"sim": sim, "wealth": wealth}


def drift_vs_constant(strategy: str, features: pd.DataFrame, prices: pd.DataFrame, *, lag: int = 1,
                      periods: int = 12) -> dict:
    """Compare a rule's result under the price-drift model and the legacy constant-target model."""
    if strategy not in RULES:
        raise KeyError(f"unknown strategy {strategy!r}; choose from {sorted(RULES)}")
    name, fn = RULES[strategy]
    common = features.index.intersection(prices.index)
    feats = features.loc[common]
    px = prices.loc[common, ["G", "F", "C", "S", "I"]].ffill()
    valid = px.notna().all(axis=1).to_numpy()
    first = int(np.argmax(valid)) if valid.any() else 0
    feats, px = feats.iloc[first:], px.iloc[first:]
    targets = fn(feats)
    dates = pd.DatetimeIndex(px.index)
    drift = _run(dates, px, targets, lag, True)
    constant = _run(dates, px, targets, lag, False)

    def summary(run):
        w = run["wealth"]
        return {"final_wealth": float(w[-1]), "cagr": float(cagr(w, dates)), "max_drawdown": float(max_drawdown(w)[0]),
                "transfers": int(run["sim"]["n_transfers"])}

    a, b = summary(drift), summary(constant)
    return {"strategy": strategy, "name": name, "lag": lag, "periods_per_year": periods,
            "from": str(dates[0].date()), "to": str(dates[-1].date()),
            "price_drift": a, "constant_target": b,
            "cagr_difference": a["cagr"] - b["cagr"],
            "note": "Price drift keeps fixed shares between transfers (the real account); "
                    "constant target re-weights every session (legacy model).",
            "_drift_sim": drift["sim"], "_dates": dates}
