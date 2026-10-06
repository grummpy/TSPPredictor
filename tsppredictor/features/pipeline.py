"""Build the daily feature frame from data available at the close of each TSP session.

Every rolling and expanding calculation looks backward. Macro series are merged
on a publication date, not on the observation date. NBER dates are not returned
as columns. Optional VIX and NY Fed files are used only when supplied.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from tsppredictor.calendar import is_scheduled_month_end, is_scheduled_pre_holiday
from tsppredictor.features.lags import (
    asof_values,
    cpi_available_date,
    next_weekday,
    shift_nyfed_dates,
    unemployment_available_date,
)

I_FUND_BREAK = pd.Timestamp("2024-10-30")
EVENT_CAP = 252


def _total_return(price: pd.Series, window: int) -> pd.Series:
    return price / price.shift(window) - 1.0


def _realized_vol(returns: pd.Series, window: int) -> pd.Series:
    return returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252)


def _drawdown(price: pd.Series) -> pd.Series:
    peak = price.cummax()
    return price / peak - 1.0


def _days_since_peak(price: pd.Series) -> pd.Series:
    values = price.to_numpy(dtype=float)
    n = len(values)
    out = np.zeros(n, dtype=float)
    peak_i = 0
    peak_v = values[0] if n else np.nan
    for i in range(n):
        if values[i] >= peak_v:
            peak_v = values[i]
            peak_i = i
        out[i] = i - peak_i
    return pd.Series(out, index=price.index)


def _above(price: pd.Series, window: int) -> pd.Series:
    avg = price.rolling(window, min_periods=window).mean()
    flag = (price > avg).astype(float)
    flag[avg.isna()] = np.nan
    return flag


def _expanding_pct(series: pd.Series, min_periods: int = 252) -> pd.Series:
    return series.expanding(min_periods=min_periods).rank(pct=True)


def _lagged_h15(h15: pd.DataFrame, decision_index: pd.DatetimeIndex) -> pd.DataFrame:
    frame = h15.dropna(subset=["date"]).sort_values("date").copy()
    obs = pd.to_datetime(frame["date"]).dt.date
    frame["available_on"] = [datetime.combine(next_weekday(d), datetime.min.time()) for d in obs]
    out = pd.DataFrame(index=decision_index)
    for col in ("effr", "ust_3m", "ust_2y", "ust_10y", "spread_10y_2y", "spread_10y_3m"):
        if col not in frame.columns:
            out[col] = np.nan
            continue
        values = pd.to_numeric(frame[col], errors="coerce")
        out[col] = asof_values(decision_index, pd.Series(frame["available_on"].to_numpy()), values).to_numpy()
    return out


def _monthly_release_feature(
    monthly: pd.DataFrame,
    month_col: str,
    value_col: str,
    decision_index: pd.DatetimeIndex,
    available_fn,
) -> pd.Series:
    frame = monthly.copy()
    frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
    frame = frame.dropna(subset=[value_col])
    months = frame[month_col].astype(str).str.slice(0, 7)
    available = [datetime.combine(available_fn(m), datetime.min.time()) for m in months]
    return asof_values(decision_index, pd.Series(available), frame[value_col].reset_index(drop=True))


def _cpi_transforms(bls: pd.DataFrame) -> pd.DataFrame:
    frame = bls.copy()
    frame["month"] = frame["month"].astype(str).str.slice(0, 7)
    frame["cpi_u_sa"] = pd.to_numeric(frame["cpi_u_sa"], errors="coerce")
    frame["unemployment_rate_sa"] = pd.to_numeric(frame["unemployment_rate_sa"], errors="coerce")
    frame = frame.sort_values("month")
    cpi = frame["cpi_u_sa"]
    frame["cpi_yoy"] = cpi / cpi.shift(12) - 1.0
    frame["cpi_chg_3m"] = cpi / cpi.shift(3) - 1.0
    # 12-month minimum includes the current month. That is known when the month is released.
    frame["unemp_gap"] = frame["unemployment_rate_sa"] - frame["unemployment_rate_sa"].rolling(12, min_periods=12).min()
    return frame


def _gpr_frame(gpr: pd.DataFrame, decision_index: pd.DatetimeIndex) -> pd.DataFrame:
    frame = gpr.sort_values("date").copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for col in ("GPRD", "GPRD_ACT", "GPRD_THREAT"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    # 1-day lag: a row dated d is usable on d+1.
    frame["available_on"] = frame["date"] + pd.Timedelta(days=1)
    trail_mean = frame["GPRD"].rolling(365, min_periods=60).mean()
    trail_std = frame["GPRD"].rolling(365, min_periods=60).std(ddof=1)
    frame["gpr_z"] = (frame["GPRD"] - trail_mean) / trail_std
    frame["gpr_act_minus_threat"] = frame["GPRD_ACT"] - frame["GPRD_THREAT"]
    out = pd.DataFrame(index=decision_index)
    for col in ("gpr_z", "gpr_act_minus_threat", "GPRD"):
        out[col] = asof_values(decision_index, frame["available_on"], frame[col].reset_index(drop=True)).to_numpy()
    out["gpr_spike"] = (out["gpr_z"] > 2).astype(float)
    out.loc[out["gpr_z"].isna(), "gpr_spike"] = np.nan
    return out


def _event_features(events: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    positions = np.arange(len(index))
    categories = {
        "war": "days_since_war",
        "financial_crisis": "days_since_crisis",
        "rate_shock": "days_since_rate",
        "pandemic": "days_since_pandemic",
    }
    reaction = pd.to_datetime(events["first_reaction_tsp_date"], errors="coerce")
    usable = events.loc[reaction.notna()].copy()
    usable["first_reaction_tsp_date"] = pd.to_datetime(usable["first_reaction_tsp_date"])
    # Keep only events whose reaction date is inside this (possibly truncated) sample.
    usable = usable[usable["first_reaction_tsp_date"] <= index.max()] if len(index) else usable.iloc[0:0]
    for cat, col in categories.items():
        dates = usable.loc[usable["category"] == cat, "first_reaction_tsp_date"].sort_values()
        days = np.full(len(index), np.nan)
        if len(dates):
            locs = index.searchsorted(pd.DatetimeIndex(dates), side="left")
            locs = locs[locs < len(index)]
            # searchsorted can land on a later session when the event date is not itself a row.
            # Use the first index on or after the reaction date, which is the reaction session
            # when the column was built that way, and the next session otherwise.
            cursor = 0
            for loc in locs:
                days[loc:] = np.arange(len(index) - loc)
                cursor = loc
            del cursor
            days = np.minimum(days, EVENT_CAP)
        out[col] = days
    for cat, col in (("war", "in_war_window"), ("financial_crisis", "in_crisis_window")):
        flag = np.zeros(len(index), dtype=float)
        dates = usable.loc[usable["category"] == cat, "first_reaction_tsp_date"]
        for stamp in dates:
            loc = int(index.searchsorted(pd.Timestamp(stamp), side="left"))
            if loc >= len(index):
                continue
            flag[loc : loc + 21] = 1.0
        out[col] = flag
    del positions
    return out


def _apply_vix(features: pd.DataFrame, vix: pd.DataFrame | None, rv20: pd.Series, rv63: pd.Series) -> None:
    index = features.index
    if vix is None or vix.empty:
        features["vol_level"] = rv20.to_numpy()
        features["vol_pct"] = _expanding_pct(rv20).to_numpy()
        features["vol_chg_5"] = rv20.diff(5).to_numpy()
        features["vol_minus_rv"] = 0.0
        return
    frame = vix.sort_values("date").copy()
    frame["date"] = pd.to_datetime(frame["date"])
    # Same-day close: availability date is the observation date.
    level = asof_values(index, frame["date"], frame["vix"].reset_index(drop=True))
    # If the as-of VIX is missing (before 1990, or a gap), fall back to realized vol.
    level = level.where(level.notna(), rv20)
    features["vol_level"] = level.to_numpy()
    features["vol_pct"] = _expanding_pct(pd.Series(level.to_numpy(), index=index)).to_numpy()
    features["vol_chg_5"] = pd.Series(level.to_numpy(), index=index).diff(5).to_numpy()
    features["vol_minus_rv"] = level.to_numpy() - 100.0 * rv63.to_numpy()


def _apply_nyfed(features: pd.DataFrame, nyfed: pd.DataFrame | None) -> None:
    if nyfed is None or nyfed.empty:
        return
    frame = nyfed.copy()
    date_col = None
    for candidate in ("date", "Date", "DATE"):
        if candidate in frame.columns:
            date_col = candidate
            break
    if date_col is None:
        # First column is the date in the NY Fed sheet.
        date_col = frame.columns[0]
    prob_col = None
    for candidate in frame.columns:
        lowered = str(candidate).lower()
        if "prob" in lowered or "rec" in lowered:
            prob_col = candidate
            break
    if prob_col is None:
        numeric = [c for c in frame.columns if c != date_col]
        if not numeric:
            return
        prob_col = numeric[-1]
    slim = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_col], errors="coerce"),
            "prob": pd.to_numeric(frame[prob_col], errors="coerce"),
        }
    ).dropna()
    shifted = shift_nyfed_dates(slim, "date")
    # Available at the shifted month-end (the information month), not 12 months later.
    values = asof_values(features.index, shifted["date"], shifted["prob"].reset_index(drop=True))
    features["nyfed_rec_prob"] = values.to_numpy()


def _headlines(features: pd.DataFrame, headlines: pd.DataFrame | None) -> None:
    if headlines is None or headlines.empty:
        return
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    frame = headlines.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["compound"] = frame["headline"].astype(str).map(lambda text: analyzer.polarity_scores(text)["compound"])
    daily = frame.groupby(frame["date"].dt.normalize()).agg(tone=("compound", "mean"), volume=("compound", "size"))
    daily = daily.sort_index()
    daily["available_on"] = daily.index + pd.Timedelta(days=1)
    tone_z_src = (daily["tone"] - daily["tone"].rolling(252, min_periods=60).mean()) / daily["tone"].rolling(
        252, min_periods=60
    ).std(ddof=1)
    vol_z_src = (daily["volume"] - daily["volume"].rolling(252, min_periods=60).mean()) / daily["volume"].rolling(
        252, min_periods=60
    ).std(ddof=1)
    features["news_tone_z"] = asof_values(
        features.index, pd.Series(daily["available_on"].to_numpy()), tone_z_src.reset_index(drop=True)
    ).to_numpy()
    features["news_volume_z"] = asof_values(
        features.index, pd.Series(daily["available_on"].to_numpy()), vol_z_src.reset_index(drop=True)
    ).to_numpy()


def build_features(
    prices: pd.DataFrame,
    h15: pd.DataFrame,
    bls: pd.DataFrame,
    gpr_daily: pd.DataFrame,
    events: pd.DataFrame,
    vix: pd.DataFrame | None = None,
    nyfed: pd.DataFrame | None = None,
    headlines: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Feature row t uses prices through t and macro releases available by t.

    ``prices`` columns are G, F, C, S, I. Pass a frame truncated at t to compute
    the same row the full sample produces at t.
    """
    px = prices.sort_index().copy()
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    index = pd.DatetimeIndex(px.index)
    rets = px.pct_change()
    features = pd.DataFrame(index=index)

    for fund in ("C", "S", "I", "F", "G"):
        price = px[fund]
        key = fund.lower()
        windows = (21, 63, 126, 252) if fund != "G" else (21, 63, 252)
        for window in windows:
            features[f"{key}_mom_{window}"] = _total_return(price, window)
        if fund != "G":
            features[f"{key}_mom_12_1"] = price.shift(21) / price.shift(252) - 1.0
            features[f"{key}_dd"] = _drawdown(price)

    features["c_above_sma50"] = _above(px["C"], 50)
    features["c_above_sma100"] = _above(px["C"], 100)
    features["c_above_sma200"] = _above(px["C"], 200)
    features["c_above_sma10m"] = _above(px["C"], 210)
    sma200 = px["C"].rolling(200, min_periods=200).mean()
    features["c_sma200_slope"] = sma200 / sma200.shift(20) - 1.0
    rv63 = _realized_vol(rets["C"], 63)
    rv20 = _realized_vol(rets["C"], 20)
    features["c_dist_vol"] = ((px["C"] / sma200) - 1.0) / rv63
    for fund in ("S", "I", "F"):
        features[f"{fund.lower()}_above_sma200"] = _above(px[fund], 200)
    features["c_rv20"] = rv20
    features["c_rv63"] = rv63
    features["c_vvol"] = rv20.rolling(63, min_periods=63).std(ddof=1)
    negative_sq = np.minimum(rets["C"].to_numpy(dtype=float), 0.0) ** 2
    features["c_downside"] = np.sqrt(pd.Series(negative_sq, index=index).rolling(63, min_periods=63).mean())
    features["c_vol_pct"] = _expanding_pct(rv63)
    features["c_days_since_peak"] = _days_since_peak(px["C"])
    dd = features["c_dd"]
    features["c_ulcer"] = np.sqrt((dd**2).rolling(63, min_periods=63).mean())

    mom = pd.DataFrame(
        {"c": features["c_mom_252"], "s": features["s_mom_252"], "i": features["i_mom_252"]},
        index=index,
    )
    ranks = mom.rank(axis=1, ascending=True, method="average")
    features["c_rs_rank"] = ranks["c"]
    features["s_rs_rank"] = ranks["s"]
    features["i_rs_rank"] = ranks["i"]
    finite_mom = mom.notna().any(axis=1)
    best = pd.Series(index=mom.index, dtype=object)
    if finite_mom.any():
        best.loc[finite_mom] = mom.loc[finite_mom].idxmax(axis=1)
    for fund in ("c", "s", "i"):
        beats_g = features[f"{fund}_mom_252"] > features["g_mom_252"]
        flag = ((best == fund) & beats_g).astype(float)
        flag[mom[fund].isna() | features["g_mom_252"].isna()] = np.nan
        features[f"{fund}_dual_mom"] = flag

    months = index.month
    features["month"] = months.astype(float)
    features["month_sin"] = np.sin(2 * math.pi * months / 12.0)
    features["month_cos"] = np.cos(2 * math.pi * months / 12.0)
    dates = [ts.date() for ts in index]
    # First three sessions of the month, counted inside the provided sample.
    # That count does not depend on later sessions, so it is truncation-safe.
    nth = pd.Series(dates, index=index)
    month_key = index.to_period("M")
    order = nth.groupby(month_key).cumcount()
    is_first3 = order < 3
    is_last = np.array([is_scheduled_month_end(d) for d in dates])
    features["turn_of_month"] = (is_first3.to_numpy() | is_last).astype(float)
    features["pre_holiday"] = np.array([is_scheduled_pre_holiday(d) for d in dates], dtype=float)
    features["nov_apr"] = np.isin(months, [11, 12, 1, 2, 3, 4]).astype(float)
    features["pres_cycle"] = (index.year % 4).astype(float)

    h15_lagged = _lagged_h15(h15, index)
    features["spread_10y_3m"] = h15_lagged["spread_10y_3m"]
    features["spread_10y_2y"] = h15_lagged["spread_10y_2y"]
    features["spread_10y_3m_chg_63"] = features["spread_10y_3m"] - features["spread_10y_3m"].shift(63)
    features["spread_10y_2y_chg_63"] = features["spread_10y_2y"] - features["spread_10y_2y"].shift(63)
    inverted = features["spread_10y_3m"] < 0
    run = []
    count = 0.0
    for value in inverted.to_numpy():
        if value is True or value == 1:
            count += 1.0
        else:
            count = 0.0
        run.append(count / 21.0)
    features["curve_inverted"] = inverted.astype(float)
    features.loc[features["spread_10y_3m"].isna(), "curve_inverted"] = np.nan
    features["months_inverted"] = run
    features.loc[features["spread_10y_3m"].isna(), "months_inverted"] = np.nan
    features["tbill_minus_effr"] = h15_lagged["ust_3m"] - h15_lagged["effr"]

    cpi = _cpi_transforms(bls)
    features["cpi_yoy"] = _monthly_release_feature(cpi, "month", "cpi_yoy", index, cpi_available_date).to_numpy()
    features["cpi_chg_3m"] = _monthly_release_feature(cpi, "month", "cpi_chg_3m", index, cpi_available_date).to_numpy()
    features["unemp_gap"] = _monthly_release_feature(
        cpi, "month", "unemp_gap", index, unemployment_available_date
    ).to_numpy()
    g_ann_pct = features["g_mom_21"] * (252.0 / 21.0) * 100.0
    features["g_minus_tbill"] = g_ann_pct.to_numpy() - h15_lagged["ust_3m"].to_numpy()

    _apply_vix(features, vix, rv20, rv63)
    gpr = _gpr_frame(gpr_daily, index)
    features["gpr_z"] = gpr["gpr_z"]
    features["gpr_act_minus_threat"] = gpr["gpr_act_minus_threat"]
    features["gpr_spike"] = gpr["gpr_spike"]
    event_cols = _event_features(events, index)
    for col in event_cols.columns:
        features[col] = event_cols[col]
    features["i_structural_break"] = (index >= I_FUND_BREAK).astype(float)
    _apply_nyfed(features, nyfed)
    _headlines(features, headlines)
    # NBER is intentionally absent. Evaluation code builds recession labels separately.
    banned = [col for col in features.columns if "nber" in col.lower()]
    if banned:
        raise RuntimeError(f"NBER columns leaked into features: {banned}")
    return features


def nber_evaluation_flag(nber: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Recession indicator for evaluation only. Do not pass this to a model."""
    peaks = pd.to_datetime(nber["peak"], errors="coerce")
    troughs = pd.to_datetime(nber["trough"], errors="coerce")
    flag = np.zeros(len(index), dtype=int)
    dates = index.to_numpy()
    for peak, trough in zip(peaks, troughs, strict=False):
        if pd.isna(peak) or pd.isna(trough):
            continue
        flag[(dates >= np.datetime64(peak)) & (dates <= np.datetime64(trough))] = 1
    return pd.Series(flag, index=index, name="nber_recession_evaluation_only")
