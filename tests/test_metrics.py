"""Tests 18–20: hand-computed metrics, buy-and-hold, and always-G."""

import numpy as np
import pandas as pd
import pytest

from tsppredictor.backtest.honesty import verdict
from tsppredictor.backtest.metrics import cagr, max_drawdown, one_way_turnover
from tsppredictor.backtest.walkforward import constant_fund_path, one_hot, simulate_targets


@pytest.mark.parametrize("dsr", [None, 0.94, np.nan])
def test_positive_interval_without_sufficient_dsr_is_inconclusive(dsr):
    assert verdict(0.02, [0.01, 0.03], dsr) == "Inconclusive"


def test_verdict_dsr_threshold_and_underperformance():
    assert verdict(0.02, [0.01, 0.03], 0.95) == "Beat"
    assert verdict(-0.02, [-0.03, -0.01], None) == "Underperformed"


def test_18_toy_series_matches_hand_calculation():
    frame = pd.read_csv("tests/fixtures/toy_prices.csv", parse_dates=["Date"]).set_index("Date")
    wealth = frame["price"].to_numpy(dtype=float) / 100.0
    dates = pd.DatetimeIndex(frame.index)
    # Hand calculation: end price 99, span 2020-01-09 minus 2020-01-02 = 7 days.
    # (0.99) ** (365.25 / 7) - 1 = -0.4080967977694844
    # Trough 90 over peak 115 = -0.21739130434782605
    assert dates[-1] - dates[0] == pd.Timedelta(days=7)
    assert cagr(wealth, dates) == -0.4080967977694844
    drawdown, peak_i, trough_i = max_drawdown(wealth)
    assert drawdown == -0.21739130434782605
    assert peak_i == 3 and trough_i == 4
    weights = np.vstack([one_hot("C")] * 3 + [one_hot("G")] * 3)
    assert one_way_turnover(weights) == 1.0


def test_19_buy_and_hold_c_matches_the_price_path(prices):
    path = constant_fund_path(prices, "C")
    days = (prices.index[-1] - prices.index[0]).days
    expected = (prices["C"].iloc[-1] / prices["C"].iloc[0]) ** (365.25 / days) - 1.0
    assert path["n_transfers"] == 0
    assert cagr(path["wealth"], prices.index) == expected
    targets = np.repeat(one_hot("C").reshape(1, -1), len(prices), axis=0)
    sim = simulate_targets(prices.index, targets, lag=1, min_hold=21, enforce_ift=True, initial=one_hot("C"))
    assert sim["n_transfers"] == 0
    rets = np.zeros(len(prices))
    px = prices["C"].to_numpy(dtype=float)
    rets[1:] = px[1:] / px[:-1] - 1.0
    wealth = np.cumprod(1.0 + rets)
    assert np.isclose(cagr(wealth, prices.index), expected)


def test_20_always_g_has_no_drawdown_and_no_transfers(prices):
    path = constant_fund_path(prices, "G")
    drawdown, _peak, _trough = max_drawdown(path["wealth"])
    assert drawdown == 0.0
    assert path["n_transfers"] == 0
    targets = np.repeat(one_hot("G").reshape(1, -1), len(prices), axis=0)
    sim = simulate_targets(prices.index, targets, lag=1, min_hold=21, enforce_ift=True, initial=one_hot("G"))
    assert sim["n_transfers"] == 0
