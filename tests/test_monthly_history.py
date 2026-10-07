import pandas as pd
import pytest

from tsppredictor.monthly_history import build_monthly_history, compound_monthly_returns

FUNDS = (("G", "G Fund", "G Fund"), ("S", "S Fund", "S Fund"))


def test_history_uses_trailing_completed_months_in_ascending_order():
    monthly = pd.DataFrame(
        {
            "month": ["2026-04", "2026-02", "2025-12", "2026-03", "2026-01"],
            "G Fund": [99.0, 2.0, 0.5, 3.0, 1.0],
            "S Fund": [9.0, 0.2, -1.0, 0.3, 0.1],
        }
    )

    payload = build_monthly_history(monthly, "2026-04-14", months=3, funds=FUNDS)

    assert payload["months"] == ["2026-01", "2026-02", "2026-03"]
    assert payload["window_start"] == "2026-01"
    assert payload["window_end"] == "2026-03"
    assert payload["monthly_returns_through"] == "2026-03"
    assert payload["funds"]["G"]["label"] == "G Fund"
    assert payload["funds"]["G"]["return_pct"] == [1.0, 2.0, 3.0]
    for fund in payload["funds"].values():
        assert len(fund["return_pct"]) == len(payload["months"])
        assert len(fund["cumulative_wealth"]) == len(payload["months"])


def test_history_compounds_returns_and_does_not_bridge_missing_values():
    monthly = pd.DataFrame(
        {
            "month": ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"],
            "G Fund": [10.0, -5.0, None, 3.0, 4.0],
            "S Fund": [None, None, 2.0, 3.0, 4.0],
        }
    )

    payload = build_monthly_history(monthly, "2026-06-01", months=5, funds=FUNDS)

    g = payload["funds"]["G"]
    assert g["cumulative_wealth"] == pytest.approx([1.1, 1.045, None, None, None], nan_ok=True)
    assert g["missing_after_start"] == ["2026-03"]
    assert g["compounded_return_pct"] is None

    s = payload["funds"]["S"]
    assert s["first_available_in_window"] == "2026-03"
    assert s["cumulative_wealth"] == pytest.approx([None, None, 1.02, 1.0506, 1.092624], nan_ok=True)
    assert s["compounded_return_pct"] == pytest.approx(9.2624)


def test_history_keeps_an_entirely_absent_csv_month_in_the_calendar_window():
    monthly = pd.DataFrame(
        {
            # 2025-12 would be included by tail(4); 2026-02 is absent entirely.
            "month": ["2025-12", "2026-01", "2026-03", "2026-04", "2026-05"],
            "G Fund": [0.5, 1.0, 3.0, 4.0, 99.0],
            "S Fund": [-1.0, 0.1, 0.3, 0.4, 9.0],
        }
    )

    payload = build_monthly_history(monthly, "2026-05-12", months=4, funds=FUNDS)

    assert payload["months"] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert payload["window_start"] == "2026-01"
    assert payload["window_end"] == "2026-04"
    assert payload["monthly_returns_through"] == "2026-04"
    assert payload["funds"]["G"]["return_pct"] == [1.0, None, 3.0, 4.0]
    assert payload["funds"]["G"]["missing_after_start"] == ["2026-02"]
    assert payload["funds"]["G"]["cumulative_wealth"] == pytest.approx([1.01, None, None, None], nan_ok=True)


def test_compounding_preserves_leading_missing_values_and_rejects_invalid_window():
    assert compound_monthly_returns([None, 1.0, 2.0]) == pytest.approx([None, 1.01, 1.0302], nan_ok=True)
    monthly = pd.DataFrame({"month": ["2026-01"], "G Fund": [1.0], "S Fund": [1.0]})
    with pytest.raises(ValueError, match="at least one"):
        build_monthly_history(monthly, "2026-02-01", months=0, funds=FUNDS)
