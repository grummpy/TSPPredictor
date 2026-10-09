"""Load the bundled Tier A snapshot and check it against MANIFEST.csv."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from tsppredictor.paths import snapshot_dir

CORE = ("G Fund", "F Fund", "C Fund", "S Fund", "I Fund")
CORE_MAP = {"G Fund": "G", "F Fund": "F", "C Fund": "C", "S Fund": "S", "I Fund": "I"}
L_MAP = {
    "L Income": "L_INCOME",
    "L 2030": "L2030",
    "L 2035": "L2035",
    "L 2040": "L2040",
    "L 2045": "L2045",
    "L 2050": "L2050",
    "L 2055": "L2055",
    "L 2060": "L2060",
    "L 2065": "L2065",
    "L 2070": "L2070",
    "L 2075": "L2075",
}

# These are the files the offline application actually opens.  The manifest
# also records Tier B/C reference material, which may deliberately be absent
# from a small, distributable snapshot.
REQUIRED_SNAPSHOT_FILES = frozenset(
    {
        "MANIFEST.csv",
        "tsp_daily_share_prices.csv",
        "tsp_monthly_returns_pct.csv",
        "tsp_annual_returns_pct.csv",
        "tsp_retired_lfunds_monthly_returns_pct.csv",
        "events.csv",
        "macro/primary/fed_h15_treasury_cmt_and_effr_daily.csv",
        "macro/primary/bls_cpi_unemployment_monthly.csv",
        "macro/gpr_daily_caldara_iacoviello.csv",
        "macro/gpr_monthly_caldara_iacoviello.csv",
        "macro/nber_business_cycle_dates.csv",
    }
)


def sha256_16(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


@dataclass
class IntegrityReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    root: Path
    daily: pd.DataFrame
    monthly: pd.DataFrame
    annual: pd.DataFrame
    retired: pd.DataFrame
    events: pd.DataFrame
    h15: pd.DataFrame
    bls: pd.DataFrame
    gpr_daily: pd.DataFrame
    gpr_monthly: pd.DataFrame
    nber: pd.DataFrame
    manifest: pd.DataFrame
    hash_report: dict


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def verify_manifest(root: Path | None = None) -> dict:
    """Hash supplied files and distinguish required data from optional Tier B/C."""
    root = root or snapshot_dir()
    manifest = pd.read_csv(root / "MANIFEST.csv")
    present = []
    missing = []
    mismatched = []
    for row in manifest.itertuples(index=False):
        path = root / row.path
        if not path.exists():
            missing.append(row.path)
            continue
        digest = sha256_16(path)
        if digest != row.sha256_16:
            mismatched.append({"path": row.path, "expected": row.sha256_16, "actual": digest})
        else:
            present.append(row.path)
    required_missing = [path for path in missing if path in REQUIRED_SNAPSHOT_FILES]
    optional_missing = [path for path in missing if path not in REQUIRED_SNAPSHOT_FILES]
    return {
        "present": present,
        "missing": missing,
        "mismatched": mismatched,
        "required_missing": required_missing,
        "optional_missing": optional_missing,
        "ok": not mismatched and not required_missing,
    }


def load_snapshot(root: Path | None = None) -> Snapshot:
    root = root or snapshot_dir()
    hashes = verify_manifest(root)
    if hashes["mismatched"] or hashes["required_missing"]:
        raise ValueError(
            "Snapshot validation failed: "
            f"mismatched={hashes['mismatched']}, required_missing={hashes['required_missing']}"
        )

    daily = _read_csv(root / "tsp_daily_share_prices.csv")
    daily["Date"] = pd.to_datetime(daily["Date"])
    daily = daily.sort_values("Date").drop_duplicates("Date").set_index("Date")
    rename = {**CORE_MAP, **L_MAP}
    daily = daily.rename(columns=rename)
    for col in list(rename.values()):
        if col in daily.columns:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")

    monthly = _read_csv(root / "tsp_monthly_returns_pct.csv")
    annual = _read_csv(root / "tsp_annual_returns_pct.csv")
    retired = _read_csv(root / "tsp_retired_lfunds_monthly_returns_pct.csv")
    events = _read_csv(root / "events.csv")
    h15 = _read_csv(root / "macro/primary/fed_h15_treasury_cmt_and_effr_daily.csv")
    h15["date"] = pd.to_datetime(h15["date"])
    bls = _read_csv(root / "macro/primary/bls_cpi_unemployment_monthly.csv")
    gpr_d = _read_csv(root / "macro/gpr_daily_caldara_iacoviello.csv")
    gpr_d["date"] = pd.to_datetime(gpr_d["date"])
    gpr_m = _read_csv(root / "macro/gpr_monthly_caldara_iacoviello.csv")
    nber = _read_csv(root / "macro/nber_business_cycle_dates.csv")
    manifest = pd.read_csv(root / "MANIFEST.csv")
    return Snapshot(
        root=root,
        daily=daily,
        monthly=monthly,
        annual=annual,
        retired=retired,
        events=events,
        h15=h15,
        bls=bls,
        gpr_daily=gpr_d,
        gpr_monthly=gpr_m,
        nber=nber,
        manifest=manifest,
        hash_report=hashes,
    )


def month_end_return_pct(daily: pd.DataFrame, fund: str) -> pd.Series:
    """Month-end percent return from daily prices. Index is YYYY-MM."""
    prices = daily[fund].dropna()
    grouped = prices.groupby(prices.index.to_period("M"))
    last = grouped.last()
    ret = last.pct_change() * 100.0
    ret.index = ret.index.astype(str)
    return ret.iloc[1:]


def check_integrity(snap: Snapshot, as_of_today: pd.Timestamp | None = None) -> IntegrityReport:
    """Validation used by ``tsp update`` and by the test suite's expectations."""
    report = IntegrityReport(ok=True)
    daily = snap.daily
    if not daily.index.is_monotonic_increasing:
        report.errors.append("daily dates are not ascending")
    if daily.index.has_duplicates:
        report.errors.append("daily dates are not unique")
    core = ["G", "F", "C", "S", "I"]
    for fund in core:
        if daily[fund].isna().any():
            report.errors.append(f"{fund} has empty prices")
        if (daily[fund] <= 0).any():
            report.errors.append(f"{fund} has a non-positive price")
    g_diff = daily["G"].diff()
    if (g_diff.dropna() < -1e-9).any():
        report.errors.append("G Fund price decreased")
    report.stats["n_daily"] = int(len(daily))
    report.stats["daily_first"] = daily.index.min().strftime("%Y-%m-%d")
    report.stats["daily_last"] = daily.index.max().strftime("%Y-%m-%d")

    today = pd.Timestamp(as_of_today) if as_of_today is not None else pd.Timestamp.today().normalize()
    age = (today - daily.index.max()).days
    report.stats["daily_age_days"] = int(age)
    if age > 7:
        report.warnings.append(f"newest share price is {age} calendar days old")

    monthly = snap.monthly
    report.stats["n_monthly"] = int(len(monthly))
    report.stats["monthly_first"] = str(monthly["month"].iloc[0])
    report.stats["monthly_last"] = str(monthly["month"].iloc[-1])
    # Reconcile overlapping months from 2003-07 onward.
    max_abs = {}
    n_cmp = 0
    worst = 0.0
    long_name = {"G": "G Fund", "F": "F Fund", "C": "C Fund", "S": "S Fund", "I": "I Fund"}
    official_df = monthly.set_index("month")
    for fund in core:
        calc = month_end_return_pct(daily, fund)
        joined = pd.DataFrame({"calc": calc, "off": pd.to_numeric(official_df[long_name[fund]], errors="coerce")})
        # Official monthly returns are bundled only through September 2026.
        # Daily data can extend later, but it must not be compared to an
        # unbundled (or synthetic future) monthly observation.
        joined = joined.loc[(joined.index >= "2003-07") & (joined.index <= "2026-09")].dropna()
        n_cmp = int(len(joined))
        diff = (joined["calc"] - joined["off"]).abs()
        max_abs[fund] = float(diff.max()) if len(diff) else None
        if len(diff):
            worst = max(worst, float(diff.max()))
            if float(diff.max()) > 0.01:
                report.errors.append(f"{fund} daily-to-monthly gap {float(diff.max()):.4f} pp exceeds 0.01")
    report.stats["recon_months"] = n_cmp
    report.stats["recon_max_abs_pp"] = max_abs
    report.stats["recon_worst_pp"] = worst

    annual = snap.annual
    y2026 = annual.loc[annual["year"].astype(int) == 2026]
    if y2026.empty or not bool(y2026["is_partial_year"].iloc[0] in (True, "True", "true", 1)):
        # bundled snapshot flags 2026 partial; a later full year may be False
        if not y2026.empty and str(y2026["period_end_yyyymm"].iloc[0]).endswith("12"):
            report.notes.append("2026 annual row covers a full year")
        elif y2026.empty:
            report.warnings.append("no 2026 annual row")
        else:
            if str(y2026["is_partial_year"].iloc[0]) not in ("True", "true", "1"):
                report.warnings.append("2026 annual row is not flagged partial")
    report.stats["n_annual"] = int(len(annual))

    # BLS gaps
    bls = snap.bls.copy()
    for col in ("cpi_u_sa", "unemployment_rate_sa"):
        bls[col] = pd.to_numeric(bls[col], errors="coerce")
    missing_cpi = bls.loc[bls["cpi_u_sa"].isna(), "month"].astype(str).tolist()
    missing_un = bls.loc[bls["unemployment_rate_sa"].isna(), "month"].astype(str).tolist()
    if "2025-10" in set(missing_cpi) or "2025-10" in set(bls["month"].astype(str)):
        report.notes.append(
            "BLS CPI-U and unemployment for 2025-10 are missing (shutdown). "
            f"CPI missing months: {missing_cpi}. Unemployment missing months: {missing_un}."
        )
    report.stats["bls_cpi_missing"] = missing_cpi
    report.stats["bls_unemp_missing"] = missing_un

    events = snap.events
    if events["event_id"].duplicated().any():
        report.errors.append("duplicate event ids")
    if events["source_url"].isna().any() or not events["source_url"].astype(str).str.startswith("https://").all():
        report.errors.append("every event needs an https source_url")
    report.stats["n_events"] = int(len(events))

    report.ok = not report.errors
    return report


def core_prices(snap: Snapshot) -> pd.DataFrame:
    return snap.daily[["G", "F", "C", "S", "I"]].copy()
