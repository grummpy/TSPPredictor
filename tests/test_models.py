"""Tests 21–24: calibration, regimes, and the stale-price flag."""

import numpy as np
import pandas as pd

from tsppredictor.backtest.honesty import brier_skill_binary, reliability, verdict
from tsppredictor.backtest.metrics import cagr
from tsppredictor.models.diagnostics import toy_buy_i_after_c_up
from tsppredictor.models.ml import walk_forward_models
from tsppredictor.models.regimes import fit_gmm_states, relabel_by_volatility


def _walk(seed: int, planted: bool):
    rng = np.random.default_rng(seed)
    n = 1600
    dates = pd.bdate_range("2008-01-02", periods=n)
    signal = rng.normal(size=n)
    noise = rng.normal(size=n)
    if planted:
        labels = np.where(signal > 0.0, "C", "G").astype(object)
    else:
        labels = rng.choice(np.array(["C", "G"], dtype=object), size=n)
    frame = pd.DataFrame({"signal": signal, "noise": noise}, index=dates)
    return walk_forward_models(
        frame,
        labels,
        ["signal", "noise"],
        h=5,
        lag=1,
        cadence="daily",
        fit_hgb=False,
        min_rows=80,
        min_span_days=400,
    ), labels


def test_21_planted_signal_and_noise_verdict():
    planted, labels = _walk(0, True)
    proba = planted["logistic"]
    mask = np.isfinite(proba).all(axis=1)
    # Class order in _align_proba is G, F, C, S, I. C is column 2.
    p_c = proba[mask, 2]
    outcome = (labels[mask] == "C").astype(float)
    skill = brier_skill_binary(p_c, outcome)["brier_skill"]
    assert skill is not None and skill > 0

    noise, labels_n = _walk(1, False)
    proba_n = noise["logistic"]
    mask_n = np.isfinite(proba_n).all(axis=1)
    p_n = proba_n[mask_n, 2]
    outcome_n = (labels_n[mask_n] == "C").astype(float)
    skill_n = brier_skill_binary(p_n, outcome_n)["brier_skill"]
    assert skill_n is not None and abs(skill_n) <= 0.02

    dates = pd.bdate_range("2010-01-04", periods=400)
    returns = np.zeros(400)
    returns[1:] = 0.0004
    wealth = np.cumprod(1.0 + returns)
    assert cagr(wealth, dates) == cagr(wealth, dates)
    # Identical strategy and baseline returns have excess CAGR of exactly 0.
    from tsppredictor.backtest.honesty import block_bootstrap_excess_cagr

    boot = block_bootstrap_excess_cagr(returns, returns, dates, block=21, n_boot=50, seed=0)
    assert boot["excess_cagr"] == 0.0
    assert verdict(boot["excess_cagr"], boot["ci90"], dsr=0.5) != "Beat"


def test_22_probabilities_and_reliability_counts():
    result, labels = _walk(2, True)
    proba = result["logistic"]
    mask = np.isfinite(proba).all(axis=1)
    assert np.nanmax(proba) <= 1.0 + 1e-8
    assert np.nanmin(proba[mask]) >= -1e-8
    chosen = proba[mask].max(axis=1)
    y = labels[mask]
    pred = np.where(proba[mask, 2] >= proba[mask, 0], "C", "G")
    right = (pred == y).astype(float)
    table = reliability(chosen, right)
    assert table["count_sum"] == table["n"]
    assert table["n"] == int(mask.sum())


def test_23_regime_relabel_is_stable():
    rng = np.random.default_rng(4)
    raw = rng.integers(0, 3, size=300)
    vol = np.where(raw == 0, 0.1, np.where(raw == 1, 0.2, 0.4)) + rng.normal(0, 0.001, size=300)
    ordered = relabel_by_volatility(raw, vol)
    again = relabel_by_volatility(raw, vol)
    assert np.array_equal(ordered, again)
    means = [vol[ordered == state].mean() for state in sorted(set(ordered.tolist()))]
    assert means == sorted(means)
    features = rng.normal(size=(240, 4))
    vol2 = np.abs(features[:, 0])
    first = fit_gmm_states(features, vol2, n_states=3, seed=0)
    second = fit_gmm_states(features, vol2, n_states=3, seed=0)
    assert np.array_equal(first, second)


def test_24_stale_price_toy_is_flagged():
    report = toy_buy_i_after_c_up()
    assert report["suspect"] is True
    assert report["asset"] == "I"
    assert report["hold_sessions"] == 1
