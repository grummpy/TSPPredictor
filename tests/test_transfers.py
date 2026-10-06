"""Tests 1–7: noon cutoff, posting month, transfer limit, TSP calendar."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from tsppredictor.calendar import project_tsp_days, projected_holidays
from tsppredictor.rules.ift import TransferBook, as_weights

ET = ZoneInfo("America/New_York")


@pytest.mark.parametrize("bad", [-0.1, np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("as_dict", [False, True])
def test_invalid_allocation_components_are_rejected(bad, as_dict):
    target = {"G": 1.0, "C": bad} if as_dict else [1.0, 0.0, bad, 0.0, 0.0]
    with pytest.raises(ValueError, match="finite and non-negative"):
        as_weights(target)


def test_valid_allocation_weights_are_normalized():
    expected = [0.5, 0.0, 0.5, 0.0, 0.0]
    assert np.allclose(as_weights({"G": 50, "C": 50}), expected)
    assert np.allclose(as_weights([50, 0, 50, 0, 0]), expected)


def test_projected_new_year_observation_crosses_year_boundary():
    assert date(2027, 12, 31) in projected_holidays(2027)
    assert project_tsp_days(date(2027, 12, 30), date(2028, 1, 3)) == [
        date(2027, 12, 30),
        date(2028, 1, 3),
    ]


def test_projected_new_year_sunday_observation():
    assert project_tsp_days(date(2022, 12, 30), date(2023, 1, 3)) == [
        date(2022, 12, 30),
        date(2023, 1, 3),
    ]


def et(year, month, day, hour, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=ET)


def test_01_noon_cutoff(tsp_calendar):
    assert tsp_calendar.posting_date(et(2026, 9, 15, 11, 59)) == date(2026, 9, 15)
    assert tsp_calendar.posting_date(et(2026, 9, 15, 12, 0)) == date(2026, 9, 16)


def test_02_weekend_posts_monday(tsp_calendar):
    assert tsp_calendar.posting_date(et(2026, 2, 28, 10, 0)) == date(2026, 3, 2)


def test_03_columbus_day(tsp_calendar):
    assert tsp_calendar.is_business_day(date(2024, 10, 14)) is False
    assert tsp_calendar.posting_date(et(2024, 10, 14, 9, 0)) == date(2024, 10, 15)


def test_04_month_end_trap_counts_october(tsp_calendar):
    posted = tsp_calendar.posting_date(et(2026, 9, 30, 13, 0))
    assert posted == date(2026, 10, 1)
    book = TransferBook(tsp_calendar)
    book.set_initial("civilian", "G")
    result = book.request("civilian", et(2026, 9, 30, 13, 0), "C")
    assert result.accepted
    assert result.month == "2026-10"
    assert result.posting_date == date(2026, 10, 1)


def test_05_two_then_g_only(tsp_calendar):
    book = TransferBook(tsp_calendar)
    book.set_initial("civilian", "C")
    first = book.request("civilian", et(2026, 9, 1, 10, 0), "S")
    second = book.request("civilian", et(2026, 9, 2, 10, 0), "I")
    third = book.request("civilian", et(2026, 9, 3, 10, 0), "C")
    into_g = book.request("civilian", et(2026, 9, 4, 10, 0), "G")
    back = book.request("civilian", et(2026, 9, 8, 10, 0), "C")
    nxt = book.request("civilian", et(2026, 10, 1, 10, 0), "C")
    assert first.accepted and first.counted_as_unrestricted
    assert second.accepted and second.counted_as_unrestricted
    assert third.accepted is False
    assert into_g.accepted and into_g.g_only_after_limit
    assert into_g.counted_as_unrestricted is False
    assert back.accepted is False
    assert nxt.accepted and nxt.month == "2026-10" and nxt.counted_as_unrestricted


def test_06_accounts_are_independent(tsp_calendar):
    book = TransferBook(tsp_calendar)
    book.set_initial("civilian", "G")
    book.set_initial("uniformed", "G")
    book.request("civilian", et(2026, 9, 1, 10, 0), "C")
    book.request("civilian", et(2026, 9, 2, 10, 0), "S")
    blocked = book.request("civilian", et(2026, 9, 3, 10, 0), "I")
    allowed = book.request("uniformed", et(2026, 9, 3, 10, 0), "C")
    assert blocked.accepted is False
    assert allowed.accepted and allowed.unrestricted_used == 1


def test_07_business_days_from_the_price_file(tsp_calendar):
    assert tsp_calendar.is_business_day(date(2023, 10, 9)) is False
    assert tsp_calendar.is_business_day(date(2023, 11, 10)) is True
    assert tsp_calendar.is_business_day(date(2024, 11, 11)) is False
    assert tsp_calendar.is_business_day(date(2025, 1, 9)) is False
    assert tsp_calendar.is_business_day(date(2024, 7, 5)) is True
