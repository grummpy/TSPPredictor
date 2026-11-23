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
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from tsppredictor.paths import snapshot_dir

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
    source: str  # "calendar", "calendar-next-release", "fallback", "ics"
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
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    out: list[Release] = []
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        summary = re.search(r"^SUMMARY[^:]*:(.*)$", block, re.M)
        start = re.search(r"^DTSTART[^:]*:(\d{8})", block, re.M)
        if not summary or not start:
            continue
        title = summary.group(1).strip()
        series = next((name for pattern, name in _TITLE_SERIES if pattern.search(title)), None)
        month = _MONTH_IN_TITLE.search(title)
        if series is None or month is None:
            continue
        reference = datetime.strptime(f"{month.group(1).title()} {month.group(2)}", "%B %Y").strftime("%Y-%m")
        out.append(Release(series, reference, datetime.strptime(start.group(1), "%Y%m%d").date(), "ics", ICS_URL))
    return out


def merge_releases(path: Path, releases: list[Release]) -> dict:
    """Add ICS releases that are not yet in the calendar file (never rewrites history)."""
    table = {s: dict(rows) for s, rows in calendar_table(path).items()}
    added = 0
    for item in releases:
        rows = table.setdefault(item.series, {})
        if item.reference_month not in rows:
            rows[item.reference_month] = (item.release_date, item.url or "")
            added += 1
    if added:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["series", "reference_month", "release_date", "source_url"])
            for series in sorted(table):
                for month in sorted(table[series]):
                    released, url = table[series][month]
                    writer.writerow([series, month, released.isoformat(), url])
        _load.cache_clear()
    return {"added": added, "path": str(path)}


def fetch_ics(timeout: float = 20.0, session=None) -> str:
    """Download the BLS schedule ICS. Network use is explicit (``tsp update --release-calendar``).

    BLS refuses scripted requests that do not identify a contact; set
    ``TSP_CONTACT_EMAIL`` to put one in the User-Agent, or download the ICS in a
    browser and pass it with ``--ics-file``.
    """
    import os

    import requests

    contact = os.environ.get("TSP_CONTACT_EMAIL", "").strip()
    agent = "TSP Predictor (educational, local)" + (f" {contact}" if contact else "")
    http = session or requests
    response = http.get(ICS_URL, timeout=timeout, headers={"User-Agent": agent, "Accept": "text/calendar"})
    response.raise_for_status()
    text = response.text
    if "BEGIN:VCALENDAR" not in text:
        raise RuntimeError("BLS did not return a calendar (often a 403 page); set TSP_CONTACT_EMAIL or use --ics-file")
    return text


def upcoming(today: date | None = None, days: int = 14, path: Path | None = None) -> list[Release]:
    today = today or date.today()
    return releases_between(today, today + timedelta(days=days), path=path)
