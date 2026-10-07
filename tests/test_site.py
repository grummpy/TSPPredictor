"""Tests 25–28: build outputs, loopback bind, privacy, optional browser smoke."""

import json
import re
import threading
from pathlib import Path

import pytest

from tsppredictor.cli import BIND_HOST, make_server


@pytest.fixture(scope="session")
def built():
    from tsppredictor.build import run_build

    return run_build()


def test_25_build_outputs_and_no_remote_assets(built):
    dist = Path(built["dist"])
    html = (dist / "index.html").read_text()
    assert "TSP Predictor" in html
    assert "not financial advice" in html.lower() or "Not financial advice" in html or "not financial advice" in html
    for name in (
        "meta.json",
        "today.json",
        "scoreboard.json",
        "calibration.json",
        "history.json",
        "monthly-history.json",
        "trials.json",
        "features.json",
    ):
        payload = json.loads((dist / "data" / name).read_text())
        assert payload["schema_version"] == 1
        assert payload["data_as_of"]
    script = (dist / "app.js").read_text()
    style = (dist / "app.css").read_text()
    html_wo = re.sub(r'<a class="citation"[^>]*>.*?</a>', "", html, flags=re.S)
    assert "http://" not in html_wo and "https://" not in html_wo
    assert "http" not in script
    assert "http" not in style
    assert 'src="http' not in html
    vendor = (dist / "vendor" / "plotly.min.js").read_text()
    urls = set(re.findall(r"https?://[^\"'\s)\\]+", vendor))
    assert urls
    for url in urls:
        assert "w3.org" in url
    rows = json.loads((dist / "data" / "scoreboard.json").read_text())["rows"]
    kinds = {row["kind"] for row in rows}
    assert "baseline" in kinds and "rule" in kinds and "model" in kinds
    ids = {row["id"] for row in rows}
    for required in ("bh_c", "always_g", "static_60_40", "l2050", "logistic", "hgb", "ensemble"):
        assert required in ids
    rule_ids = {row["id"] for row in rows if row["kind"] == "rule"}
    assert len(rule_ids) >= 3
    daily_lags = {row["lag"] for row in rows if row["cadence"] == "daily" and row["kind"] == "model"}
    monthly_lags = {row["lag"] for row in rows if row["cadence"] == "monthly" and row["kind"] == "model"}
    assert {1, 2} <= daily_lags
    assert {1, 2} <= monthly_lags
    for row in rows:
        for comparison in row["versus"].values():
            assert comparison["verdict"] in {"Beat", "Inconclusive", "Underperformed"}
            assert len(comparison["ci90"]) == 2

    curves = json.loads((dist / "data" / "curves.json").read_text())
    for key in ("daily-lag-1", "daily-lag-2", "monthly-lag-1", "monthly-lag-2"):
        assert curves["views"][key]["series"]
    monthly_history = json.loads((dist / "data" / "monthly-history.json").read_text())
    assert monthly_history["kind"] == "official_monthly_returns"
    assert monthly_history["completed_month_count"] == 120
    assert monthly_history["months"] == sorted(monthly_history["months"])
    assert monthly_history["window_end"] < monthly_history["data_as_of"][:7]
    for fund in monthly_history["funds"].values():
        assert len(fund["return_pct"]) == 120
        assert len(fund["cumulative_wealth"]) == 120
    c_history = monthly_history["funds"]["C"]
    assert c_history["cumulative_wealth"][0] == pytest.approx(1 + c_history["return_pct"][0] / 100)
    assert "monthly-history.json" in script
    assert "payload.views" in script
    assert "drawCurves(curvesPayload, cadence, lag)" in script
    assert 'id="monthly-history-start"' in html


def test_26_serve_binds_loopback_only(built):
    assert BIND_HOST == "127.0.0.1"
    httpd = make_server(8766)
    assert httpd.server_address[0] == "127.0.0.1"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8766/index.html", timeout=5) as response:
            body = response.read().decode()
        assert "Why this signal" in body
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_27_personal_data_stays_local():
    ignore = Path(".gitignore").read_text()
    for line in ("data/user/", "data/cache/", ".env"):
        assert line in ignore
    root = Path("tsppredictor")
    banned_snippets = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        if "tsp-balance" in text or "localStorage" in text:
            banned_snippets.append(str(path))
    assert banned_snippets == []
    # The journal command writes only under data/user.
    journal = (root / "cli.py").read_text()
    assert "journal.jsonl" in journal
    assert "user_dir" in journal


def test_28_browser_smoke_optional():
    pytest.skip(
        "The pinned runtime does not include Playwright. "
        "A browser check is recorded in the handoff only if it was actually run."
    )
