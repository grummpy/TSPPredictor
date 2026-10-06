"""Optional Tier B/C fetchers. Everything lands in data/cache/ and is gitignored.

FRED copies are exploration charts only. Trained models do not read them.
VIX is Cboe history for local use. NY Fed probabilities are shifted back
12 months before any feature uses them. Fama-French and Shiller files are
context series, not training inputs for the TSP model.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from tsppredictor.data.ingest_tsp import fetch_bytes
from tsppredictor.paths import cache_dir

FRED_SERIES = [
    "VIXCLS",
    "DGS10",
    "DGS2",
    "DGS3MO",
    "DTB3",
    "T10Y2Y",
    "T10Y3M",
    "UNRATE",
    "CPIAUCSL",
    "FEDFUNDS",
    "DFF",
    "NFCI",
    "STLFSI4",
    "BAA10Y",
    "T10YIE",
    "ICSA",
    "DCOILWTICO",
    "DTWEXBGS",
    "USEPUINDXD",
    "USREC",
]

VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
FF_DAILY_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
FF_MONTHLY_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"
NYFED_URL = "https://www.newyorkfed.org/medialibrary/media/research/capital_markets/allmonth.xls"
SHILLER_URL = "https://shillerdata.com/ie_data.xls"
GDELT_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=stock%20market&mode=timelinetone&format=csv&timespan=5y"
)


def _cache(name: str) -> Path:
    path = cache_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def fetch_fred(series: list[str] | None = None) -> list[str]:
    """Download FRED graph CSVs for exploration. Not used to train models."""
    written = []
    for series_id in series or FRED_SERIES:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        raw = fetch_bytes(url, "https://fred.stlouisfed.org/")
        dest = _cache(f"macro/fred_{series_id}.csv")
        # Stamp the restriction into a sidecar so a later reader does not miss it.
        dest.write_bytes(raw)
        dest.with_suffix(".NOTE.txt").write_text(
            "Exploration copy via FRED. Do not use to train or develop the TSP model. "
            "FRED terms restrict using FRED content to develop machine-learning systems. "
            f"Source series {series_id} via FRED.\n"
        )
        written.append(str(dest))
    return written


def fetch_vix() -> Path:
    raw = fetch_bytes(VIX_URL, "https://www.cboe.com/")
    dest = _cache("macro/primary/vix_history_cboe.csv")
    dest.write_bytes(raw)
    dest.with_suffix(".NOTE.txt").write_text(
        "Cboe VIX history, local personal use. Tier C: do not commit or redistribute.\n"
    )
    return dest


def _french_zip_to_csv(raw: bytes, dest: Path, monthly: bool) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("latin1")
    lines = [ln.strip() for ln in text.splitlines()]
    # Skip the copyright preamble until the header row that starts with a comma.
    start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith(",mkt-rf") or line.lower().startswith(", mkt-rf"):
            start = i
            break
    body = "\n".join(lines[start:])
    # Stop at the first blank line after the table (annual section follows in the monthly file).
    kept = []
    started = False
    for line in body.splitlines():
        if not line.strip():
            if started:
                break
            continue
        started = True
        kept.append(line)
    frame = pd.read_csv(io.StringIO("\n".join(kept)))
    frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = frame["date"].astype(str).str.strip()
    if monthly:
        frame = frame[frame["date"].str.len() == 6]
        frame["date"] = frame["date"].str.slice(0, 4) + "-" + frame["date"].str.slice(4, 6)
    else:
        frame = frame[frame["date"].str.len() == 8]
        frame["date"] = (
            frame["date"].str.slice(0, 4) + "-" + frame["date"].str.slice(4, 6) + "-" + frame["date"].str.slice(6, 8)
        )
    for col in frame.columns[1:]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    dest.write_text(
        "# Copyright Eugene F. Fama and Kenneth R. French. Local cache only; not for redistribution.\n"
    )
    frame.to_csv(dest, mode="a", index=False)


def fetch_fama_french() -> list[str]:
    daily = fetch_bytes(FF_DAILY_URL, "https://mba.tuck.dartmouth.edu/")
    monthly = fetch_bytes(FF_MONTHLY_URL, "https://mba.tuck.dartmouth.edu/")
    dpath = _cache("macro/ff3_factors_daily.csv")
    mpath = _cache("macro/ff3_factors_monthly.csv")
    _french_zip_to_csv(daily, dpath, monthly=False)
    _french_zip_to_csv(monthly, mpath, monthly=True)
    return [str(dpath), str(mpath)]


def fetch_shiller() -> Path:
    raw = fetch_bytes(SHILLER_URL, "https://shillerdata.com/")
    dest = _cache("macro/shiller_ie_data.xls")
    dest.write_bytes(raw)
    try:
        frame = pd.read_excel(io.BytesIO(raw), sheet_name="Data", header=None)
        dest.with_suffix(".csv").write_text(frame.to_csv(index=False))
    except Exception as exc:
        dest.with_suffix(".NOTE.txt").write_text(f"Downloaded raw xls. CSV parse failed: {exc}\n")
    return dest


def fetch_nyfed() -> Path:
    raw = fetch_bytes(NYFED_URL, "https://www.newyorkfed.org/")
    dest = _cache("macro/nyfed_yield_curve_recession_probability.xls")
    dest.write_bytes(raw)
    try:
        frame = pd.read_excel(io.BytesIO(raw))
        csv_path = _cache("macro/nyfed_yield_curve_recession_probability.csv")
        frame.to_csv(csv_path, index=False)
        csv_path.with_suffix(".NOTE.txt").write_text(
            "NY Fed yield-curve recession probability. The file is forward-dated by 12 months. "
            "Shift the date back 12 months before using it as a feature.\n"
        )
        return csv_path
    except Exception as exc:
        dest.with_suffix(".NOTE.txt").write_text(f"Downloaded raw xls. CSV parse failed: {exc}\n")
        return dest


def fetch_gdelt_tone() -> Path:
    raw = fetch_bytes(GDELT_URL, "https://www.gdeltproject.org/")
    dest = _cache("news/gdelt_timelinetone.csv")
    dest.write_bytes(raw)
    dest.with_suffix(".NOTE.txt").write_text(
        "GDELT DOC 2.0 timeline tone. Cite GDELT. Optional, off by default, not used unless present.\n"
    )
    return dest


def fetch_optional(include_news: bool = False) -> dict:
    """Fetch Tier B/C sources into data/cache/. Failures are reported, not fatal to the others."""
    results: dict[str, str] = {}
    steps = {
        "fred": fetch_fred,
        "vix": fetch_vix,
        "fama_french": fetch_fama_french,
        "shiller": fetch_shiller,
        "nyfed": fetch_nyfed,
    }
    if include_news:
        steps["gdelt"] = fetch_gdelt_tone
    for name, fn in steps.items():
        try:
            results[name] = str(fn())
        except Exception as exc:
            results[name] = f"error: {exc}"
    return results


def load_cached_vix() -> pd.DataFrame | None:
    path = cache_dir() / "macro/primary/vix_history_cboe.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    # Cboe header: DATE, OPEN, HIGH, LOW, CLOSE
    cols = {c: c.strip().lower() for c in frame.columns}
    frame = frame.rename(columns=cols)
    date_col = "date" if "date" in frame.columns else frame.columns[0]
    frame["date"] = pd.to_datetime(frame[date_col], errors="coerce")
    close = "close" if "close" in frame.columns else frame.columns[-1]
    out = frame.dropna(subset=["date"]).sort_values("date")
    out["vix"] = pd.to_numeric(out[close], errors="coerce")
    return out[["date", "vix"]].dropna()


def load_cached_nyfed() -> pd.DataFrame | None:
    path = cache_dir() / "macro/nyfed_yield_curve_recession_probability.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    return frame
