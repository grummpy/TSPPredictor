"""Feature registry. The dashboard data dictionary is generated from this list."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    source: str
    publication_lag: str
    description: str
    unit: str
    model: bool = True


def _specs() -> list[FeatureSpec]:
    rows: list[FeatureSpec] = []

    def add(name, source, lag, description, unit, model=True):
        rows.append(FeatureSpec(name, source, lag, description, unit, model))

    for fund, label in (("c", "C Fund"), ("s", "S Fund"), ("i", "I Fund"), ("f", "F Fund")):
        for window, text in ((21, "1-month"), (63, "3-month"), (126, "6-month"), (252, "12-month")):
            add(
                f"{fund}_mom_{window}",
                "TSP share prices",
                "close of day t",
                f"{label} total return over the trailing {text} ({window} TSP sessions).",
                "decimal return",
                model=fund == "c" or window == 252,
            )
        add(
            f"{fund}_mom_12_1",
            "TSP share prices",
            "close of day t",
            f"{label} return from 12 months ago to 1 month ago, skipping the latest month.",
            "decimal return",
            model=fund == "c",
        )
    for fund in ("g",):
        for window in (21, 63, 252):
            add(
                f"{fund}_mom_{window}",
                "TSP share prices",
                "close of day t",
                f"G Fund total return over {window} TSP sessions.",
                "decimal return",
                model=False,
            )
    add("c_above_sma50", "TSP share prices", "close of day t", "1 when the C Fund price is above its 50-session average.", "0/1")
    add("c_above_sma100", "TSP share prices", "close of day t", "1 when the C Fund price is above its 100-session average.", "0/1", model=False)
    add("c_above_sma200", "TSP share prices", "close of day t", "1 when the C Fund price is above its 200-session average.", "0/1")
    add("c_above_sma10m", "TSP share prices", "close of day t", "1 when the C Fund price is above its 10-month (210-session) average.", "0/1")
    add("c_sma200_slope", "TSP share prices", "close of day t", "20-session change in the C Fund 200-session average.", "decimal", model=False)
    add(
        "c_dist_vol",
        "TSP share prices",
        "close of day t",
        "C Fund distance from its 200-session average, divided by annualized 63-session volatility.",
        "vol units",
    )
    for fund, label in (("s", "S Fund"), ("i", "I Fund"), ("f", "F Fund")):
        add(
            f"{fund}_above_sma200",
            "TSP share prices",
            "close of day t",
            f"1 when the {label} price is above its 200-session average.",
            "0/1",
            model=False,
        )
    add("c_rv20", "TSP share prices", "close of day t", "C Fund 20-session realized volatility, annualized with 252.", "decimal")
    add("c_rv63", "TSP share prices", "close of day t", "C Fund 63-session realized volatility, annualized with 252.", "decimal")
    add("c_vvol", "TSP share prices", "close of day t", "63-session standard deviation of 20-session realized volatility.", "decimal", model=False)
    add("c_downside", "TSP share prices", "close of day t", "63-session downside deviation of C Fund daily returns.", "decimal")
    add(
        "c_vol_pct",
        "TSP share prices",
        "expanding window through t",
        "Expanding percentile rank of 63-session C Fund volatility. Uses only history through t.",
        "0-1",
    )
    add("c_dd", "TSP share prices", "close of day t", "C Fund drawdown from its running peak through t.", "decimal")
    add("c_days_since_peak", "TSP share prices", "close of day t", "TSP sessions since the C Fund running peak.", "sessions", model=False)
    add("c_ulcer", "TSP share prices", "close of day t", "63-session Ulcer index of the C Fund.", "decimal")
    for fund, label in (("s", "S"), ("i", "I"), ("f", "F")):
        add(f"{fund}_dd", "TSP share prices", "close of day t", f"{label} Fund drawdown from its running peak.", "decimal", model=False)
    add("c_rs_rank", "TSP share prices", "close of day t", "Cross-sectional rank of 12-month return among C, S, and I. 3 is strongest.", "rank")
    add("s_rs_rank", "TSP share prices", "close of day t", "Cross-sectional rank of 12-month return among C, S, and I. 3 is strongest.", "rank", model=False)
    add("i_rs_rank", "TSP share prices", "close of day t", "Cross-sectional rank of 12-month return among C, S, and I. 3 is strongest.", "rank", model=False)
    add(
        "c_dual_mom",
        "TSP share prices",
        "close of day t",
        "1 when C leads S and I over 12 months and also beat the G Fund over 12 months.",
        "0/1",
    )
    add("s_dual_mom", "TSP share prices", "close of day t", "Same dual-momentum flag for the S Fund.", "0/1", model=False)
    add("i_dual_mom", "TSP share prices", "close of day t", "Same dual-momentum flag for the I Fund.", "0/1", model=False)
    add("month", "calendar", "known at t", "Calendar month number. A feature to test, not an assumed effect.", "1-12", model=False)
    add("month_sin", "calendar", "known at t", "Sine of the month, so the model does not treat December as larger than January.", "unitless")
    add("month_cos", "calendar", "known at t", "Cosine of the month.", "unitless")
    add(
        "turn_of_month",
        "calendar",
        "known at t",
        "1 on the last scheduled business day of the month and the first three sessions. Schedule uses holiday rules, not future prices.",
        "0/1",
    )
    add(
        "pre_holiday",
        "calendar",
        "known at t",
        "1 when the next scheduled session skips a weekday holiday. Weekend-only gaps are not flagged.",
        "0/1",
        model=False,
    )
    add("nov_apr", "calendar", "known at t", "1 in November through April, else 0. The 'Sell in May' split, tested rather than assumed.", "0/1")
    add("pres_cycle", "calendar", "known at t", "Calendar year modulo 4. Election years are 0. A feature to test, not an assumed effect.", "0-3", model=False)
    add(
        "spread_10y_3m",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "10-year minus 3-month Treasury yield, in percentage points, lagged to the next weekday.",
        "percentage points",
    )
    add(
        "spread_10y_2y",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "10-year minus 2-year Treasury yield, lagged to the next weekday.",
        "percentage points",
    )
    add(
        "spread_10y_3m_chg_63",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "Change in the lagged 10y-3m spread over 63 TSP sessions.",
        "percentage points",
    )
    add(
        "spread_10y_2y_chg_63",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "Change in the lagged 10y-2y spread over 63 TSP sessions.",
        "percentage points",
        model=False,
    )
    add("curve_inverted", "Federal Reserve H.15", "next weekday after the observation", "1 when the lagged 10y-3m spread is negative.", "0/1")
    add(
        "months_inverted",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "How long the lagged 10y-3m spread has been negative, in approximate months.",
        "months",
    )
    add(
        "tbill_minus_effr",
        "Federal Reserve H.15",
        "next weekday after the observation",
        "3-month Treasury yield minus the effective federal funds rate, both lagged.",
        "percentage points",
        model=False,
    )
    add(
        "cpi_yoy",
        "BLS CPI-U SA",
        "15th of the following month",
        "Year-over-year change in CPI-U, visible only from the 15th of the next month. Latest vintage, not a real-time vintage.",
        "decimal",
    )
    add(
        "cpi_chg_3m",
        "BLS CPI-U SA",
        "15th of the following month",
        "Three-month change in CPI-U, same publication lag.",
        "decimal",
        model=False,
    )
    add(
        "unemp_gap",
        "BLS unemployment rate SA",
        "8th of the following month",
        "Unemployment rate minus its minimum over the prior 12 months. Sahm-style derived indicator, not the official Sahm rule.",
        "percentage points",
    )
    add(
        "g_minus_tbill",
        "TSP G Fund and H.15",
        "G at close t; bill lagged one weekday",
        "Annualized trailing 21-session G Fund return, in percent, minus the lagged 3-month yield.",
        "percentage points",
        model=False,
    )
    add(
        "vol_level",
        "Cboe VIX if cached, else C Fund realized volatility",
        "VIX same-day close; realized vol uses the close of t",
        "VIX close when a local Cboe file is present. Otherwise 20-session C Fund realized volatility. The build does not fail when VIX is absent.",
        "VIX points or decimal vol",
    )
    add("vol_pct", "same as vol_level", "same as vol_level", "Expanding percentile of vol_level through t.", "0-1", model=False)
    add("vol_chg_5", "same as vol_level", "same as vol_level", "Five-session change in vol_level.", "same as vol_level")
    add(
        "vol_minus_rv",
        "VIX and C Fund realized vol",
        "same-day close",
        "VIX minus 100 times 63-session C Fund realized vol when VIX is present; otherwise 0.",
        "points",
        model=False,
    )
    add(
        "gpr_z",
        "Caldara and Iacoviello GPR daily (CC BY)",
        "1 day",
        "GPR daily index minus its trailing-year mean, divided by its trailing-year standard deviation.",
        "z-score",
    )
    add(
        "gpr_act_minus_threat",
        "Caldara and Iacoviello GPR daily (CC BY)",
        "1 day",
        "GPR acts minus GPR threats, lagged one day.",
        "index points",
        model=False,
    )
    add(
        "gpr_spike",
        "Caldara and Iacoviello GPR daily (CC BY)",
        "1 day",
        "1 when the lagged GPR z-score is above 2.",
        "0/1",
    )
    add("days_since_war", "events.csv", "first_reaction_tsp_date", "TSP sessions since the latest war event, capped at 252. Blank before any event.", "sessions", model=False)
    add(
        "days_since_crisis",
        "events.csv",
        "first_reaction_tsp_date",
        "TSP sessions since the latest financial-crisis event, capped at 252.",
        "sessions",
        model=False,
    )
    add("days_since_rate", "events.csv", "first_reaction_tsp_date", "TSP sessions since the latest rate-shock event, capped at 252.", "sessions", model=False)
    add(
        "days_since_pandemic",
        "events.csv",
        "first_reaction_tsp_date",
        "TSP sessions since the latest pandemic event, capped at 252.",
        "sessions",
        model=False,
    )
    add(
        "in_war_window",
        "events.csv",
        "first_reaction_tsp_date",
        "1 during the 21 TSP sessions starting on a war event's first reaction date (days 0 through 20).",
        "0/1",
    )
    add(
        "in_crisis_window",
        "events.csv",
        "first_reaction_tsp_date",
        "1 during the 21 TSP sessions starting on a financial-crisis event's first reaction date.",
        "0/1",
    )
    add(
        "i_structural_break",
        "TSP announcement",
        "known from 2024-10-30",
        "1 on and after 2024-10-30, when TSP completed the I Fund benchmark change. 0 before that date.",
        "0/1",
        model=False,
    )
    add(
        "news_tone_z",
        "user headlines.csv scored with VADER, optional",
        "1 day",
        "Trailing-year z-score of the mean headline compound score. Absent unless the user supplies headlines. Selection of headlines can bias a backtest.",
        "z-score",
        model=False,
    )
    add(
        "news_volume_z",
        "user headlines.csv, optional",
        "1 day",
        "Trailing-year z-score of the daily headline count.",
        "z-score",
        model=False,
    )
    add(
        "nyfed_rec_prob",
        "NY Fed yield-curve model, optional cache",
        "shifted back 12 months, then month-end",
        "Recession probability after moving the forward-dated file back 12 months. Not in the default model matrix unless the cache file exists, and never taken from the raw forward date.",
        "probability",
        model=False,
    )
    return rows


FEATURES: list[FeatureSpec] = _specs()


def model_feature_names() -> list[str]:
    return [row.name for row in FEATURES if row.model]


def feature_dicts() -> list[dict]:
    return [asdict(row) for row in FEATURES]
