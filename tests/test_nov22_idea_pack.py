"""Nov 22 idea pack: release calendar, journal features, insights, connectors, provenance."""

from __future__ import annotations

import json
import threading
import warnings
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tsppredictor import NOT_ADVICE
from tsppredictor.backtest.walkforward import one_hot, portfolio_returns, simulate_targets
from tsppredictor.data import release_calendar as rc
from tsppredictor.journal import (
    export_journal,
    filter_by_tag,
    import_interchange,
    interchange_stats,
    journal_diff,
    journal_tags,
    make_interchange,
    new_entry,
    read_journal,
    sync_folder,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- Actual publication calendar -------------------------------------------

def test_release_date_uses_real_bls_calendar():
    assert rc.release_date("bls_cpi", "2024-10") == date(2024, 11, 13)
    assert rc.release_date("bls_employment_situation", "2024-10") == date(2024, 11, 1)
    # The Sept 2025 jobs report slipped to Nov 20 in the 2025 shutdown.
    assert rc.release_date("bls_employment_situation", "2025-09") == date(2025, 11, 20)
    assert rc.release("bls_cpi", "2024-10").source == "calendar"


def test_unpublished_month_waits_for_next_release_and_old_months_fall_back_conservatively():
    oct_2025 = rc.release("bls_cpi", "2025-10")  # never published (shutdown)
    assert oct_2025.source == "calendar-next-release"
    assert oct_2025.release_date >= date(2025, 12, 10)
    old = rc.release("bls_cpi", "1990-01")
    assert old.source == "fallback"
    # The fallback day is at least as late as every normal release in the table.
    table = rc.calendar_table()["bls_cpi"]
    normal = [d.day for m, (d, _u) in table.items() if m not in rc.SHUTDOWN_MONTHS
              and (pd.Period(m, "M") + 1).strftime("%Y-%m") == d.strftime("%Y-%m")]
    assert old.release_date.day >= max(normal)


def test_feature_lags_follow_calendar_not_fixed_days():
    from tsppredictor.features.lags import cpi_available_date, unemployment_available_date

    assert cpi_available_date("2024-10") == date(2024, 11, 13)
    assert unemployment_available_date("2025-09") == date(2025, 11, 20)


def test_monthly_features_do_not_leak_late_jobs_report(snap):
    from tsppredictor.features.monthly import build_monthly_features

    feats = build_monthly_features(snap.monthly, snap.h15, snap.bls, snap.gpr_monthly)
    bls = snap.bls.assign(month=snap.bls["month"].astype(str).str.slice(0, 7)).set_index("month")
    rate = pd.to_numeric(bls["unemployment_rate_sa"], errors="coerce")
    gap = rate - rate.rolling(12, min_periods=12).min()
    when = pd.Timestamp("2025-10-31")
    if "2025-09" not in gap.index or when not in feats.index:
        pytest.skip("snapshot does not cover the 2025 shutdown window")
    # The Sept 2025 jobs report came out on 2025-11-20, so at the October month-end
    # the latest visible print is August's (released 2025-09-05).
    assert float(feats.loc[when, "unemp_gap"]) == pytest.approx(float(gap.loc["2025-08"]))


def test_ics_parse_recognizes_releases_and_ignores_other_series():
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261210\r\n"
        "SUMMARY:Consumer Price Index for November 2026\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261204\r\nSUMMARY:Employment Situation for\r\n  November 2026\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261211\r\nSUMMARY:Producer Price Index for November 2026\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20991231\r\nSUMMARY:Consumer Price Index for October 2024\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    releases = rc.parse_bls_ics(ics)
    assert {(r.series, r.reference_month) for r in releases} == {
        ("bls_cpi", "2026-11"), ("bls_employment_situation", "2026-11"), ("bls_cpi", "2024-10")}


def test_upcoming_releases_window():
    rows = rc.upcoming(today=date(2026, 11, 22), days=14)
    assert any(r.series == "bls_employment_situation" and r.release_date == date(2026, 12, 4) for r in rows)


# --- Journal: prefer-incoming, not-advice, tags, diff, stats, sync ---------

def _write_interchange(path: Path, entries):
    path.write_text(json.dumps(make_interchange(entries)), encoding="utf-8")


def test_interchange_carries_not_advice(tmp_path):
    journal = tmp_path / "journal.jsonl"
    journal.write_text(json.dumps(new_entry(decision_date="2024-01-02", fund="G")) + "\n")
    out = tmp_path / "x.json"
    export_journal(journal, out)
    assert json.loads(out.read_text())["not_advice"] == NOT_ADVICE


def test_prefer_incoming_replaces_conflicts_after_backup(tmp_path):
    journal = tmp_path / "journal.jsonl"
    local = new_entry(decision_date="2024-01-02", fund="G", reason="local")
    journal.write_text(json.dumps(local) + "\n")
    incoming = dict(local, reason="incoming wins", fund="C")
    extra = new_entry(decision_date="2024-02-01", fund="S")
    source = tmp_path / "in.json"
    _write_interchange(source, [incoming, extra])
    result = import_interchange(journal, source, on_conflict="prefer-incoming")
    assert result["added"] == 1 and result["replaced"] == 1
    assert result["backup"] and Path(result["backup"]).exists()
    assert local["reason"] in Path(result["backup"]).read_text()
    rows = {row["id"]: row for row in read_journal(journal)}
    assert rows[local["id"]]["reason"] == "incoming wins"


def test_tags_filter_and_legacy_ids_unchanged():
    plain = new_entry(decision_date="2024-01-02", fund="G", reason="r", confidence=0.5)
    tagged = new_entry(decision_date="2024-01-02", fund="G", reason="r", confidence=0.5, tags=["IFT Limit", "news", "news"])
    assert journal_tags(tagged) == ["ift-limit", "news"]
    assert journal_tags(plain) == []
    assert filter_by_tag([plain, tagged], "news") == [tagged]


def test_journal_diff_and_stats(tmp_path):
    a1 = new_entry(decision_date="2024-01-02", fund="G")
    a2 = new_entry(decision_date="2024-01-03", fund="C")
    b2 = dict(a2, reason="changed")
    b3 = new_entry(decision_date="2024-03-01", fund="I", tags=["news"])
    diff = journal_diff([a1, a2], [b2, b3])
    assert [r["id"] for r in diff["only_in_a"]] == [a1["id"]]
    assert [r["id"] for r in diff["only_in_b"]] == [b3["id"]]
    assert [c["id"] for c in diff["conflicts"]] == [a2["id"]]
    path = tmp_path / "s.json"
    _write_interchange(path, [a1, b2, b3])
    stats = interchange_stats(path)
    assert stats["count"] == 3 and stats["first_date"] == "2024-01-02" and stats["last_date"] == "2024-03-01"
    assert stats["funds"] == {"C": 1, "G": 1, "I": 1} and stats["tags"] == {"news": 1}


def test_sync_folder_round_trip(tmp_path):
    folder = tmp_path / "shared"
    folder.mkdir()
    laptop = tmp_path / "laptop.jsonl"
    desktop = tmp_path / "desktop.jsonl"
    laptop.write_text(json.dumps(new_entry(decision_date="2024-01-02", fund="G")) + "\n")
    desktop.write_text(json.dumps(new_entry(decision_date="2024-02-02", fund="C")) + "\n")
    sync_folder(laptop, folder)
    sync_folder(desktop, folder)
    sync_folder(laptop, folder)
    assert len(read_journal(laptop)) == 2 and len(read_journal(desktop)) == 2


# --- Journal insights ------------------------------------------------------

def _ramp_prices():
    dates = pd.bdate_range("2024-01-01", periods=120)
    return pd.DataFrame({"G": np.full(120, 10.0), "F": np.full(120, 10.0),
                         "C": 10.0 * 1.01 ** np.arange(120), "S": 10.0 * 0.99 ** np.arange(120),
                         "I": np.full(120, 10.0)}, index=dates)


def test_entry_outcome_and_calibration():
    from tsppredictor.journal_insights import confidence_calibration, entry_outcome, monthly_review

    prices = _ramp_prices()
    entry = {"date": "2024-01-01", "fund": "C", "confidence": 0.9}
    out = entry_outcome(entry, 21, prices)
    assert out["status"] == "complete"
    assert out["return"] == pytest.approx(1.01 ** 21 - 1)
    assert out["beat_g"] is True and out["g_return"] == pytest.approx(0.0)
    pending = entry_outcome({"date": "2024-06-01", "fund": "C", "confidence": 0.5}, 63, prices)
    assert pending["status"] == "pending"
    entries = [entry, {"date": "2024-01-02", "fund": "S", "confidence": 0.85},
               {"date": "2024-01-03", "fund": "C", "confidence": 0.2}]
    cal = confidence_calibration(entries, prices)
    high = next(b for b in cal["bins"] if b["confidence_from"] <= 0.9 < b["confidence_to"] + 1e-9)
    assert high["n"] == 2 and high["hit_rate"] == pytest.approx(0.5)
    review = monthly_review(entries, prices, "2024-01")
    assert NOT_ADVICE in review["markdown"] and review["complete_21d"] == 3


def test_ift_diary_enforces_two_unrestricted_transfers(tmp_path):
    from tsppredictor.journal_insights import ift_month_summary, record_ift

    record_ift(tmp_path, when=date(2024, 3, 4), from_mix="100 G", to_mix="100 C", reason="trend")
    record_ift(tmp_path, when=date(2024, 3, 11), from_mix="100 C", to_mix="100 S", reason="rotation")
    with pytest.raises(ValueError, match="two unrestricted"):
        record_ift(tmp_path, when=date(2024, 3, 18), from_mix="100 S", to_mix="100 I", reason="no")
    record_ift(tmp_path, when=date(2024, 3, 18), from_mix="100 S", to_mix="100 G", reason="safety", g_only=True)
    summary = ift_month_summary(tmp_path, "2024-03")
    assert summary["unrestricted_used"] == 2 and summary["unrestricted_left"] == 0 and len(summary["transfers"]) == 3


# --- More hand ledgers: months that hit the two-IFT limit -----------------

def test_hand_ledger_third_request_in_month_is_refused():
    """G -> C -> G uses both transfers; a third request for C is refused until the next month."""
    dates = pd.bdate_range("2024-01-02", periods=6)  # Jan 2..9, all January
    prices = pd.DataFrame({"G": [100.0] * 6, "F": [100.0] * 6, "C": [100, 110, 121, 133.1, 146.41, 161.051],
                           "S": [100.0] * 6, "I": [100.0] * 6}, index=dates)
    targets = np.full((6, 5), np.nan)
    targets[0] = one_hot("C")  # posts at session 1
    targets[1] = one_hot("G")  # posts at session 2: second and last unrestricted IFT
    targets[2] = one_hot("C")  # refused: limit reached, not G-only
    sim = simulate_targets(dates, targets, lag=1, initial=one_hot("G"), prices=prices)
    assert sim["month_used"] == {"2024-01": 2}
    assert sim["post_dates"] == [dates[1], dates[2]]
    wealth = np.cumprod(1.0 + portfolio_returns(prices, sim["weights"]))
    # Hand ledger: $1 in G through the session-1 post, then C for exactly one session
    # (110 -> 121, +10%), then back in G for the rest of the month.
    assert wealth == pytest.approx([1.0, 1.0, 1.1, 1.1, 1.1, 1.1])


def test_hand_ledger_limit_resets_in_new_month():
    """Two January transfers use the limit; the refused move goes through in February."""
    dates = pd.DatetimeIndex(["2024-01-29", "2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02", "2024-02-05"])
    prices = pd.DataFrame({"G": [100.0] * 6, "F": [100.0] * 6, "C": [100, 100, 100, 100, 110, 121],
                           "S": [100.0] * 6, "I": [100.0] * 6}, index=dates)
    targets = np.full((6, 5), np.nan)
    targets[0] = one_hot("S")   # posts Jan 30
    targets[1] = one_hot("G")   # posts Jan 31 (limit used)
    targets[2] = one_hot("C")   # requested Jan 31 after close -> posts Feb 1 (new month)
    sim = simulate_targets(dates, targets, lag=1, initial=one_hot("G"), prices=prices)
    assert sim["month_used"] == {"2024-01": 2, "2024-02": 1}
    assert sim["post_dates"][-1] == dates[3]
    wealth = np.cumprod(1.0 + portfolio_returns(prices, sim["weights"]))
    # In C from the Feb 1 close: +10% on Feb 2 and +10% on Feb 5.
    assert wealth == pytest.approx([1.0, 1.0, 1.0, 1.0, 1.1, 1.21])


def test_simulate_without_prices_warns():
    dates = pd.bdate_range("2024-01-02", periods=3)
    with pytest.warns(DeprecationWarning):
        simulate_targets(dates, np.full((3, 5), np.nan), lag=1, initial=one_hot("G"))
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        prices = pd.DataFrame(100.0, index=dates, columns=["G", "F", "C", "S", "I"])
        simulate_targets(dates, np.full((3, 5), np.nan), lag=1, initial=one_hot("G"), prices=prices)


def test_allocation_drift_tracks_mix_between_posts():
    from tsppredictor.journal_insights import allocation_drift

    dates = pd.bdate_range("2024-01-02", periods=4)
    prices = pd.DataFrame({"G": [100.0] * 4, "F": [100.0] * 4, "C": [100, 110, 121, 133.1],
                           "S": [100.0] * 4, "I": [100.0] * 4}, index=dates)
    sim = simulate_targets(dates, np.full((4, 5), np.nan), lag=1,
                           initial=np.array([0.5, 0, 0.5, 0, 0]), prices=prices)
    drift = allocation_drift(sim["weights"], dates, sim["post_dates"])
    assert drift["max_drift_any_fund"] > 0.0


def test_drift_vs_constant_reports_both_models(snap):
    from tsppredictor.backtest.compare import drift_vs_constant
    from tsppredictor.features.monthly import build_monthly_features, monthly_price_index
    from tsppredictor.models.rules import RULES

    feats = build_monthly_features(snap.monthly, snap.h15, snap.bls, snap.gpr_monthly)
    px = monthly_price_index(snap.monthly)
    rule = next(iter(RULES))
    result = drift_vs_constant(rule, feats, px)
    assert set(result["price_drift"]) == {"final_wealth", "cagr", "max_drawdown", "transfers"}
    assert result["cagr_difference"] == pytest.approx(result["price_drift"]["cagr"] - result["constant_target"]["cagr"])
    with pytest.raises(KeyError):
        drift_vs_constant("nope", feats, px)


# --- Evidence additions ----------------------------------------------------

def test_lag_cost_table_and_missing_runs():
    from tsppredictor.evidence import lag_cost_table, lag_sensitivity

    rows = [
        {"id": "r", "name": "Rule", "cadence": "daily", "horizon": 21, "lag": 1, "metrics": {"cagr": 0.08}},
        {"id": "r", "name": "Rule", "cadence": "daily", "horizon": 21, "lag": 2, "metrics": {"cagr": 0.07}},
        {"id": "solo", "name": "Solo", "cadence": "daily", "horizon": 63, "lag": 1, "metrics": {"cagr": 0.05}},
    ]
    table = lag_cost_table(rows)
    assert table[0]["cagr_lost_per_extra_lag"] == pytest.approx(0.01)
    assert "cost" in table[0]["plain"]
    sens = lag_sensitivity(rows)
    assert sens["missing_runs"] == [{"id": "solo", "cadence": "daily", "horizon": 63, "run_lag": 2}]


def test_vintage_gap_report_and_metadata():
    from tsppredictor.evidence import macro_vintage_metadata, vintage_gap_report

    report = vintage_gap_report(None)
    assert {r["series"] for r in report["series"]} == {"CPIAUCSL", "UNRATE", "H15"}
    assert all(not r["first_print"] and r["gap_months"] > 0 for r in report["series"])
    fp = {"CPIAUCSL": pd.DataFrame({"month": ["2024-01", "2024-02"], "value": [1.0, 2.0]})}
    meta = macro_vintage_metadata(fp)
    assert meta["first_print_vintages_available"] is True
    covered = vintage_gap_report(fp)
    cpi = next(r for r in covered["series"] if r["series"] == "CPIAUCSL")
    assert cpi["first_print"] is True


# --- Connectors ------------------------------------------------------------

def test_alfred_off_without_key_and_first_print_overlay(monkeypatch):
    from tsppredictor.connectors import alfred

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert alfred.enabled() is False
    with pytest.raises(RuntimeError, match="off"):
        alfred.fetch_first_print("CPIAUCSL")
    assert alfred.first_print_params("UNRATE", "k")["output_type"] == 4
    bls = pd.DataFrame({"month": ["2024-01", "2024-02"], "cpi_u_sa": [300.0, 301.0], "unemployment_rate_sa": [3.7, 3.9]})
    out = alfred.apply_first_print(bls, {"UNRATE": pd.DataFrame({"month": ["2024-01"], "value": [3.6]})})
    assert out["unemployment_rate_sa"].tolist() == [3.6, 3.9]
    assert out["cpi_u_sa"].tolist() == [300.0, 301.0]


def test_h15_ddp_fixture_parses_real_series():
    from tsppredictor.connectors.h15 import parse_ddp_csv

    frame = parse_ddp_csv((FIXTURES / "h15_ddp_sample.csv").read_text())
    assert {"date", "ust_3m", "ust_2y", "ust_10y"} <= set(frame.columns)
    assert len(frame) > 0 and frame["ust_10y"].dropna().between(0, 20).all()


@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1", True), ("192.168.1.20", True), ("10.0.0.5", True), ("[::1]", True), ("fd00::1", True),
    ("100.64.1.1", False), ("224.0.0.251", False), ("169.254.1.1", False), ("8.8.8.8", False),
    ("0.0.0.0", False), ("example.com", False), ("[ff02::1]", False), ("::ffff:8.8.8.8", False),
])
def test_localsend_host_allowlist(host, ok):
    from tsppredictor.connectors.localsend import allowed_host

    assert allowed_host(host) is ok


def test_localsend_sends_to_fake_receiver(tmp_path):
    pytest.importorskip("requests")
    from tsppredictor.connectors.localsend import send_file

    received = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.startswith("/api/localsend/v2/prepare-upload"):
                files = json.loads(body)["files"]
                payload = json.dumps({"sessionId": "s1", "files": {k: "tok" for k in files}}).encode()
            else:
                received["path"] = self.path
                received["body"] = body
                payload = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = tmp_path / "j.json"
        path.write_text('{"x": 1}')
        result = send_file(path, "127.0.0.1", port=server.server_address[1])
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert result["sent"] is True and received["body"] == b'{"x": 1}'
    assert "sessionId=s1" in received["path"] and "token=tok" in received["path"]
    with pytest.raises(ValueError):
        send_file(path, "8.8.8.8")


def test_validation_profiling_tracking_and_exports(tmp_path, prices):
    from tsppredictor.connectors.exports import export_evidence_project, export_obsidian
    from tsppredictor.connectors.frames import to_pandas
    from tsppredictor.connectors.profiling import compare, profile, profile_snapshot
    from tsppredictor.connectors.tracking import log_run
    from tsppredictor.connectors.validation import validate_prices

    report = validate_prices(prices)
    assert report["passed"] is True
    bad = prices.copy()
    bad.iloc[5, bad.columns.get_loc("C")] = -1.0
    assert validate_prices(bad)["passed"] is False
    store = tmp_path / "profile.json"
    first = profile_snapshot(prices, store)
    assert first["flags"] == []
    shrunk = profile(prices.iloc[:-10])
    assert any(f["flag"] == "rows_decreased" for f in compare(profile(prices), shrunk))
    record = log_run({"a": 1}, {"m": 0.5, "skip": "text"}, path=tmp_path / "runs.jsonl")
    assert record["metrics"] == {"m": 0.5}
    entry = new_entry(decision_date="2024-01-02", fund="C", reason="Trend / test", tags=["news"])
    notes = export_obsidian([entry], tmp_path / "vault")
    note = next((tmp_path / "vault" / "TSP Journal").glob("*.md")).read_text()
    assert notes["notes"] == 1 and "tags: [tsp-journal, news]" in note and NOT_ADVICE in note
    ev = export_evidence_project([{"id": "x", "name": "X", "cadence": "daily", "horizon": 21, "lag": 1,
                                   "metrics": {"cagr": 0.1}}], tmp_path / "evidence")
    assert (tmp_path / "evidence" / "sources" / "tsp" / "scoreboard.csv").exists() and ev
    assert to_pandas(prices) is not None


# --- Provenance: verify and reproduce --------------------------------------

def _fake_dist(root: Path, elapsed: float = 1.0) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    (root / "index.html").write_text("<html></html>")
    (data / "meta.json").write_text(json.dumps({"schema_version": 1, "elapsed_seconds": elapsed, "x": 1}))
    (data / "build-manifest.json").write_text(json.dumps({"schema_version": 1, "source": {"revision": "abc"}}))
    return root


def test_verify_build_manifest_detects_tampering(tmp_path):
    from tsppredictor.provenance import stamp_outputs, verify_build_manifest, write_provenance_badge

    dist = _fake_dist(tmp_path / "dist")
    assert verify_build_manifest(dist)["ok"] is False  # no output hashes yet
    stamp_outputs(dist)
    assert verify_build_manifest(dist)["ok"] is True
    assert write_provenance_badge(dist)["verified"] is True
    assert verify_build_manifest(dist)["ok"] is True  # badge file is excluded from hashing
    (dist / "index.html").write_text("<html>changed</html>")
    result = verify_build_manifest(dist)
    assert result["ok"] is False and "changed: index.html" in result["problems"]
    (dist / "extra.js").write_text("1")
    assert "unlisted: extra.js" in verify_build_manifest(dist)["problems"]


def test_compare_builds_ignores_timing_only():
    import tempfile

    from tsppredictor.provenance import compare_builds, stamp_outputs

    with tempfile.TemporaryDirectory() as tmp:
        a = _fake_dist(Path(tmp) / "a", elapsed=1.0)
        b = _fake_dist(Path(tmp) / "b", elapsed=9.0)
        stamp_outputs(a)
        assert compare_builds(a, b)["reproduced"] is True
        (b / "data" / "meta.json").write_text(json.dumps({"schema_version": 1, "elapsed_seconds": 2, "x": 2}))
        result = compare_builds(a, b)
        assert result["reproduced"] is False and result["differed"] == ["data/meta.json"]


def test_vintage_replay_without_cache_changes_nothing(snap):
    from tsppredictor.vintage_replay import replay

    result = replay(snap, first_print={})
    assert result["available"] is False and "FRED_API_KEY" in result["message"]


def test_release_context_for_journal_entry():
    from tsppredictor.journal_insights import release_context

    rows = release_context({"date": "2024-11-13", "fund": "C"})
    assert any(r["series"] == "bls_cpi" for r in rows)


def test_fetch_ics_rejects_block_pages():
    class FakeResponse:
        text = "<html>Access Denied</html>"
        status_code = 200

        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, *args, **kwargs):
            assert kwargs["allow_redirects"] is False
            return FakeResponse()

    with pytest.raises(RuntimeError, match="did not return a calendar"):
        rc.fetch_ics(session=FakeSession())


def test_fetch_ics_does_not_follow_redirects():
    class Redirect:
        status_code = 302

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, url, **kwargs):
            assert url == rc.ICS_URL and kwargs["allow_redirects"] is False
            return Redirect()

    with pytest.raises(RuntimeError, match="redirects are not followed"):
        rc.fetch_ics(session=FakeSession())


def test_buy_and_hold_slices_are_lag_invariant_not_unpaired():
    from tsppredictor.evidence import lag_sensitivity

    rows = [{"id": "bh_i_after_break", "kind": "slice", "cadence": "daily", "horizon": None, "lag": 1,
             "name": "BH I", "metrics": {"cagr": 0.05}}]
    sens = lag_sensitivity(rows)
    assert sens["unpaired"] == [] and sens["missing_runs"] == []
    assert sens["lag_invariant"][0]["id"] == "bh_i_after_break"
