"""ALFRED (Archival FRED) first-print vintages for CPI and unemployment.

Needs ``FRED_API_KEY`` in the environment (free key from the St. Louis Fed);
without it the connector is off.  ``output_type=4`` asks ALFRED for the initial
release of each observation, i.e. the value that was actually public first.
Results are cached under ``data/cache/alfred/`` (gitignored) and the build
uses them automatically when present.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from tsppredictor.paths import cache_dir

API = "https://api.stlouisfed.org/fred/series/observations"
SERIES = {"CPIAUCSL": "cpi_u_sa", "UNRATE": "unemployment_rate_sa"}


def api_key() -> str | None:
    key = os.environ.get("FRED_API_KEY", "").strip()
    return key or None


def enabled() -> bool:
    return api_key() is not None


def first_print_params(series: str, key: str) -> dict:
    return {
        "series_id": series,
        "api_key": key,
        "file_type": "json",
        "realtime_start": "1776-07-04",
        "realtime_end": "9999-12-31",
        "output_type": 4,  # initial release only
    }


def parse_observations(payload: dict) -> pd.DataFrame:
    rows = []
    for item in payload.get("observations", []):
        value = item.get("value")
        if value in (None, "."):
            continue
        rows.append({"month": str(item["date"])[:7], "value": float(value),
                     "first_published": item.get("realtime_start")})
    frame = pd.DataFrame(rows, columns=["month", "value", "first_published"])
    return frame.drop_duplicates("month", keep="first").sort_values("month").reset_index(drop=True)


def cache_path(series: str) -> Path:
    path = cache_dir() / "alfred"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{series}_first_print.csv"


def fetch_first_print(series: str, session=None, timeout: float = 30.0) -> pd.DataFrame:
    key = api_key()
    if key is None:
        raise RuntimeError("ALFRED connector is off: set FRED_API_KEY to enable it")
    import requests

    http = session or requests
    response = http.get(API, params=first_print_params(series, key), timeout=timeout)
    response.raise_for_status()
    frame = parse_observations(response.json())
    frame.to_csv(cache_path(series), index=False)
    return frame


def load_cached_first_print() -> dict[str, pd.DataFrame]:
    out = {}
    for series in SERIES:
        path = cache_dir() / "alfred" / f"{series}_first_print.csv"
        if path.exists():
            frame = pd.read_csv(path, dtype={"month": str})
            if len(frame):
                out[series] = frame
    return out


def apply_first_print(bls: pd.DataFrame, first_print: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Point-in-time macro inputs: replace latest revisions with first prints where cached."""
    out = bls.copy()
    out["month"] = out["month"].astype(str).str.slice(0, 7)
    for series, column in SERIES.items():
        table = first_print.get(series)
        if table is None or not len(table):
            continue
        mapping = dict(zip(table["month"].astype(str).str.slice(0, 7), table["value"], strict=False))
        replaced = out["month"].map(mapping)
        out[column] = replaced.where(replaced.notna(), pd.to_numeric(out[column], errors="coerce"))
    return out
