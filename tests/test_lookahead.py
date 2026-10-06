"""Tests 13–17: truncation, poisoned future, publication lags, execution lag, purge."""

from datetime import date

import numpy as np
import pandas as pd

from tsppredictor.backtest.walkforward import label_price_end, last_train_index, one_hot, simulate_targets
from tsppredictor.features.lags import cpi_available_date, shift_nyfed_dates
from tsppredictor.features.pipeline import build_features, nber_evaluation_flag
from tsppredictor.features.spec import model_feature_names


def _features(snap, prices):
    return build_features(prices, snap.h15, snap.bls, snap.gpr_daily, snap.events)


def test_13_truncation_invariance(snap, prices):
    full = _features(snap, prices)
    rng = np.random.default_rng(0)
    candidates = np.arange(900, len(prices) - 1)
    picks = rng.choice(candidates, size=20, replace=False)
    for loc in picks:
        loc = int(loc)
        truncated = _features(snap, prices.iloc[: loc + 1])
        stamp = prices.index[loc]
        left = full.loc[stamp]
        right = truncated.loc[stamp]
        both = left.index.intersection(right.index)
        for column in both:
            a = left[column]
            b = right[column]
            if pd.isna(a) and pd.isna(b):
                continue
            assert np.isclose(float(a), float(b), rtol=1e-8, atol=1e-8, equal_nan=True), column


def test_14_poisoned_future_does_not_change_the_past(snap, prices):
    full = _features(snap, prices)
    loc = 4000
    stamp = prices.index[loc]
    poisoned = prices.copy()
    rng = np.random.default_rng(1)
    noise = rng.uniform(5, 80, size=(len(prices) - loc - 1, poisoned.shape[1]))
    poisoned.iloc[loc + 1 :] = noise
    alt = _features(snap, poisoned)
    left = full.loc[:stamp]
    right = alt.loc[:stamp]
    for column in left.columns:
        a = left[column].to_numpy(dtype=float)
        b = right[column].to_numpy(dtype=float)
        assert np.allclose(a, b, rtol=1e-8, atol=1e-8, equal_nan=True), column


def test_15_publication_lags_and_nber(snap, prices):
    assert cpi_available_date("2024-10") == date(2024, 11, 15)
    dates = pd.bdate_range("2023-01-02", "2024-12-31")
    tiny = pd.DataFrame(
        {fund: np.linspace(10, 20, len(dates)) for fund in ("G", "F", "C", "S", "I")},
        index=dates,
    )
    months = pd.period_range("2022-01", "2024-10", freq="M").astype(str)
    cpi = np.linspace(100, 110, len(months))
    cpi[-1] = 400.0
    bls = pd.DataFrame({"month": months, "cpi_u_sa": cpi, "unemployment_rate_sa": np.full(len(months), 4.0)})
    h15 = snap.h15
    gpr = snap.gpr_daily
    events = snap.events.iloc[0:0]
    built = build_features(tiny, h15, bls, gpr, events)
    before = built.loc[pd.Timestamp("2024-11-14"), "cpi_yoy"]
    after = built.loc[pd.Timestamp("2024-11-15"), "cpi_yoy"]
    assert pd.isna(before) or float(before) < 0.5
    assert float(after) > 1.0

    ny = pd.DataFrame({"date": ["2024-06-30"], "recession_probability": [0.42]})
    shifted = shift_nyfed_dates(ny, "date")
    assert pd.Timestamp(shifted["date"].iloc[0]) == pd.Timestamp("2023-06-30")
    seen = build_features(tiny, h15, bls, gpr, events, nyfed=ny)
    assert "nyfed_rec_prob" in seen.columns
    assert pd.isna(seen.loc[pd.Timestamp("2023-05-31"), "nyfed_rec_prob"])
    assert np.isclose(float(seen.loc[pd.Timestamp("2023-07-03"), "nyfed_rec_prob"]), 0.42)

    assert not any("nber" in name.lower() for name in built.columns)
    assert not any("nber" in name.lower() for name in model_feature_names())
    flag = nber_evaluation_flag(snap.nber, built.index)
    assert flag.name == "nber_recession_evaluation_only"
    assert "nber" not in "".join(built.columns).lower()


def test_16_execution_lag():
    dates = pd.bdate_range("2024-01-02", periods=6)
    targets = np.vstack([one_hot("G"), one_hot("G"), one_hot("C"), one_hot("C"), one_hot("C"), one_hot("C")])
    lag1 = simulate_targets(dates, targets, lag=1, min_hold=0, enforce_ift=True, initial=one_hot("G"))
    lag2 = simulate_targets(dates, targets, lag=2, min_hold=0, enforce_ift=True, initial=one_hot("G"))
    assert np.argmax(lag1["weights"][3]) == 0
    assert np.argmax(lag1["weights"][4]) == 2
    assert np.argmax(lag2["weights"][4]) == 0
    assert np.argmax(lag2["weights"][5]) == 2


def test_17_purge_and_embargo():
    for test_start in (400, 800, 1200):
        for h in (21, 63, 1):
            for lag in (1, 2):
                last = last_train_index(test_start, h, lag)
                assert label_price_end(last, h, lag) < test_start
                assert test_start - last > (h + lag)


def test_lagged_reversal_accounts_for_pending_transfer():
    dates = pd.bdate_range("2024-01-02", periods=6)
    targets = np.vstack([one_hot("C")] + [one_hot("G")] * 5)
    sim = simulate_targets(dates, targets, lag=2, initial=one_hot("G"))
    assert sim["post_dates"] == [dates[2], dates[3]]
    assert sim["month_used"] == {"2024-01": 2}
    assert np.argmax(sim["weights"][3]) == 2
    assert np.argmax(sim["weights"][4]) == 0


def test_repeated_pending_target_does_not_consume_transfers():
    dates = pd.bdate_range("2024-01-02", periods=6)
    targets = np.vstack([one_hot("C")] * 6)
    sim = simulate_targets(dates, targets, lag=2, initial=one_hot("G"))
    assert sim["post_dates"] == [dates[2]]
    assert sim["month_used"] == {"2024-01": 1}


def test_g_only_limit_uses_pending_allocation():
    dates = pd.bdate_range("2024-01-02", periods=7)
    initial = np.array([0.0, 0.0, 0.5, 0.5, 0.0])
    targets = np.full((7, 5), np.nan)
    targets[0] = one_hot("C")
    targets[1] = one_hot("S")
    targets[2] = [0.5, 0.0, 0.0, 0.5, 0.0]
    sim = simulate_targets(dates, targets, lag=2, initial=initial)
    assert sim["post_dates"] == [dates[2], dates[3], dates[4]]
    assert sim["month_used"] == {"2024-01": 2}
    assert np.allclose(sim["weights"][5], targets[2])
