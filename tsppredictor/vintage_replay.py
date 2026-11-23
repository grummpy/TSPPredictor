"""Vintage Replay Lab: rerun the monthly rules on first-print macro data.

Revised CPI and unemployment series are what the bundled snapshot holds; the
values that were actually public at each decision date were the first prints.
When ALFRED first prints are cached (``tsp update --alfred`` with
``FRED_API_KEY``), this reruns every transparent monthly rule on both inputs and
shows what changes. Without the cache it says so and changes nothing.
"""

from __future__ import annotations

import pandas as pd

from tsppredictor import NOT_ADVICE
from tsppredictor.backtest.compare import drift_vs_constant
from tsppredictor.connectors.alfred import apply_first_print, enabled, load_cached_first_print
from tsppredictor.evidence import vintage_gap_report
from tsppredictor.features.monthly import build_monthly_features, monthly_price_index
from tsppredictor.models.rules import RULES


def replay(snap=None, first_print=None) -> dict:
    from tsppredictor.data.snapshot import load_snapshot

    snap = snap or load_snapshot()
    first_print = load_cached_first_print() if first_print is None else first_print
    gap = vintage_gap_report(first_print, as_of=str(pd.Timestamp(snap.daily.index.max()).date()))
    if not first_print:
        return {"available": False, "connector_enabled": enabled(), "gap_report": gap,
                "message": "No cached ALFRED first prints. Set FRED_API_KEY and run `tsp update --alfred --skip-tsp`.",
                "not_advice": NOT_ADVICE}
    px = monthly_price_index(snap.monthly)
    revised = build_monthly_features(snap.monthly, snap.h15, snap.bls, snap.gpr_monthly)
    first = build_monthly_features(snap.monthly, snap.h15, apply_first_print(snap.bls, first_print), snap.gpr_monthly)
    rows = []
    for rule_id in RULES:
        a = drift_vs_constant(rule_id, revised, px)
        b = drift_vs_constant(rule_id, first, px)
        changed = int((a["_drift_sim"]["weights"] != b["_drift_sim"]["weights"]).any(axis=1).sum())
        rows.append({"strategy": rule_id, "name": a["name"],
                     "revised_cagr": a["price_drift"]["cagr"], "first_print_cagr": b["price_drift"]["cagr"],
                     "cagr_change": b["price_drift"]["cagr"] - a["price_drift"]["cagr"],
                     "months_with_different_holdings": changed})
    return {"available": True, "gap_report": gap, "rows": rows, "not_advice": NOT_ADVICE}
