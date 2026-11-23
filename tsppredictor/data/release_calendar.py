"""Actual BLS publication dates for the macro series the features use.

The bundled ``bls_release_calendar.csv`` lists the real release date of every
archived CPI and Employment Situation news release (BLS archive pages, CPI
from May 1999 and jobs from 1995).  For months outside that range, or months
whose release is missing, an offline fallback is used that is *conservative*
(never earlier than BLS has published in normal operation), so a backtest
cannot see data before it was public.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tsppredictor.paths import repo_root, snapshot_dir

CALENDAR_FILE = "macro/primary/bls_release_calendar.csv"
SERIES_ALIASES = {
    "cpi": "bls_cpi",
    "bls_cpi": "bls_cpi",
    "unemployment": "bls_employment_situation",
    "jobs": "bls_employment_situation",
    "empsit": "bls_employment_situation",
    "bls_employment_situation": "bls_employment_situation",
}
# Release dates that a shutdown pushed far outside the normal window are kept
# in the calendar (they are real) but excluded when deriving the fallback day.
SHUTDOWN_MONTHS = frozenset({"2013-09", "2013-10", "2018-12", "2019-01", "2025-09", "2025-10", "2025-11"})


@dataclass(frozen=True)
class Release:
    series: str
    reference_month: str
    release_date: date
    source: str  # "calendar", "calendar-next-release", "fallback", or a schedule source
    url: str | None = None


def canonical_series(series: str) -> str:
    try:
        return SERIES_ALIASES[series.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown release series {series!r}") from exc


def _month(value: str) -> str:
    return str(pd.Period(str(value)[:7], freq="M"))


@lru_cache(maxsize=8)
def _load(path_str: str) -> dict[str, dict[str, tuple[date, str]]]:
    table: dict[str, dict[str, tuple[date, str]]] = {}
    path = Path(path_str)
    if not path.exists():
        return table
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            table.setdefault(row["series"], {})[row["reference_month"]] = (
                date.fromisoformat(row["release_date"]),
                row.get("source_url") or "",
            )
    return table


def calendar_table(path: Path | None = None) -> dict[str, dict[str, tuple[date, str]]]:
    return _load(str(path or (snapshot_dir() / CALENDAR_FILE)))


def fallback_day(series: str, path: Path | None = None) -> int:
    """Latest day-of-month BLS used for a normal (non-shutdown) next-month release."""
    series = canonical_series(series)
    rows = calendar_table(path).get(series, {})
    days = []
    for month, (released, _url) in rows.items():
        if month in SHUTDOWN_MONTHS:
            continue
        period = pd.Period(month, freq="M") + 1
        if (released.year, released.month) == (period.year, period.month):
            days.append(released.day)
    if days:
        return max(days)
    return {"bls_cpi": 26, "bls_employment_situation": 19}[series]


def release(series: str, month: str, path: Path | None = None) -> Release:
    series = canonical_series(series)
    month = _month(month)
    rows = calendar_table(path).get(series, {})
    if month in rows:
        released, url = rows[month]
        return Release(series, month, released, "calendar", url or None)
    if rows:
        covered = sorted(rows)
        if covered[0] <= month <= covered[-1]:
            # Not published on its own (e.g. October 2025 CPI after the lapse in
            # appropriations): the value first became visible with the next release.
            later = next(m for m in covered if m > month)
            released, url = rows[later]
            return Release(series, month, released, "calendar-next-release", url or None)
    nxt = pd.Period(month, freq="M") + 1
    return Release(series, month, date(nxt.year, nxt.month, fallback_day(series, path)), "fallback")


def release_date(series: str, month: str, path: Path | None = None) -> date:
    """Actual publication date for ``series`` reference ``month`` (YYYY-MM)."""
    return release(series, month, path).release_date


def releases_between(start: date, end: date, series: tuple[str, ...] = ("bls_cpi", "bls_employment_situation"),
                     path: Path | None = None) -> list[Release]:
    """Calendar releases whose publication date falls in [start, end]."""
    out = []
    table = calendar_table(path)
    for name in series:
        name = canonical_series(name)
        for month, (released, url) in table.get(name, {}).items():
            if start <= released <= end:
                out.append(Release(name, month, released, "calendar", url or None))
    return sorted(out, key=lambda r: (r.release_date, r.series))


def coverage(path: Path | None = None) -> dict:
    table = calendar_table(path)
    return {
        series: {"first_month": min(rows), "last_month": max(rows), "releases": len(rows),
                 "fallback_day": fallback_day(series, path)}
        for series, rows in sorted(table.items()) if rows
    }


# --- BLS release calendar ICS (connector) ----------------------------------

ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
SCHEDULE_FILE = "bls_release_schedule.json"
MAX_ICS_BYTES = 2_000_000
_TITLE_SERIES = (
    (re.compile(r"consumer price index", re.I), "bls_cpi"),
    (re.compile(r"employment situation", re.I), "bls_employment_situation"),
)
_MONTH_IN_TITLE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", re.I
)


def parse_bls_ics(text: str) -> list[Release]:
    """Parse BLS's official schedule ICS into CPI / jobs releases.

    Summaries look like ``Consumer Price Index for October 2026``; DTSTART is the
    publication date.  Other BLS releases are ignored.
    """
    unfolded = re.sub(r"\n[ \t]", "", text.replace("\r\n", "\n")).strip()
    if not unfolded.startswith("BEGIN:VCALENDAR\n") or not unfolded.endswith("\nEND:VCALENDAR"):
        raise ValueError("Expected a complete VCALENDAR")
    blocks = re.findall(r"^BEGIN:VEVENT\n(.*?)^END:VEVENT$", unfolded, re.M | re.S)
    if len(blocks) != unfolded.splitlines().count("BEGIN:VEVENT") or len(blocks) != unfolded.splitlines().count("END:VEVENT"):
        raise ValueError("Incomplete calendar event")
    out: list[Release] = []
    for block in blocks:
        summary = re.search(r"^SUMMARY[^:]*:(.*)$", block, re.M)
        start = re.search(r"^DTSTART[^:]*:(\d{8})", block, re.M)
        if not summary or re.search(r"^STATUS:CANCELLED\s*$", block, re.M | re.I):
            continue
        title = summary.group(1).strip()
        series = next((name for pattern, name in _TITLE_SERIES if pattern.search(title)), None)
        month = _MONTH_IN_TITLE.search(title)
        if series is None or month is None:
            continue
        if not start:
            raise ValueError(f"Missing/invalid date for {series} event")
        reference = datetime.strptime(f"{month.group(1).title()} {month.group(2)}", "%B %Y").strftime("%Y-%m")
        out.append(Release(series, reference, datetime.strptime(start.group(1), "%Y%m%d").date(), "ics"))
    return out


def _schedule_path() -> Path:
    # Reading the optional schedule must not create directories or touch the snapshot.
    return repo_root() / "data" / "cache" / SCHEDULE_FILE


def _eastern_today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _future_schedule(text: str, as_of: date, path: Path | None = None) -> dict[tuple[str, str], Release]:
    size = len(text.encode("utf-8"))
    if not 0 < size <= MAX_ICS_BYTES:
        raise ValueError("Calendar size outside supported limits")
    baseline = calendar_table(path)
    parsed = parse_bls_ics(text)
    if not parsed:
        raise ValueError("Calendar contains no recognized CPI or employment releases")
    out: dict[tuple[str, str], Release] = {}
    for row in parsed:
        bundled = baseline.get(row.series, {}).get(row.reference_month)
        # A refreshed schedule can revise a still-upcoming bundled date for display,
        # but can never override a date already reached or change archived history.
        if row.release_date < as_of or (bundled and bundled[0] <= as_of):
            continue
        ref = date.fromisoformat(f"{row.reference_month}-01")
        if (row.release_date.year, row.release_date.month) <= (ref.year, ref.month):
            raise ValueError(f"Scheduled release must follow the reference month: {row.series} {row.reference_month}")
        if row.release_date > as_of + timedelta(days=550):
            raise ValueError(f"Release lies beyond the 550-day schedule horizon: {row.series} {row.reference_month}")
        key = (row.series, row.reference_month)
        if key in out and out[key] != row:
            raise ValueError(f"Conflicting dates for {row.series} {row.reference_month}")
        out[key] = row
    if not out:
        raise ValueError("Calendar has no eligible upcoming CPI or employment releases")
    return out


def cache_schedule(text: str, *, source: str, today: date | None = None) -> dict:
    """Atomically replace display-only BLS schedule; never write historical inputs."""
    if source not in ("local-ics", ICS_URL):
        raise ValueError("Unrecognized schedule source")
    today = today or _eastern_today()
    upcoming_rows = _future_schedule(text, today)
    path = _schedule_path()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = {"schema_version": 1, "source": source, "as_of": today.isoformat(), "sha256": digest, "ics": text}
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            staging = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)
    return {"scheduled": len(upcoming_rows), "source": source, "as_of": today.isoformat(),
            "sha256": digest, "path": str(path), "display_only": True}


def upcoming_display(today: date | None = None, days: int = 14) -> tuple[list[Release], dict]:
    """Read the unverified-for-model-use schedule for CLI alerts only."""
    today = today or _eastern_today()
    end = today + timedelta(days=days)
    rows = {(r.series, r.reference_month): r for r in releases_between(today, end)}
    path = _schedule_path()
    try:
        with path.open("rb") as handle:
            content = handle.read(6 * MAX_ICS_BYTES + 4096)
        payload = json.loads(content)
        as_of = date.fromisoformat(payload["as_of"])
        source = payload["source"]
        text = payload["ics"]
        if (payload["schema_version"] != 1 or as_of > today or source not in ("local-ics", ICS_URL)
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != payload["sha256"]):
            raise ValueError("Invalid schedule metadata")
        schedule = _future_schedule(text, as_of)
    except FileNotFoundError:
        return list(rows.values()), {"state": "missing"}
    except (ValueError, TypeError, AttributeError, KeyError, OSError):
        return list(rows.values()), {"state": "invalid"}
    for key, release_row in schedule.items():
        rows.pop(key, None)
        if today <= release_row.release_date <= end:
            rows[key] = Release(*key, release_row.release_date, "local-ics" if source == "local-ics" else "bls-ics",
                                None if source == "local-ics" else ICS_URL)
    return sorted(rows.values(), key=lambda r: (r.release_date, r.series)), {
        "state": "loaded", "as_of": as_of.isoformat(), "source": source, "sha256": payload["sha256"],
        "display_only": True,
    }


def fetch_ics(timeout: float = 20.0, session=None) -> str:
    """Download the BLS schedule ICS. Network use is explicit (``tsp update --release-calendar``).

    BLS refuses scripted requests that do not identify a contact; set
    ``TSP_CONTACT_EMAIL`` to put one in the User-Agent, or download the ICS in a
    browser and pass it with ``--ics-file``.
    """
    import requests

    contact = os.environ.get("TSP_CONTACT_EMAIL", "").strip()
    agent = "TSP Predictor (educational, local)" + (f" {contact}" if contact else "")
    http = session or requests
    response = http.get(ICS_URL, timeout=timeout, headers={"User-Agent": agent, "Accept": "text/calendar"},
                        allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise RuntimeError("BLS schedule endpoint did not return HTTP 200; redirects are not followed")
    text = response.text
    if "BEGIN:VCALENDAR" not in text:
        raise RuntimeError("BLS did not return a calendar (often a 403 page); set TSP_CONTACT_EMAIL or use --ics-file")
    return text


def upcoming(today: date | None = None, days: int = 14, path: Path | None = None) -> list[Release]:
    today = today or date.today()
    return releases_between(today, today + timedelta(days=days), path=path)
