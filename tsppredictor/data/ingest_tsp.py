"""Refresh TSP.gov share prices and returns.

One request per file, with a browser User-Agent and the page Referer.
At most one successful refresh per Eastern calendar day unless ``force`` is set.
If validation fails, the previous snapshot files are left in place.
"""

from __future__ import annotations

import io
import json
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from tsppredictor.calendar import ET
from tsppredictor.data.snapshot import check_integrity, sha256_16
from tsppredictor.paths import snapshot_dir

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

DAILY_URL = "https://www.tsp.gov/data/fund-price-history.csv"
MONTHLY_URL = (
    "https://www.tsp.gov/data/getMonthlyReturnsSummary.csv"
    "?Lfunds=1&InvFunds=1&IndexFunds=1&Lifetime=1&Inception=1&Trailing=1"
)
RETIRED_URL = "https://www.tsp.gov/data/getRetiredRatesOfReturn.csv"

MONTHLY_COLUMNS = [
    "L Income",
    "L 2030",
    "L 2035",
    "L 2040",
    "L 2045",
    "L 2050",
    "L 2055",
    "L 2060",
    "L 2065",
    "L 2070",
    "L 2075",
    "G Fund",
    "F Fund",
    "U.S. Aggregate Index",
    "C Fund",
    "S&P 500",
    "S Fund",
    "DJ TSM",
    "I Fund",
    "EAFE",
]


def fetch_bytes(url: str, referer: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "text/csv,*/*"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def parse_daily_raw(text: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text))
    frame = frame.dropna(how="all")
    frame = frame[frame["Date"].notna()]
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame = frame.sort_values("Date").drop_duplicates("Date")
    return frame


def parse_monthly_raw(text: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(io.StringIO(text))
    frame.columns = [str(c).strip() for c in frame.columns]
    frame = frame[frame["type"].isin(["m", "y"])].copy()
    frame["Year"] = frame["Year"].astype(str).str.replace(r"\.0$", "", regex=True)
    monthly_rows = frame[frame["type"] == "m"].copy()
    month = monthly_rows["Year"].str.slice(0, 4) + "-" + monthly_rows["Year"].str.slice(4, 6)
    monthly = pd.DataFrame({"month": month})
    for col in MONTHLY_COLUMNS:
        monthly[col] = pd.to_numeric(monthly_rows[col], errors="coerce").to_numpy()
    monthly = monthly.reset_index(drop=True)

    annual_rows = frame[frame["type"] == "y"].copy()
    year = annual_rows["Year"].str.slice(0, 4).astype(int)
    period = annual_rows["Year"].astype(str)
    annual = pd.DataFrame(
        {
            "year": year.to_numpy(),
            "period_end_yyyymm": period.to_numpy(),
            "is_partial_year": ~period.str.endswith("12").to_numpy(),
        }
    )
    for col in MONTHLY_COLUMNS:
        annual[col] = pd.to_numeric(annual_rows[col], errors="coerce").to_numpy()
    annual = annual.reset_index(drop=True)
    return monthly, annual


def parse_retired_raw(text: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text))
    frame.columns = [str(c).strip().replace("  ", " ") for c in frame.columns]
    # "L  2010" -> "L 2010" after the double-space replace; collapse any remainder.
    frame.columns = [" ".join(str(c).split()) for c in frame.columns]
    rows = frame[frame["type"] == "m"].copy()
    year = rows["Year"].astype(str).str.replace(r"\.0$", "", regex=True)
    out = pd.DataFrame({"month": year.str.slice(0, 4) + "-" + year.str.slice(4, 6)})
    for src, dest in (("L 2010", "L 2010"), ("L 2020", "L 2020"), ("L 2025", "L 2025")):
        if src in rows.columns:
            out[dest] = pd.to_numeric(rows[src], errors="coerce").to_numpy()
    return out.reset_index(drop=True)


def _last_attempt_path(root: Path) -> Path:
    return root / ".last_attempt.json"


def _already_refreshed_today(root: Path) -> bool:
    path = _last_attempt_path(root)
    if not path.exists():
        return False
    payload = json.loads(path.read_text())
    if not payload.get("ok"):
        return False
    stamp = datetime.fromisoformat(payload["at"]).astimezone(ET).date()
    return stamp == datetime.now(ET).date()


def _rewrite_manifest(root: Path, paths: list[str]) -> None:
    manifest_path = root / "MANIFEST.csv"
    manifest = pd.read_csv(manifest_path)
    for rel in paths:
        file_path = root / rel
        digest = sha256_16(file_path)
        if rel.endswith("tsp_daily_share_prices.csv"):
            frame = pd.read_csv(file_path)
            rows = len(frame)
            first = str(frame["Date"].iloc[0])[:10]
            last = str(frame["Date"].iloc[-1])[:10]
            cols = frame.shape[1]
        elif rel.endswith("tsp_monthly_returns_pct.csv"):
            frame = pd.read_csv(file_path)
            rows = len(frame)
            first = str(frame["month"].iloc[0])
            last = str(frame["month"].iloc[-1])
            cols = frame.shape[1]
        elif rel.endswith("tsp_annual_returns_pct.csv"):
            frame = pd.read_csv(file_path)
            rows = len(frame)
            first = str(int(frame["year"].iloc[0]))
            last = str(int(frame["year"].iloc[-1]))
            cols = frame.shape[1]
        elif rel.endswith("tsp_retired_lfunds_monthly_returns_pct.csv"):
            frame = pd.read_csv(file_path)
            rows = len(frame)
            first = str(frame["month"].iloc[0])
            last = str(frame["month"].iloc[-1])
            cols = frame.shape[1]
        else:
            continue
        mask = manifest["path"] == rel
        if mask.any():
            manifest.loc[mask, "rows"] = rows
            manifest.loc[mask, "cols"] = cols
            manifest.loc[mask, "first_key"] = first
            manifest.loc[mask, "last_key"] = last
            manifest.loc[mask, "sha256_16"] = digest
    manifest.to_csv(manifest_path, index=False)


def update_tsp(force: bool = False, root: Path | None = None) -> dict:
    """Download, validate, and replace the TSP files. Keeps the old files on failure."""
    root = root or snapshot_dir()
    if not force and _already_refreshed_today(root):
        return {"updated": False, "reason": "already refreshed today (Eastern date); pass --force to override"}

    staging = root / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        daily_raw = fetch_bytes(DAILY_URL, "https://www.tsp.gov/share-price-history/").decode("utf-8", "replace")
        time.sleep(0.5)
        monthly_raw = fetch_bytes(MONTHLY_URL, "https://www.tsp.gov/rates-return/").decode("utf-8", "replace")
        time.sleep(0.5)
        retired_raw = fetch_bytes(RETIRED_URL, "https://www.tsp.gov/l-funds-retired/").decode("utf-8", "replace")
        daily = parse_daily_raw(daily_raw)
        monthly, annual = parse_monthly_raw(monthly_raw)
        retired = parse_retired_raw(retired_raw)
        daily.to_csv(staging / "tsp_daily_share_prices.csv", index=False)
        monthly.to_csv(staging / "tsp_monthly_returns_pct.csv", index=False)
        annual.to_csv(staging / "tsp_annual_returns_pct.csv", index=False)
        retired.to_csv(staging / "tsp_retired_lfunds_monthly_returns_pct.csv", index=False)

        # Validate the staged TSP files against the macro snapshot that stays put.
        # Copy macro inputs into a temp tree would be heavy; validate prices directly
        # by pointing load at a merged view.
        for name in (
            "events.csv",
            "MANIFEST.csv",
            "SOURCES.md",
        ):
            src = root / name
            if src.exists():
                shutil.copy2(src, staging / name)
        for rel in (
            "macro/primary/fed_h15_treasury_cmt_and_effr_daily.csv",
            "macro/primary/bls_cpi_unemployment_monthly.csv",
            "macro/gpr_daily_caldara_iacoviello.csv",
            "macro/gpr_monthly_caldara_iacoviello.csv",
            "macro/nber_business_cycle_dates.csv",
        ):
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)
        # Manifest hashes will not match staged TSP files. Load by bypassing hash check.
        snap = _load_without_hash(staging)
        report = check_integrity(snap)
        if not report.ok:
            raise RuntimeError("validation failed: " + "; ".join(report.errors))

        replaced = [
            "tsp_daily_share_prices.csv",
            "tsp_monthly_returns_pct.csv",
            "tsp_annual_returns_pct.csv",
            "tsp_retired_lfunds_monthly_returns_pct.csv",
        ]
        for name in replaced:
            shutil.copy2(staging / name, root / name)
        _rewrite_manifest(root, replaced)
        payload = {
            "at": datetime.now(ET).isoformat(),
            "ok": True,
            "data_as_of": report.stats.get("daily_last"),
            "warnings": report.warnings,
            "recon_worst_pp": report.stats.get("recon_worst_pp"),
        }
        _last_attempt_path(root).write_text(json.dumps(payload, indent=2))
        (root / "REFRESH.json").write_text(json.dumps(payload, indent=2))
        return {"updated": True, **payload}
    except Exception as exc:
        fail = {"at": datetime.now(ET).isoformat(), "ok": False, "error": str(exc)}
        _last_attempt_path(root).write_text(json.dumps(fail, indent=2))
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _load_without_hash(root: Path):
    """Load a staging tree. Hash mismatches are expected before the manifest rewrite."""
    from tsppredictor.data.snapshot import Snapshot

    daily = pd.read_csv(root / "tsp_daily_share_prices.csv")
    daily["Date"] = pd.to_datetime(daily["Date"])
    daily = daily.sort_values("Date").set_index("Date")
    rename = {
        "G Fund": "G",
        "F Fund": "F",
        "C Fund": "C",
        "S Fund": "S",
        "I Fund": "I",
    }
    daily = daily.rename(columns=rename)
    for col in rename.values():
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    return Snapshot(
        root=root,
        daily=daily,
        monthly=pd.read_csv(root / "tsp_monthly_returns_pct.csv"),
        annual=pd.read_csv(root / "tsp_annual_returns_pct.csv"),
        retired=pd.read_csv(root / "tsp_retired_lfunds_monthly_returns_pct.csv"),
        events=pd.read_csv(root / "events.csv"),
        h15=_dated(root / "macro/primary/fed_h15_treasury_cmt_and_effr_daily.csv", "date"),
        bls=pd.read_csv(root / "macro/primary/bls_cpi_unemployment_monthly.csv"),
        gpr_daily=_dated(root / "macro/gpr_daily_caldara_iacoviello.csv", "date"),
        gpr_monthly=pd.read_csv(root / "macro/gpr_monthly_caldara_iacoviello.csv"),
        nber=pd.read_csv(root / "macro/nber_business_cycle_dates.csv"),
        manifest=pd.read_csv(root / "MANIFEST.csv"),
        hash_report={"ok": True, "present": [], "missing": [], "mismatched": []},
    )


def _dated(path: Path, col: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame[col] = pd.to_datetime(frame[col])
    return frame
