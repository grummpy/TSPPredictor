"""Tests 8–12: snapshot counts and hand-checked returns."""

from dataclasses import replace

import pandas as pd
import pytest

from tsppredictor.data.snapshot import check_integrity


@pytest.mark.parametrize("gap", [0.0, 0.02])
def test_reconciliation_validates_future_complete_month(snap, gap):
    dates = pd.to_datetime(["2026-09-30", "2026-10-30", "2026-11-02"])
    daily = pd.DataFrame(
        {fund: [100.0, 101.0, 102.0] for fund in ("G", "F", "C", "S", "I")}, index=dates
    )
    monthly = pd.DataFrame(
        {"month": ["2026-10"], **{f"{fund} Fund": [1.0] for fund in ("G", "F", "C", "S", "I")}}
    )
    monthly.loc[0, "C Fund"] += gap
    refreshed = replace(snap, daily=daily, monthly=monthly)
    report = check_integrity(refreshed, as_of_today=dates[-1])
    assert report.stats["recon_months"] == 1
    assert report.ok == (gap == 0.0)
    if gap:
        assert any("C daily-to-monthly gap" in error for error in report.errors)


def _pct(prices, fund, start, end):
    return float(prices.loc[end, fund] / prices.loc[start, fund] - 1.0) * 100.0


def test_08_daily_shape_and_g_never_falls(prices):
    assert len(prices) == 5830
    assert prices.index.is_unique
    assert prices.index.min() == pd.Timestamp("2003-05-31")
    assert prices.index.max() == pd.Timestamp("2026-10-05")
    for fund in ("G", "F", "C", "S", "I"):
        assert prices[fund].notna().all()
        assert (prices[fund] > 0).all()
    assert (prices["G"].diff().dropna() < -1e-9).sum() == 0


def test_09_daily_matches_monthly(snap, prices):
    from tsppredictor.data.snapshot import month_end_return_pct

    official = snap.monthly.set_index("month")
    names = {"G": "G Fund", "F": "F Fund", "C": "C Fund", "S": "S Fund", "I": "I Fund"}
    worst = 0.0
    n_cmp = None
    for fund, column in names.items():
        calc = month_end_return_pct(prices, fund)
        joined = pd.DataFrame({"calc": calc, "off": pd.to_numeric(official[column], errors="coerce")})
        joined = joined.loc[(joined.index >= "2003-07") & (joined.index <= "2026-09")].dropna()
        n_cmp = len(joined)
        gap = (joined["calc"] - joined["off"]).abs().max()
        worst = max(worst, float(gap))
    assert n_cmp == 279
    assert worst <= 0.01


def test_10_monthly_and_partial_2026(snap):
    monthly = snap.monthly
    assert len(monthly) == 474
    assert str(monthly["month"].iloc[0])[:7] == "1987-04"
    assert str(monthly["month"].iloc[-1])[:7] == "2026-09"
    annual = snap.annual
    row = annual.loc[annual["year"].astype(int) == 2026].iloc[0]
    assert str(row["is_partial_year"]) in {"True", "true", "1"} or bool(row["is_partial_year"]) is True


def test_11_hand_checked_returns(prices):
    checks = {
        "C": -33.83,
        "S": -41.41,
        "I": -31.95,
        "F": -0.99,
        "G": 0.12,
    }
    for fund, expected in checks.items():
        change = _pct(prices, fund, "2020-02-19", "2020-03-23")
        assert abs(change - expected) <= 0.01
    c = prices["C"]
    peak = c.cummax()
    dd = c / peak - 1.0
    trough = dd.idxmin()
    assert abs(float(dd.min()) * 100 - (-55.22)) <= 0.01
    assert trough == pd.Timestamp("2009-03-09")
    assert c.loc[:trough].idxmax() == pd.Timestamp("2007-10-09")
    assert abs(_pct(prices, "C", "2021-12-31", "2022-12-30") - (-18.13)) <= 0.01
    assert abs(_pct(prices, "F", "2021-12-31", "2022-12-30") - (-12.83)) <= 0.01
    days = (prices.index[-1] - prices.index[0]).days
    for fund, expected in (("C", 11.44), ("G", 3.07)):
        cagr = (prices[fund].iloc[-1] / prices[fund].iloc[0]) ** (365.25 / days) - 1.0
        assert abs(cagr * 100 - expected) <= 0.01


def test_12_events(snap):
    events = snap.events
    assert len(events) == 56
    assert events["event_id"].is_unique
    assert events["source_url"].astype(str).str.startswith("https://").all()
    parsed = pd.to_datetime(events["event_date"], errors="coerce")
    assert parsed.notna().all()
    by_id = events.set_index("event_id")
    assert str(by_id.loc["E2026_IRAN_WAR", "first_reaction_tsp_date"])[:10] == "2026-03-02"
    assert str(by_id.loc["E2011_DEBT_CEILING", "first_reaction_tsp_date"])[:10] == "2011-08-08"
    assert str(by_id.loc["E2023_OCT7", "first_reaction_tsp_date"])[:10] == "2023-10-10"
