"""Tests 18–20: hand-computed metrics, buy-and-hold, and always-G."""

import numpy as np
import pandas as pd
import pytest

from tsppredictor.backtest.honesty import verdict
from tsppredictor.backtest.metrics import cagr, max_drawdown, one_way_turnover, summarize
from tsppredictor.backtest.walkforward import constant_fund_path, one_hot, simulate_targets, static_mix_wealth


@pytest.mark.parametrize("dsr", [None, 0.94, np.nan])
def test_positive_interval_without_sufficient_dsr_is_inconclusive(dsr):
    assert verdict(0.02, [0.01, 0.03], dsr) == "Inconclusive"


def test_verdict_dsr_threshold_and_underperformance():
    assert verdict(0.02, [0.01, 0.03], 0.95) == "Beat"
    assert verdict(-0.02, [-0.03, -0.01], None) == "Underperformed"


@pytest.mark.parametrize("periods", [12, 252])
def test_summary_uses_requested_annualization(periods):
    dates = pd.date_range("2020-01-31", periods=25, freq="ME")
    rets = np.array([0.0] + [0.02, -0.01] * 12)
    wealth = np.cumprod(1.0 + rets)
    weights = np.vstack([one_hot("C")] * len(dates))
    stats = summarize(wealth, dates, weights, np.zeros(len(dates)), periods=periods)
    assert stats["vol"] == pytest.approx(np.std(rets[1:], ddof=1) * np.sqrt(periods))
    assert stats["sharpe_vs_g"] == pytest.approx(
        np.mean(rets[1:]) / np.std(rets[1:], ddof=1) * np.sqrt(periods)
    )
    assert stats["sortino_vs_g"] == pytest.approx(np.mean(rets[1:]) / 0.01 * np.sqrt(periods))
    expected_worst = (
        np.min(wealth[periods:] / wealth[:-periods] - 1.0)
        if len(wealth) > periods
        else wealth[-1] / wealth[0] - 1.0
    )
    assert stats["worst_12m"] == pytest.approx(expected_worst)


def test_monthly_annualization_matches_a_hand_calculated_12_period_fixture():
    dates = pd.date_range("2020-01-31", periods=13, freq="ME")
    monthly = np.array([0.01, 0.02] * 6)
    rets = np.r_[0.0, monthly]
    wealth = np.cumprod(1.0 + rets)
    stats = summarize(wealth, dates, np.vstack([one_hot("C")] * 13), np.zeros(13), periods=12)
    monthly_sd = np.std(monthly, ddof=1)
    assert stats["vol"] == pytest.approx(monthly_sd * np.sqrt(12))
    # Hand calculation: mean 1.5% divided by the sample standard deviation,
    # then scaled by sqrt(12) rather than daily sqrt(252).
    assert stats["sharpe_vs_g"] == pytest.approx(monthly.mean() / monthly_sd * np.sqrt(12))
    assert stats["worst_12m"] == pytest.approx(wealth[-1] / wealth[0] - 1.0)


def test_build_metrics_pass_monthly_periods():
    from tsppredictor.build import _metrics_on

    dates = pd.date_range("2020-01-31", periods=25, freq="ME")
    wealth = np.cumprod([1.0] + [1.02, 0.99] * 12)
    weights = np.vstack([one_hot("C")] * len(dates))
    prices = pd.DataFrame({"G": np.ones(len(dates))}, index=dates)
    expected = summarize(wealth, dates, weights, np.zeros(len(dates)), periods=12)
    actual = _metrics_on(wealth, dates, weights, prices, [], periods=12)
    for key in ("vol", "sharpe_vs_g", "sortino_vs_g", "worst_12m"):
        assert actual[key] == round(expected[key], 6)


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


def test_fixed_weight_baseline_does_not_implicitly_rebalance_daily():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    prices = pd.DataFrame(
        {"G": [100, 100, 100], "F": [100, 100, 100], "C": [100, 120, 144], "S": [100, 100, 100], "I": [100, 100, 100]},
        index=dates,
        dtype=float,
    )
    wealth, weights = static_mix_wealth(prices, np.array([0.5, 0, 0.5, 0, 0]))
    assert wealth[-1] == pytest.approx(1.22)
    assert weights[1, 2] == pytest.approx(120 / 220)
    assert weights[2, 2] == pytest.approx(144 / 244)


def test_20_always_g_has_no_drawdown_and_no_transfers(prices):
    path = constant_fund_path(prices, "G")
    drawdown, _peak, _trough = max_drawdown(path["wealth"])
    assert drawdown == 0.0
    assert path["n_transfers"] == 0
    targets = np.repeat(one_hot("G").reshape(1, -1), len(prices), axis=0)
    sim = simulate_targets(prices.index, targets, lag=1, min_hold=21, enforce_ift=True, initial=one_hot("G"))
    assert sim["n_transfers"] == 0
