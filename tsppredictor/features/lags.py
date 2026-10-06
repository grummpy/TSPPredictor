"""Publication-lag helpers. These are the functions the no-look-ahead tests call."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def next_weekday(d: date) -> date:
    cursor = d + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor


def cpi_available_date(month: str) -> date:
    """CPI for month YYYY-MM is treated as available on the 15th of the next month."""
    period = pd.Period(month, freq="M")
    nxt = period + 1
    return date(int(nxt.year), int(nxt.month), 15)


def unemployment_available_date(month: str) -> date:
    """Unemployment for month YYYY-MM is treated as available on the 8th of the next month."""
    period = pd.Period(month, freq="M")
    nxt = period + 1
    return date(int(nxt.year), int(nxt.month), 8)


def shift_nyfed_dates(frame: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Move a forward-dated NY Fed probability file back 12 months.

    The published file dates the probability at the horizon it refers to.
    Subtracting 12 months puts the row on the month when the spread was known.
    """
    out = frame.copy()
    out[date_col] = pd.to_datetime(out[date_col]) - pd.DateOffset(months=12)
    return out


def asof_values(decision_dates: pd.DatetimeIndex, available_on: pd.Series, values: pd.Series) -> pd.Series:
    """Last value whose availability date is on or before each decision date."""
    table = pd.DataFrame(
        {
            "available_on": pd.to_datetime(pd.Series(available_on).to_numpy()),
            "value": pd.Series(values).to_numpy(),
        }
    )
    table = table.dropna(subset=["available_on"]).sort_values("available_on")
    # Drop duplicate publication timestamps, keeping the last revision in file order.
    table = table.drop_duplicates("available_on", keep="last")
    left = pd.DataFrame(
        {
            "decision": pd.to_datetime(pd.Index(decision_dates)),
            "_order": np.arange(len(decision_dates)),
        }
    ).sort_values("decision")
    merged = pd.merge_asof(left, table, left_on="decision", right_on="available_on", direction="backward")
    merged = merged.sort_values("_order")
    return pd.Series(merged["value"].to_numpy(), index=pd.DatetimeIndex(decision_dates))
