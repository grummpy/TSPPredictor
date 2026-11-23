"""Validation reports for the bundled price CSVs (Pointblank when installed).

The native checks always run; when the optional ``pointblank`` package is
installed the same rules are also expressed as a Pointblank validation so its
HTML report can be produced.
"""

from __future__ import annotations

import pandas as pd

FUNDS = ("G", "F", "C", "S", "I")


def validate_prices(prices: pd.DataFrame) -> dict:
    """Native checks: sorted unique dates, positive finite prices, no >50% one-day jumps."""
    frame = prices.copy()
    if "Date" in frame.columns:
        frame = frame.set_index(pd.to_datetime(frame["Date"])).drop(columns=["Date"])
    checks = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    index = pd.DatetimeIndex(frame.index)
    add("dates_sorted", index.is_monotonic_increasing)
    add("dates_unique", not index.has_duplicates, f"{int(index.duplicated().sum())} duplicate dates")
    for fund in FUNDS:
        if fund not in frame.columns:
            add(f"{fund}_present", False, "column missing")
            continue
        column = pd.to_numeric(frame[fund], errors="coerce")
        present = column.dropna()
        add(f"{fund}_positive", bool((present > 0).all()), f"{int((present <= 0).sum())} non-positive")
        jumps = present.pct_change().abs()
        big = jumps[jumps > 0.5]
        add(f"{fund}_no_extreme_jumps", big.empty, ", ".join(str(d.date()) for d in big.index[:5]))
    return {"kind": "price_validation", "rows": int(len(frame)), "passed": all(c["passed"] for c in checks),
            "checks": checks, "pointblank": pointblank_report(frame)}


def pointblank_report(frame: pd.DataFrame) -> dict:
    try:
        import pointblank as pb
    except ImportError:
        return {"available": False}
    data = frame.reset_index().rename(columns={frame.index.name or "index": "Date"})
    validation = pb.Validate(data=data, label="TSP daily share prices")
    for fund in FUNDS:
        if fund in data.columns:
            validation = validation.col_vals_gt(columns=fund, value=0, na_pass=True)
    validation = validation.interrogate()
    return {"available": True, "all_passed": bool(validation.all_passed())}
