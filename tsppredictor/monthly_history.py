"""Prepare the dashboard's factual, official monthly-return history.

This module deliberately keeps published TSP fund returns separate from the
experimental walk-forward models.  Values are aligned to one shared list of
completed calendar months; missing observations remain missing rather than
being treated as a zero return.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

OFFICIAL_MONTHLY_FUNDS: tuple[tuple[str, str, str], ...] = (
    ("G", "G Fund", "G Fund"),
    ("F", "F Fund", "F Fund"),
    ("C", "C Fund", "C Fund"),
    ("S", "S Fund", "S Fund"),
    ("I", "I Fund", "I Fund"),
    ("L_INCOME", "L Income", "L Income"),
    ("L2030", "L 2030", "L 2030"),
    ("L2035", "L 2035", "L 2035"),
    ("L2040", "L 2040", "L 2040"),
    ("L2045", "L 2045", "L 2045"),
    ("L2050", "L 2050", "L 2050"),
    ("L2055", "L 2055", "L 2055"),
    ("L2060", "L 2060", "L 2060"),
    ("L2065", "L 2065", "L 2065"),
    ("L2070", "L 2070", "L 2070"),
    ("L2075", "L 2075", "L 2075"),
)


def compound_monthly_returns(values: Sequence[float | None]) -> list[float | None]:
    """Return cumulative wealth at each month-end without bridging a gap.

    The first available return starts a series at ``1 + return``.  Leading
    missing values are expected for newer funds.  A missing value after a fund
    has started makes later cumulative wealth unknown because silently
    skipping that month would overstate the precision of the compounded total.
    """

    wealth: list[float | None] = []
    compounded = 1.0
    started = False
    interrupted = False
    for value in values:
        if value is None or not np.isfinite(value):
            wealth.append(None)
            if started:
                interrupted = True
            continue
        if interrupted:
            wealth.append(None)
            continue
        compounded *= 1.0 + (float(value) / 100.0)
        wealth.append(round(compounded, 10))
        started = True
    return wealth


def _completed_month_frame(monthly: pd.DataFrame, data_as_of: str | pd.Timestamp) -> pd.DataFrame:
    if "month" not in monthly.columns:
        raise ValueError("official monthly-return data must include a month column")
    frame = monthly.copy()
    parsed = pd.to_datetime(frame["month"].astype(str).str.slice(0, 7) + "-01", errors="coerce")
    frame = frame.loc[parsed.notna()].copy()
    frame["_period"] = parsed.loc[parsed.notna()].dt.to_period("M")
    frame["month"] = frame["_period"].astype(str)
    frame = frame.sort_values("_period").drop_duplicates("_period", keep="last")
    cutoff = pd.Timestamp(data_as_of).to_period("M")
    return frame.loc[frame["_period"] < cutoff].copy()


def _numeric_values(frame: pd.DataFrame, column: str) -> list[float | None]:
    if column not in frame.columns:
        return [None] * len(frame)
    numeric = pd.to_numeric(frame[column], errors="coerce")
    return [round(float(value), 6) if np.isfinite(value) else None for value in numeric]


def _first_month(months: Sequence[str], values: Sequence[float | None]) -> str | None:
    for month, value in zip(months, values, strict=True):
        if value is not None:
            return month
    return None


def build_monthly_history(
    monthly: pd.DataFrame,
    data_as_of: str | pd.Timestamp,
    *,
    months: int = 120,
    funds: Sequence[tuple[str, str, str]] = OFFICIAL_MONTHLY_FUNDS,
) -> dict:
    """Build an aligned trailing window of completed official monthly returns."""

    if months < 1:
        raise ValueError("months must be at least one")
    completed = _completed_month_frame(monthly, data_as_of)
    if completed.empty:
        raise ValueError("no completed official monthly-return rows are available")

    # The window is a calendar window, not the last 120 rows that happened to
    # be present in the CSV. Reindexing makes an entirely absent source month
    # visible to the dashboard as missing data instead of silently extending
    # the history farther into the past.
    cutoff = pd.Timestamp(data_as_of).to_period("M")
    window_periods = pd.period_range(end=cutoff - 1, periods=months, freq="M")
    window = completed.set_index("_period").reindex(window_periods)
    window["_period"] = window.index
    window["month"] = window.index.astype(str)
    month_keys = window["month"].tolist()
    payload_funds: dict[str, dict] = {}
    for fund_id, label, column in funds:
        full_values = _numeric_values(completed, column)
        values = _numeric_values(window, column)
        wealth = compound_monthly_returns(values)
        first_after_start = _first_month(month_keys, values)
        missing_after_start = []
        if first_after_start is not None:
            first_index = month_keys.index(first_after_start)
            missing_after_start = [month for month, value in zip(month_keys[first_index:], values[first_index:], strict=True) if value is None]
        payload_funds[fund_id] = {
            "label": label,
            "source_column": column,
            "first_available": _first_month(completed["month"].tolist(), full_values),
            "first_available_in_window": first_after_start,
            "return_pct": values,
            "cumulative_wealth": wealth,
            "missing_months": [month for month, value in zip(month_keys, values, strict=True) if value is None],
            "missing_after_start": missing_after_start,
            "compounded_return_pct": None if not wealth or wealth[-1] is None else round((wealth[-1] - 1.0) * 100.0, 6),
        }
    return {
        "schema_version": 1,
        "kind": "official_monthly_returns",
        "source": "TSP.gov published monthly return summary bundled with this local snapshot",
        "source_file": "data/snapshot/tsp_monthly_returns_pct.csv",
        "data_as_of": pd.Timestamp(data_as_of).strftime("%Y-%m-%d"),
        "monthly_returns_through": completed["month"].iloc[-1],
        "window_start": month_keys[0],
        "window_end": month_keys[-1],
        "completed_month_count": len(month_keys),
        "months": month_keys,
        "funds": payload_funds,
    }
