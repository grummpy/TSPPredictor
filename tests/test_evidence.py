"""Regression coverage for auditable macro-vintage and lag-sensitivity output."""

import pytest

from tsppredictor.evidence import lag_sensitivity, macro_vintage_metadata


def _row(strategy_id, cadence, horizon, lag, cagr, excess):
    return {
        "id": strategy_id,
        "name": strategy_id.title(),
        "cadence": cadence,
        "horizon": horizon,
        "lag": lag,
        "metrics": {"cagr": cagr},
        "versus": {"bh_c": {"excess_cagr": excess}},
    }


def test_macro_vintage_metadata_keeps_latest_revisions_and_assumptions_explicit():
    metadata = macro_vintage_metadata()
    assert metadata["kind"] == "macro_availability_and_vintage"
    assert metadata["first_print_vintages_available"] is False
    assert metadata["vintage_status"] == "latest_revision_only"
    assert {row["series"] for row in metadata["availability_rules"]} >= {
        "BLS CPI",
        "BLS unemployment",
        "Federal Reserve H.15",
    }
    # A caller cannot accidentally mutate the shared statement for another build.
    metadata["availability_rules"].clear()
    assert macro_vintage_metadata()["availability_rules"]


def test_lag_sensitivity_compares_only_matching_strategy_cadence_and_horizon():
    report = lag_sensitivity(
        [
            _row("ensemble", "daily", 21, 1, 0.10, 0.02),
            _row("ensemble", "daily", 21, 2, 0.08, 0.01),
            _row("ensemble", "daily", 63, 1, 0.11, 0.03),
            _row("ensemble", "monthly", 1, 1, 0.06, 0.01),
            _row("ensemble", "monthly", 1, 2, 0.05, -0.01),
        ]
    )
    daily = next(row for row in report["comparisons"] if row["cadence"] == "daily")
    assert daily["horizon"] == 21
    assert daily["reference_lag"] == 1
    assert daily["compared_lag"] == 2
    assert daily["cagr"]["difference"] == pytest.approx(-0.02)
    assert daily["excess_cagr_vs_bh_c"]["difference"] == pytest.approx(-0.01)
    assert report["unpaired"] == [{"id": "ensemble", "cadence": "daily", "horizon": 63, "available_lags": [1]}]
