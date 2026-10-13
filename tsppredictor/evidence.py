"""Auditable data-vintage and execution-lag evidence for local builds.

The bundled macro files are revised/latest observations.  They are useful for
reproducing this local backtest, but they are not first-print vintage data.
This module makes that limitation and the already-calculated lag alternatives
machine-readable instead of leaving them only in prose.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy


_MACRO_VINTAGE_METADATA = {
    "kind": "macro_availability_and_vintage",
    "vintage_status": "latest_revision_only",
    "first_print_vintages_available": False,
    "limitation": (
        "Bundled macro observations are the latest revisions in the local snapshot. "
        "They are not asserted to be the first releases available on a historical decision date."
    ),
    "availability_rules": [
        {
            "series": "BLS CPI",
            "publication_timing": "assumed 15th of the following month",
            "source_vintage": "latest bundled revision",
        },
        {
            "series": "BLS unemployment",
            "publication_timing": "assumed 8th of the following month",
            "source_vintage": "latest bundled revision",
        },
        {
            "series": "Federal Reserve H.15",
            "publication_timing": "next weekday after the observation date",
            "source_vintage": "latest bundled revision",
        },
        {
            "series": "Caldara-Iacoviello daily GPR",
            "publication_timing": "one calendar day after the observation date",
            "source_vintage": "latest bundled revision",
        },
    ],
}


def macro_vintage_metadata() -> dict:
    """Return an independent, serializable statement of macro-data limits."""
    return deepcopy(_MACRO_VINTAGE_METADATA)


def _number(value):
    return None if value is None else float(value)


def lag_sensitivity(rows: Iterable[Mapping]) -> dict:
    """Compare stored like-for-like results across configured execution lags.

    This does not create a new model run.  It exposes the already-run lag-1 and
    lag-2 blocks, keeping cadence, horizon, and strategy fixed.  A row that has
    no companion lag remains explicit in ``unpaired`` rather than being silently
    compared to a different horizon.
    """
    grouped: dict[tuple[str, str, int | None], dict[int, Mapping]] = {}
    for row in rows:
        try:
            key = (str(row["id"]), str(row["cadence"]), row.get("horizon"))
            lag = int(row["lag"])
        except (KeyError, TypeError, ValueError):
            continue
        grouped.setdefault(key, {})[lag] = row

    comparisons = []
    unpaired = []
    for (strategy_id, cadence, horizon), by_lag in sorted(grouped.items()):
        available = sorted(by_lag)
        if len(available) < 2:
            unpaired.append(
                {
                    "id": strategy_id,
                    "cadence": cadence,
                    "horizon": horizon,
                    "available_lags": available,
                }
            )
            continue
        reference_lag = available[0]
        reference = by_lag[reference_lag]
        for compared_lag in available[1:]:
            compared = by_lag[compared_lag]
            reference_metrics = reference.get("metrics") or {}
            compared_metrics = compared.get("metrics") or {}
            reference_bh_c = (reference.get("versus") or {}).get("bh_c") or {}
            compared_bh_c = (compared.get("versus") or {}).get("bh_c") or {}
            reference_cagr = _number(reference_metrics.get("cagr"))
            compared_cagr = _number(compared_metrics.get("cagr"))
            reference_excess = _number(reference_bh_c.get("excess_cagr"))
            compared_excess = _number(compared_bh_c.get("excess_cagr"))
            comparisons.append(
                {
                    "id": strategy_id,
                    "name": str(reference.get("name", strategy_id)),
                    "cadence": cadence,
                    "horizon": horizon,
                    "reference_lag": reference_lag,
                    "compared_lag": compared_lag,
                    "cagr": {
                        "reference": reference_cagr,
                        "compared": compared_cagr,
                        "difference": None
                        if reference_cagr is None or compared_cagr is None
                        else compared_cagr - reference_cagr,
                    },
                    "excess_cagr_vs_bh_c": {
                        "reference": reference_excess,
                        "compared": compared_excess,
                        "difference": None
                        if reference_excess is None or compared_excess is None
                        else compared_excess - reference_excess,
                    },
                }
            )
    return {
        "kind": "execution_lag_sensitivity",
        "note": (
            "Historical out-of-sample results only. Each comparison keeps strategy, cadence, and horizon fixed; "
            "it is not a forecast or a recommendation."
        ),
        "comparisons": comparisons,
        "unpaired": unpaired,
    }
