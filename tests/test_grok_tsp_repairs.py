"""Regression checks for isolated schedule refresh and the personal posting diary."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from tsppredictor.cli import app
from tsppredictor.data import release_calendar as rc
from tsppredictor.data import snapshot
from tsppredictor.journal_insights import allocation_drift, ift_month_summary, read_ift_diary, record_ift
from tsppredictor.paths import snapshot_dir

AS_OF = date(2026, 11, 23)
RUNNER = CliRunner()


def _ics(*events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
    for title, day in events:
        lines += ["BEGIN:VEVENT", f"SUMMARY:{title}", f"DTSTART;VALUE=DATE:{day}", "END:VEVENT"]
    return ("\r\n".join([*lines, "END:VCALENDAR", ""])).encode("utf-8")


@pytest.fixture
def isolated_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_eastern_today", lambda: AS_OF)
    monkeypatch.setattr(rc, "repo_root", lambda: tmp_path)
    return tmp_path / "data" / "cache" / rc.SCHEDULE_FILE


def _deny_network(*args, **kwargs):
    pytest.fail("An offline schedule operation attempted network access")


def test_cli_schedule_refresh_never_mutates_model_snapshot(tmp_path, isolated_schedule, monkeypatch):
    from tsppredictor.data import ingest_tsp

    monkeypatch.setattr(ingest_tsp, "update_tsp", _deny_network)
    monkeypatch.setattr(rc, "fetch_ics", _deny_network)
    root = snapshot_dir()
    historical = root / rc.CALENDAR_FILE
    manifest = root / "MANIFEST.csv"
    before = (historical.read_bytes(), manifest.read_bytes())

    ics = tmp_path / "input.ics"
    cpi = "Consumer Price Index for November 2026"
    jobs = "Employment Situation for November 2026"
    earlier = "Consumer Price Index for October 2026"
    payload = _ics((cpi, "20261210"), (cpi, "20261210"), (jobs, "20261208"), (earlier, "20261209"))
    ics.write_bytes(payload)
    result = RUNNER.invoke(app, ["update", "--ics-file", str(ics)])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout)
    assert receipt["display_only"] and receipt["scheduled"] == 2
    assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(isolated_schedule.read_text())["source"] == "local-ics"
    rendered = RUNNER.invoke(app, ["releases", "--days", "30"])
    assert rendered.exit_code == 0, rendered.output
    rows = json.loads(rendered.stdout)["upcoming"]
    assert ("2026-11", "2026-12-10", "local-ics") in [(r["month"], r["date"], r["source"]) for r in rows]
    assert all(r["month"] != "2026-10" for r in rows)
    assert [r["date"] for r in rows if r["series"] == "bls_employment_situation"] == ["2026-12-08"]

    ics.write_bytes(_ics((cpi, "20261215"), (jobs, "20261208")))
    result = RUNNER.invoke(app, ["update", "--skip-tsp", "--ics-file", str(ics)])
    assert result.exit_code == 0, result.output
    display, _ = rc.upcoming_display(days=30)
    assert [r.release_date.isoformat() for r in display if r.series == "bls_cpi"] == ["2026-12-15"]
    # The immutable/model-facing calendar still has the bundled jobs date,
    # and the published October CPI remains unchanged.
    assert rc.release_date("jobs", "2026-11") == date(2026, 12, 4)
    assert rc.release_date("cpi", "2026-10") == date(2026, 11, 10)
    assert (historical.read_bytes(), manifest.read_bytes()) == before
    assert not snapshot.load_snapshot(root).daily.empty


@pytest.mark.parametrize("kind", ["malformed", "conflicting", "write_failure"])
def test_failed_schedule_update_keeps_last_good_cache(tmp_path, isolated_schedule, monkeypatch, kind):
    title = "Consumer Price Index for November 2026"
    old = _ics((title, "20261210"))
    rc.cache_schedule(old.decode(), source="local-ics")
    before = isolated_schedule.read_bytes()
    ics = tmp_path / "input.ics"
    if kind == "malformed":
        ics.write_bytes(b"BEGIN:VCALENDAR\n")
    elif kind == "conflicting":
        ics.write_bytes(_ics((title, "20261211"), (title, "20261212")))
    else:
        ics.write_bytes(_ics((title, "20261211")))

        def fail_replace(*_args):
            raise OSError("Synthetic atomic rename failure")

        monkeypatch.setattr(rc.os, "replace", fail_replace)
    result = RUNNER.invoke(app, ["update", "--ics-file", str(ics)])
    assert result.exit_code == 1, result.output
    assert "previous schedule retained" in result.output
    assert isolated_schedule.read_bytes() == before
    assert list(isolated_schedule.parent.iterdir()) == [isolated_schedule]


def test_corrupt_cache_falls_back_and_excludes_local_rows(isolated_schedule):
    text = _ics(("Consumer Price Index for November 2026", "20261210")).decode()
    rc.cache_schedule(text, source="local-ics")
    content = json.loads(isolated_schedule.read_text())
    content["ics"] = content["ics"].replace("20261210", "20261211")
    isolated_schedule.write_text(json.dumps(content))
    rows, status = rc.upcoming_display(days=30)
    assert status["state"] == "invalid"
    assert rows and all(r.source == "calendar" for r in rows)


def _log(tmp_path, day, *, g_only=False):
    return record_ift(tmp_path, when=date.fromisoformat(day), from_mix="personal input", to_mix="personal input",
                      reason="test", g_only=g_only)


def test_first_two_postings_count_even_if_first_g_only(tmp_path):
    assert _log(tmp_path, "2024-03-04", g_only=True)["unrestricted_number"] == 1
    assert _log(tmp_path, "2024-03-11")["unrestricted_number"] == 2
    with pytest.raises(ValueError, match="two unrestricted"):
        _log(tmp_path, "2024-03-18")
    assert _log(tmp_path, "2024-03-18", g_only=True)["unrestricted_number"] is None
    assert _log(tmp_path, "2024-04-01", g_only=True)["unrestricted_number"] == 1
    summary = ift_month_summary(tmp_path, "2024-03")
    assert summary["unrestricted_left"] == 0 and summary["over_limit_logged"] == 0
    assert [r["status"] for r in summary["transfers"]] == ["unrestricted", "unrestricted", "g_only"]


def test_backdated_entry_cannot_invalidate_a_later_logged_posting(tmp_path):
    _log(tmp_path, "2024-03-11", g_only=True)
    _log(tmp_path, "2024-03-18")
    before = read_ift_diary(tmp_path)
    with pytest.raises(ValueError, match="Backdated"):
        _log(tmp_path, "2024-03-04", g_only=True)
    assert read_ift_diary(tmp_path) == before


def test_legacy_entries_reclassify_chronologically_without_rewriting(tmp_path):
    old = [
        {"date": "2024-03-18", "month": "2024-03", "g_only": False, "unrestricted_number": 2},
        {"date": "2024-03-11", "month": "2024-03", "g_only": False, "unrestricted_number": 1},
        {"date": "2024-03-04", "month": "2024-03", "g_only": True, "unrestricted_number": None},
    ]
    source = tmp_path / "ift_diary.jsonl"
    original = "\n".join(map(json.dumps, old))
    source.write_text(original)
    summary = ift_month_summary(tmp_path, "2024-03")
    assert summary["unrestricted_left"] == 0 and summary["over_limit_logged"] == 1
    assert [r["unrestricted_number"] for r in summary["transfers"]] == [1, 2, None]
    assert source.read_text() == original


def test_post_day_is_still_in_old_drift_segment():
    dates = pd.bdate_range("2024-01-04", periods=4)
    weights = np.array([[0.8, 0.2], [0.75, 0.25], [0.3, 0.7], [0.35, 0.65]])
    # Friday's close resets holdings for Monday's first session with the new mix.
    drift = allocation_drift(weights, dates, [dates[1], dates[3]], funds=("G", "C"))
    older, newer = drift["segments"]
    assert (older["from"], older["to"]) == ("2024-01-04", "2024-01-05")
    assert (newer["from"], newer["to"]) == ("2024-01-08", "2024-01-09")
    assert newer["start_mix"] == {"G": 0.3, "C": 0.7}
    assert drift["max_drift_any_fund"] == 0.05
