"""Federal Reserve H.15 via the Board's Data Download Program (DDP).

``tsp update --h15`` downloads the official CSV package for the series the
macro rules cite and writes a normalized copy to ``data/cache/h15_ddp.csv``.
The bundled snapshot stays the default input; the DDP pull is opt-in.
"""

from __future__ import annotations

import io

import pandas as pd

from tsppredictor.paths import cache_dir

DDP_URL = "https://www.federalreserve.gov/datadownload/Output.aspx"
# Treasury constant-maturity package (verified 2026-11-22: returns RIFLGFCM01..RIFLGFCY30).
PACKAGE = "bf17364827e38702b42a58cf8eaa3f78"
SERIES = {
    "RIFLGFCM03_N.B": "ust_3m",
    "RIFLGFCY02_N.B": "ust_2y",
    "RIFLGFCY10_N.B": "ust_10y",
}


def ddp_params(start: str = "", end: str = "", lastobs: str = "") -> dict:
    return {"rel": "H15", "series": PACKAGE, "lastobs": lastobs, "from": start, "to": end,
            "filetype": "csv", "label": "include", "layout": "seriescolumn"}


def parse_ddp_csv(text: str) -> pd.DataFrame:
    """Parse a DDP 'seriescolumn' CSV: descriptor rows, then a 'Time Period' header of series codes."""
    lines = text.splitlines()
    header_row = next(i for i, line in enumerate(lines) if line.lstrip('"').startswith("Time Period"))
    frame = pd.read_csv(io.StringIO("\n".join(lines[header_row:])), na_values=["ND", "NC", "NA"])
    frame = frame.rename(columns={frame.columns[0]: "date", **SERIES})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date"]).reset_index(drop=True)


def fetch(session=None, timeout: float = 60.0) -> dict:
    import requests

    http = session or requests
    response = http.get(DDP_URL, params=ddp_params(), timeout=timeout,
                        headers={"User-Agent": "Mozilla/5.0 (TSP Predictor; educational)"})
    response.raise_for_status()
    frame = parse_ddp_csv(response.text)
    path = cache_dir() / "h15_ddp.csv"
    frame.to_csv(path, index=False)
    return {"rows": len(frame), "path": str(path), "columns": list(frame.columns)}
