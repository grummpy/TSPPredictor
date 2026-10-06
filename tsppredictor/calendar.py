"""TSP business-day calendar.

Historical dates come only from the share-price file. The TSP is closed on days
that file omits, including Columbus Day and Veterans Day, and it is also closed
on some NYSE-only closures. Dates after the last share price use a projected
calendar: weekends off, NYSE holidays off, plus federal Columbus Day and
Veterans Day. Projected dates are labeled as projected.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth weekday of a month. weekday: Monday=0. n is 1-based."""
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= timedelta(days=1)
    return cursor


def _easter(year: int) -> date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


_HOLIDAY_CACHE: dict[int, set[date]] = {}


def projected_holidays(year: int) -> set[date]:
    """NYSE holidays plus Columbus Day and Veterans Day, for a future year."""
    cached = _HOLIDAY_CACHE.get(year)
    if cached is not None:
        return cached
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # MLK
        _nth_weekday(year, 2, 0, 3),  # Washington's birthday
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day (TSP, not NYSE)
        _observed(date(year, 11, 11)),  # Veterans Day (TSP, not NYSE)
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    # Next year's Saturday New Year's Day is observed in this year.
    if date(year + 1, 1, 1).weekday() == 5:
        holidays.add(date(year, 12, 31))
    _HOLIDAY_CACHE[year] = holidays
    return holidays


def project_tsp_days(start: date, end: date) -> list[date]:
    """Weekdays from start through end that are not projected holidays."""
    if end < start:
        return []
    by_year: dict[int, set[date]] = {}
    out: list[date] = []
    cursor = start
    while cursor <= end:
        year = cursor.year
        if year not in by_year:
            by_year[year] = projected_holidays(year)
        if cursor.weekday() < 5 and cursor not in by_year[year]:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def scheduled_next_business_day(d: date) -> date:
    """Next projected business day strictly after d. Used for calendar features."""
    cursor = d + timedelta(days=1)
    for _ in range(14):
        holidays = projected_holidays(cursor.year)
        if cursor.weekday() < 5 and cursor not in holidays:
            return cursor
        cursor += timedelta(days=1)
    return cursor


def is_scheduled_month_end(d: date) -> bool:
    nxt = scheduled_next_business_day(d)
    return (nxt.year, nxt.month) != (d.year, d.month)


def is_scheduled_pre_holiday(d: date) -> bool:
    """True when the next scheduled session skips a weekday (a holiday gap)."""
    nxt = scheduled_next_business_day(d)
    gap = (nxt - d).days
    if gap <= 1:
        return False
    # A normal weekend is Friday -> Monday (3 days) with no weekday holiday.
    if d.weekday() == 4 and gap == 3:
        return False
    return True


class TSPCalendar:
    def __init__(self, observed: list[date] | pd.DatetimeIndex, project_years: int = 2):
        days: list[date] = []
        for value in observed:
            if isinstance(value, datetime):
                days.append(value.date())
            elif isinstance(value, pd.Timestamp):
                days.append(value.date())
            elif isinstance(value, date):
                days.append(value)
            else:
                days.append(pd.Timestamp(value).date())
        self.observed = sorted(set(days))
        if not self.observed:
            raise ValueError("TSP calendar needs at least one share-price date")
        self.observed_set = set(self.observed)
        self.first = self.observed[0]
        self.last = self.observed[-1]
        end = date(self.last.year + project_years, 12, 31)
        self.projected = project_tsp_days(self.last + timedelta(days=1), end)
        self.projected_set = set(self.projected)
        self.all_dates = self.observed + self.projected
        self._index = {d: i for i, d in enumerate(self.all_dates)}

    def is_business_day(self, d: date) -> bool:
        if isinstance(d, datetime):
            d = d.date()
        elif isinstance(d, pd.Timestamp):
            d = d.date()
        if d < self.first:
            return False
        if d <= self.last:
            return d in self.observed_set
        return d in self.projected_set

    def is_projected(self, d: date) -> bool:
        if isinstance(d, datetime):
            d = d.date()
        return d in self.projected_set

    def next_business_day(self, d: date) -> date:
        if isinstance(d, datetime):
            d = d.date()
        elif isinstance(d, pd.Timestamp):
            d = d.date()
        pos = bisect.bisect_right(self.all_dates, d)
        if pos >= len(self.all_dates):
            extra = project_tsp_days(self.all_dates[-1] + timedelta(days=1), d + timedelta(days=400))
            self.projected.extend(extra)
            self.projected_set.update(extra)
            self.all_dates.extend(extra)
            pos = bisect.bisect_right(self.all_dates, d)
        return self.all_dates[pos]

    def previous_business_day(self, d: date) -> date | None:
        if isinstance(d, pd.Timestamp):
            d = d.date()
        pos = bisect.bisect_left(self.all_dates, d) - 1
        if pos < 0:
            return None
        return self.all_dates[pos]

    def posting_date(self, request_dt: datetime) -> date:
        """Posting date under the noon-ET cutoff.

        Before noon ET on a TSP business day, the request posts that day.
        At or after noon, or on a non-business day, it posts the next business day.
        """
        if request_dt.tzinfo is None:
            aware = request_dt.replace(tzinfo=ET)
        else:
            aware = request_dt.astimezone(ET)
        day = aware.date()
        at_or_after_noon = (aware.hour, aware.minute, aware.second, aware.microsecond) >= (12, 0, 0, 0)
        if self.is_business_day(day) and not at_or_after_noon:
            return day
        return self.next_business_day(day)

    def last_business_day_of_month(self, year: int, month: int) -> date:
        if month == 12:
            probe = date(year + 1, 1, 1)
        else:
            probe = date(year, month + 1, 1)
        return self.previous_business_day(probe)  # type: ignore[return-value]

    def is_month_end_trap(self, request_dt: datetime) -> bool:
        """After noon on the last business day, the post falls in the next month."""
        if request_dt.tzinfo is None:
            aware = request_dt.replace(tzinfo=ET)
        else:
            aware = request_dt.astimezone(ET)
        day = aware.date()
        if not self.is_business_day(day):
            return False
        last = self.last_business_day_of_month(day.year, day.month)
        if day != last:
            return False
        posted = self.posting_date(request_dt)
        return (posted.year, posted.month) != (day.year, day.month)

    def loc(self, d: date) -> int:
        if isinstance(d, pd.Timestamp):
            d = d.date()
        return self._index[d]
