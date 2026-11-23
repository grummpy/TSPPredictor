"""Profile each price snapshot and flag odd shifts (whylogs when installed).

A compact native profile (per-fund count/mean/std of daily returns and last
price) is always computed and compared with the previous profile saved in the
cache.  If ``whylogs`` is installed its profile is also written next to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tsppredictor.paths import cache_dir

FUNDS = ("G", "F", "C", "S", "I")


def profile(prices: pd.DataFrame) -> dict:
    out = {}
    for fund in FUNDS:
        if fund not in prices.columns:
            continue
        series = pd.to_numeric(prices[fund], errors="coerce").dropna()
        rets = series.pct_change().dropna()
        out[fund] = {"count": int(series.size), "last": float(series.iloc[-1]) if series.size else None,
                     "ret_mean": float(rets.mean()) if rets.size else None,
                     "ret_std": float(rets.std(ddof=1)) if rets.size > 1 else None}
    return out


def compare(previous: dict, current: dict, *, z: float = 4.0) -> list[dict]:
    """Flags: fewer rows than before, or a return std that moved by > z-fold log ratio."""
    flags = []
    for fund, now in current.items():
        before = previous.get(fund)
        if not before:
            continue
        if now["count"] < before["count"]:
            flags.append({"fund": fund, "flag": "rows_decreased", "before": before["count"], "now": now["count"]})
        if before.get("ret_std") and now.get("ret_std"):
            ratio = abs(np.log(now["ret_std"] / before["ret_std"]))
            if ratio > np.log(z) / 4:
                flags.append({"fund": fund, "flag": "volatility_shift", "before": before["ret_std"],
                              "now": now["ret_std"]})
    return flags


def profile_snapshot(prices: pd.DataFrame, store: Path | None = None) -> dict:
    store = store or (cache_dir() / "price_profile.json")
    current = profile(prices)
    previous = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    flags = compare(previous, current)
    store.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    result = {"kind": "price_profile", "funds": current, "flags": flags, "whylogs": False}
    try:
        import whylogs as why
    except ImportError:
        return result
    view = why.log(pandas=prices.reset_index(drop=True)).view()
    view.write(str(store.with_suffix(".whylogs.bin")))
    result["whylogs"] = True
    return result
