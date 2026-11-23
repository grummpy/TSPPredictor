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
            "publication_timing": "actual BLS CPI release date from the bundled release calendar; "
            "conservative fallback day outside its coverage",
            "source_vintage": "latest bundled revision",
        },
        {
            "series": "BLS unemployment",
            "publication_timing": "actual Employment Situation release date from the bundled release calendar; "
            "conservative fallback day outside its coverage",
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


def macro_vintage_metadata(first_print: Mapping[str, object] | None = None) -> dict:
    """Return an independent, serializable statement of macro-data limits.

    ``first_print`` maps series name -> first-print table (from the ALFRED
    connector cache).  When any is present the statement says so per series.
    """
    from tsppredictor.data.release_calendar import coverage

    meta = deepcopy(_MACRO_VINTAGE_METADATA)
    meta["release_calendar"] = coverage()
    if first_print:
        meta["first_print_vintages_available"] = True
        meta["vintage_status"] = "first_print_where_cached"
        meta["first_print_series"] = sorted(first_print)
        meta["limitation"] = (
            "First-print (ALFRED) values are used for the cached series listed in first_print_series; "
            "all other macro observations remain latest revisions."
        )
    return meta


def vintage_gap_report(first_print: Mapping[str, object] | None = None, *, as_of: str | None = None) -> dict:
    """Which macro series lack first-print data, and for how long.

    ``first_print`` maps series -> DataFrame with ``month`` (or ``date``) column.
    A series with no first-print table lacks it for its whole bundled history.
    """
    import pandas as pd

    from tsppredictor.data.snapshot import load_snapshot

    snap = load_snapshot()
    spans = {
        "CPIAUCSL": (snap.bls["month"].astype(str).min(), snap.bls["month"].astype(str).max()),
        "UNRATE": (snap.bls["month"].astype(str).min(), snap.bls["month"].astype(str).max()),
        "H15": (str(pd.Timestamp(snap.h15["date"].min()).date())[:7], str(pd.Timestamp(snap.h15["date"].max()).date())[:7]),
    }
    first_print = dict(first_print or {})
    rows = []
    for series, (start, end) in spans.items():
        table = first_print.get(series)
        if table is None or len(table) == 0:
            months = len(pd.period_range(start, end, freq="M"))
            rows.append({"series": series, "first_print": False, "gap_start": start, "gap_end": end,
                         "gap_months": months})
            continue
        column = "month" if "month" in table.columns else "date"
        covered = pd.PeriodIndex(pd.to_datetime(table[column].astype(str)), freq="M")
        wanted = pd.period_range(start, end, freq="M")
        missing = wanted.difference(covered)
        rows.append({"series": series, "first_print": True,
                     "gap_start": str(missing.min()) if len(missing) else None,
                     "gap_end": str(missing.max()) if len(missing) else None,
                     "gap_months": int(len(missing))})
    return {"kind": "vintage_gap_report", "as_of": as_of, "series": rows,
            "note": "H.15 rates are rarely revised; ALFRED first-print coverage applies to CPI and unemployment."}


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
    lag_invariant = []
    for row in rows:
        if row.get("kind") == "slice":
            # Buy-and-hold slices (e.g. I Fund before/after its benchmark change) make
            # no transfers, so execution lag cannot change them.
            lag_invariant.append({"id": str(row.get("id")), "cadence": row.get("cadence"), "name": row.get("name")})
            continue
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
    missing_runs = [
        {"id": row["id"], "cadence": row["cadence"], "horizon": row["horizon"],
         "run_lag": next(lag for lag in (1, 2) if lag not in row["available_lags"])}
        for row in unpaired if any(lag not in row["available_lags"] for lag in (1, 2))
    ]
    return {
        "kind": "execution_lag_sensitivity",
        "missing_runs": missing_runs,
        "note": (
            "Historical out-of-sample results only. Each comparison keeps strategy, cadence, and horizon fixed; "
            "it is not a forecast or a recommendation."
        ),
        "comparisons": comparisons,
        "unpaired": unpaired,
        "lag_invariant": lag_invariant,
    }


def lag_cost_table(rows: Iterable[Mapping]) -> list[dict]:
    """CAGR lost per extra day (session or month row) of execution lag, per strategy."""
    sensitivity = lag_sensitivity(rows)
    table = []
    for item in sensitivity["comparisons"]:
        difference = item["cagr"]["difference"]
        extra = item["compared_lag"] - item["reference_lag"]
        per_step = None if difference is None or extra <= 0 else -difference / extra
        unit = "session" if item["cadence"] == "daily" else "month"
        table.append({
            "id": item["id"], "name": item["name"], "cadence": item["cadence"], "horizon": item["horizon"],
            "reference_lag": item["reference_lag"], "compared_lag": item["compared_lag"],
            "cagr_lost_per_extra_lag": per_step, "unit": unit,
            "plain": None if per_step is None else (
                f"Each extra {unit} of lag {'cost' if per_step > 0 else 'added'} about "
                f"{abs(per_step) * 100:.2f} percentage points of CAGR for {item['name']} "
                f"({item['cadence']}, h={item['horizon']}). Historical only; not a forecast."
            ),
        })
    return sorted(table, key=lambda r: (r["cadence"], r["horizon"] or 0, -(r["cagr_lost_per_extra_lag"] or 0)))
