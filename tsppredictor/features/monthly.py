"""Monthly-cadence features from TSP's official monthly returns.

Window names match the daily frame so the same rules can run. On this cadence
``c_mom_252`` is the 12-month return, ``c_mom_63`` is 3 months, ``c_mom_21`` is
1 month, and ``c_above_sma200`` uses the 10-month average. Macro series are
lagged a full month, which is longer than the daily one-weekday lag.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tsppredictor.calendar import is_scheduled_pre_holiday

CORE = {
    "G Fund": "G",
    "F Fund": "F",
    "C Fund": "C",
    "S Fund": "S",
    "I Fund": "I",
}


def monthly_price_index(monthly: pd.DataFrame) -> pd.DataFrame:
    frame = monthly.copy()
    frame["month"] = frame["month"].astype(str).str.slice(0, 7)
    frame = frame.drop_duplicates("month").sort_values("month")
    index = pd.PeriodIndex(frame["month"], freq="M").to_timestamp("M")
    out = pd.DataFrame(index=index)
    out.index.name = "Date"
    for src, dest in CORE.items():
        rets = pd.to_numeric(frame[src], errors="coerce").to_numpy() / 100.0
        level = np.full(len(rets), np.nan)
        started = False
        acc = 1.0
        for i, ret in enumerate(rets):
            if not np.isfinite(ret):
                if started:
                    level[i] = acc
                continue
            acc *= 1.0 + ret
            level[i] = acc
            started = True
        out[dest] = level
    return out


def build_monthly_features(monthly: pd.DataFrame, h15: pd.DataFrame, bls: pd.DataFrame, gpr_m: pd.DataFrame) -> pd.DataFrame:
    px = monthly_price_index(monthly)
    index = pd.DatetimeIndex(px.index)
    features = pd.DataFrame(index=index)
    for fund in ("C", "S", "I", "F", "G"):
        price = px[fund]
        key = fund.lower()
        features[f"{key}_mom_21"] = price / price.shift(1) - 1.0
        features[f"{key}_mom_63"] = price / price.shift(3) - 1.0
        features[f"{key}_mom_126"] = price / price.shift(6) - 1.0
        features[f"{key}_mom_252"] = price / price.shift(12) - 1.0
        if fund != "G":
            features[f"{key}_mom_12_1"] = price.shift(1) / price.shift(12) - 1.0
            features[f"{key}_dd"] = price / price.cummax() - 1.0
    sma10 = px["C"].rolling(10, min_periods=10).mean()
    above = (px["C"] > sma10).astype(float)
    above[sma10.isna()] = np.nan
    features["c_above_sma10m"] = above
    features["c_above_sma50"] = above
    features["c_above_sma100"] = above
    features["c_above_sma200"] = above
    features["c_sma200_slope"] = sma10 / sma10.shift(1) - 1.0
    rets = px["C"].pct_change()
    rv = rets.rolling(12, min_periods=12).std(ddof=1) * math.sqrt(12)
    features["c_rv20"] = rv
    features["c_rv63"] = rv
    features["c_dist_vol"] = ((px["C"] / sma10) - 1.0) / rv
    features["c_vvol"] = rv.rolling(12, min_periods=12).std(ddof=1)
    neg = np.minimum(rets.to_numpy(dtype=float), 0.0) ** 2
    features["c_downside"] = np.sqrt(pd.Series(neg, index=index).rolling(12, min_periods=12).mean())
    features["c_vol_pct"] = rv.expanding(min_periods=36).rank(pct=True)
    features["c_ulcer"] = np.sqrt((features["c_dd"] ** 2).rolling(12, min_periods=12).mean())
    features["c_days_since_peak"] = 0.0
    for fund in ("S", "I", "F"):
        sma = px[fund].rolling(10, min_periods=10).mean()
        flag = (px[fund] > sma).astype(float)
        flag[sma.isna()] = np.nan
        features[f"{fund.lower()}_above_sma200"] = flag
    mom = features[["c_mom_252", "s_mom_252", "i_mom_252"]]
    ranks = mom.rank(axis=1, ascending=True, method="average")
    features["c_rs_rank"] = ranks["c_mom_252"]
    features["s_rs_rank"] = ranks["s_mom_252"]
    features["i_rs_rank"] = ranks["i_mom_252"]
    finite_mom = mom.notna().any(axis=1)
    best = pd.Series(index=mom.index, dtype=object)
    if finite_mom.any():
        best.loc[finite_mom] = mom.loc[finite_mom].idxmax(axis=1)
    for fund, col in (("c", "c_mom_252"), ("s", "s_mom_252"), ("i", "i_mom_252")):
        beats = features[col] > features["g_mom_252"]
        flag = ((best == col) & beats).astype(float)
        flag[features[col].isna()] = np.nan
        features[f"{fund}_dual_mom"] = flag
    months = index.month
    features["month"] = months.astype(float)
    features["month_sin"] = np.sin(2 * math.pi * months / 12)
    features["month_cos"] = np.cos(2 * math.pi * months / 12)
    features["turn_of_month"] = 1.0  # a month-end decision is the turn of the month
    features["pre_holiday"] = [1.0 if is_scheduled_pre_holiday(ts.date()) else 0.0 for ts in index]
    features["nov_apr"] = np.isin(months, [11, 12, 1, 2, 3, 4]).astype(float)
    features["pres_cycle"] = (index.year % 4).astype(float)

    # Lag macro by one month: the month-end print is not used in that same month.
    h15m = h15.copy()
    h15m["date"] = pd.to_datetime(h15m["date"])
    h15m = h15m.set_index("date").sort_index()
    month_end = h15m.resample("ME").last().shift(1)
    month_end.index = month_end.index.to_period("M").to_timestamp("M")
    aligned = month_end.reindex(index)
    features["spread_10y_3m"] = aligned["spread_10y_3m"]
    features["spread_10y_2y"] = aligned["spread_10y_2y"]
    features["spread_10y_3m_chg_63"] = features["spread_10y_3m"] - features["spread_10y_3m"].shift(3)
    features["spread_10y_2y_chg_63"] = features["spread_10y_2y"] - features["spread_10y_2y"].shift(3)
    inverted = features["spread_10y_3m"] < 0
    count = 0.0
    run = []
    for value in inverted.to_numpy():
        if value is True or value == 1:
            count += 1
        else:
            count = 0
        run.append(count)
    features["curve_inverted"] = inverted.astype(float)
    features.loc[features["spread_10y_3m"].isna(), "curve_inverted"] = np.nan
    features["months_inverted"] = run
    features.loc[features["spread_10y_3m"].isna(), "months_inverted"] = np.nan
    features["tbill_minus_effr"] = aligned["ust_3m"] - aligned["effr"]

    bls = bls.copy()
    bls["month"] = bls["month"].astype(str).str.slice(0, 7)
    bls["cpi_u_sa"] = pd.to_numeric(bls["cpi_u_sa"], errors="coerce")
    bls["unemployment_rate_sa"] = pd.to_numeric(bls["unemployment_rate_sa"], errors="coerce")
    bls = bls.drop_duplicates("month").set_index("month").sort_index()
    cpi = bls["cpi_u_sa"]
    yoy = (cpi / cpi.shift(12) - 1.0).shift(1)  # previous month's release
    chg3 = (cpi / cpi.shift(3) - 1.0).shift(1)
    gap = (bls["unemployment_rate_sa"] - bls["unemployment_rate_sa"].rolling(12, min_periods=12).min()).shift(1)
    key = index.to_period("M").astype(str)
    features["cpi_yoy"] = yoy.reindex(key).to_numpy()
    features["cpi_chg_3m"] = chg3.reindex(key).to_numpy()
    features["unemp_gap"] = gap.reindex(key).to_numpy()
    features["g_minus_tbill"] = features["g_mom_21"] * 12.0 * 100.0 - aligned["ust_3m"].to_numpy()
    features["vol_level"] = rv
    features["vol_pct"] = features["c_vol_pct"]
    features["vol_chg_5"] = rv.diff(1)
    features["vol_minus_rv"] = 0.0

    gpr = gpr_m.copy()
    gpr["month"] = gpr["month"].astype(str).str.slice(0, 7)
    gpr = gpr.drop_duplicates("month").set_index("month").sort_index()
    gpr["GPR"] = pd.to_numeric(gpr["GPR"], errors="coerce")
    z = (gpr["GPR"] - gpr["GPR"].rolling(12, min_periods=12).mean()) / gpr["GPR"].rolling(12, min_periods=12).std(ddof=1)
    z = z.shift(1)
    features["gpr_z"] = z.reindex(key).to_numpy()
    if "GPRA" in gpr.columns and "GPRT" in gpr.columns:
        diff = (pd.to_numeric(gpr["GPRA"], errors="coerce") - pd.to_numeric(gpr["GPRT"], errors="coerce")).shift(1)
        features["gpr_act_minus_threat"] = diff.reindex(key).to_numpy()
    else:
        features["gpr_act_minus_threat"] = np.nan
    features["gpr_spike"] = (features["gpr_z"] > 2).astype(float)
    features.loc[features["gpr_z"].isna(), "gpr_spike"] = np.nan
    for col in (
        "days_since_war",
        "days_since_crisis",
        "days_since_rate",
        "days_since_pandemic",
        "in_war_window",
        "in_crisis_window",
    ):
        features[col] = 0.0
    features["i_structural_break"] = (index >= pd.Timestamp("2024-10-30")).astype(float)
    features["si_listed"] = (index >= pd.Timestamp("2002-05-31")).astype(float)
    return features
