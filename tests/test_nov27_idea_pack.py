"""Nov 27 2026 idea pack: profiling, studies, add-ons and connectors."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tsppredictor.connectors import profiling as prof


def _prices(n=400, seed=0, vol=0.01):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    data = {f: 10 * np.cumprod(1 + rng.normal(0, vol * (1 + i * 0.3), n)) for i, f in enumerate("GFCSI")}
    return pd.DataFrame(data, index=idx)


# --- improvements ---------------------------------------------------------

def test_imp01_scarcity_is_labeled_by_its_quantile():
    from tsppredictor.studies import scarcity_at, scarcity_upper_bound

    rng = np.random.default_rng(1)
    rets = rng.normal(0, 0.01, 1000)
    raw = np.tile([0.0, 0, 1, 0, 0], (1000, 1)).astype(float)
    held = np.tile([0.5, 0, 0.5, 0, 0], (1000, 1)).astype(float)
    five = scarcity_upper_bound(raw, held, rets)
    assert five["worst_sessions"] == 50 and five["worst_5pct_sessions"] == 50
    assert "worst 5%" in five["note"] and "decile" not in five["note"]
    ten = scarcity_at(raw, held, rets, 0.10)
    assert ten["worst_sessions"] == 100 and ten["label"] == "worst decile (10%)" and ten["worst_5pct_sessions"] is None
    with pytest.raises(ValueError):
        scarcity_at(raw, held, rets, 1.5)


def test_imp02_threshold_is_a_plain_volatility_ratio():
    base = {"C": {"count": 10, "ret_std": 0.01}}
    assert prof.compare(base, {"C": {"count": 10, "ret_std": 0.0135}}) == []
    flags = prof.compare(base, {"C": {"count": 10, "ret_std": 0.0145}})
    assert flags[0]["flag"] == "volatility_shift" and flags[0]["threshold"] == prof.VOLATILITY_RATIO
    assert prof.compare(base, {"C": {"count": 10, "ret_std": 0.0069}})[0]["ratio"] < 1
    assert prof.compare(base, {"C": {"count": 10, "ret_std": 0.0145}}, volatility_ratio=1.5) == []
    with pytest.raises(ValueError):
        prof.compare(base, base, volatility_ratio=1.0)


def test_imp03_imp04_flags_persist_until_acknowledged_and_builds_repeat(tmp_path):
    store = tmp_path / "price_profile.json"
    calm = _prices()
    assert prof.profile_snapshot(calm, store, data_as_of="2021-01-01")["flags"] == []
    wild = calm.copy()
    wild["C"] = 10 * np.cumprod(1 + np.random.default_rng(9).normal(0, 0.05, len(calm)))
    first = prof.profile_snapshot(wild, store, data_as_of="2021-02-01")
    second = prof.profile_snapshot(wild, store, data_as_of="2021-02-01")
    assert any(f["flag"] == "volatility_shift" for f in first["flags"])
    assert first["flags"] == second["flags"], "a second build must not hide the flag"
    assert first["baseline_sha256"] == second["baseline_sha256"]
    assert prof.acknowledge_flags(store)["acknowledged"] is True
    assert [f for f in prof.profile_snapshot(wild, store, data_as_of="2021-02-01")["flags"] if f["flag"] == "volatility_shift"] == []


def test_imp05_fn02_restated_history_is_caught(tmp_path):
    store = tmp_path / "price_profile.json"
    px = _prices()
    prof.profile_snapshot(px, store)
    grown = pd.concat([px, _prices(3, seed=5).set_axis(pd.bdate_range(px.index[-1] + pd.Timedelta(days=1), periods=3))])
    assert not [f for f in prof.profile_snapshot(grown, store)["flags"] if f["flag"] == "history_restated"]
    edited = grown.copy()
    edited.iloc[10, 2] *= 1.01
    flags = prof.profile_snapshot(edited, store)["flags"]
    assert any(f["flag"] == "history_restated" for f in flags)
    d1 = prof.history_digest(px, keep_last=5)
    assert d1["rows"] == len(px) - 5 and d1 == prof.history_digest(px.copy(), keep_last=5)
    with pytest.raises(ValueError):
        prof.history_digest(px, keep_last=-1)


def test_imp06_fn09_l_funds_are_profiled(tmp_path, snap):
    l_frame = snap.daily[[c for c in snap.daily.columns if str(c).startswith("L")]]
    profile = prof.l_fund_profile(l_frame)
    assert "L2050" in profile and profile["L2050"]["count"] > 100
    out = prof.profile_snapshot(_prices(), tmp_path / "p.json", l_frame=pd.DataFrame({"L2050": _prices()["C"]}))
    assert "L2050" in out["l_funds"]


def test_imp07_fn04_spike_windows_do_not_overlap():
    from tsppredictor.studies import gpr_spike_study, spike_starts

    flag = np.zeros(400)
    for start in (100, 110, 250):
        flag[start:start + 3] = 1
    assert spike_starts(flag) == [100, 110, 250]
    assert spike_starts(flag, cooldown=60) == [100, 250]
    px = _prices()
    study = gpr_spike_study(px, pd.Series(flag, index=px.index))
    assert study["n"] == 2 and study["skipped_overlapping"] == 1 and study["cooldown_sessions"] == 60
    assert len(study["spike_dates"]) == 2


def test_imp08_fn05_filled_sessions_are_counted():
    from tsppredictor.studies import filled_sessions, gpr_spike_study

    assert filled_sessions([0.0, np.nan, 0.01, np.inf]) == 2
    px = _prices()
    px.iloc[105:108, px.columns.get_loc("C")] = np.nan
    flag = np.zeros(len(px))
    flag[100:102] = 1
    study = gpr_spike_study(px, pd.Series(flag, index=px.index))
    assert study["funds"]["C"]["filled_sessions"] >= 3 and study["funds"]["G"]["filled_sessions"] == 0


def test_imp09_profile_writes_are_atomic(tmp_path, monkeypatch):
    store = tmp_path / "p.json"
    prof.profile_snapshot(_prices(), store)
    before = store.read_text()
    calls = []
    real = prof.os.replace
    monkeypatch.setattr(prof.os, "replace", lambda a, b: (calls.append((a, b)), real(a, b)))
    prof.acknowledge_flags(store)
    assert calls and all(Path(a).name.endswith(".tmp") for a, _ in calls)
    assert json.loads(store.read_text()).keys() >= json.loads(before).keys() - {"_data_as_of"}
    assert not list(tmp_path.glob(".*.tmp"))


def test_imp10_whylogs_failure_does_not_end_the_build(tmp_path, monkeypatch):
    import sys
    import types

    fake = types.ModuleType("whylogs")

    def boom(**_kw):
        raise RuntimeError("profile writer crashed")

    fake.log = boom
    monkeypatch.setitem(sys.modules, "whylogs", fake)
    out = prof.profile_snapshot(_prices(), tmp_path / "p.json")
    assert out["whylogs"] is False and "profile writer crashed" in out["whylogs_reason"]


# --- functions ------------------------------------------------------------

def test_fn01_fn03_history_and_acknowledge(tmp_path):
    store = tmp_path / "p.json"
    assert prof.acknowledge_flags(store)["acknowledged"] is False
    for i in range(3):
        prof.profile_snapshot(_prices(seed=i), store, data_as_of=f"2021-0{i + 1}-01")
        time.sleep(0.01)
    history = prof.profile_history(2, store)
    assert [h["data_as_of"] for h in history] == ["2021-02-01", "2021-03-01"]
    assert prof.acknowledge_flags(store)["baseline_data_as_of"] == "2021-03-01"


def test_fn06_engine_report():
    from tsppredictor.build import engine_report

    report = engine_report()
    assert report["engine"] == "pandas" and "polars" in report["optional_engines"]


def test_fn08_f_drawdown_by_window(prices, snap):
    from tsppredictor.studies import f_drawdown_by_window, g_versus_f

    rows = f_drawdown_by_window(g_versus_f(prices, snap.monthly))
    by_id = {r["id"]: r for r in rows}
    assert by_id["hiking_2022"]["f_max_drawdown"] < -0.05
    assert by_id["hiking_2022"]["g_max_drawdown"] >= -1e-9


def test_fn10_explain_flag():
    assert "fewer than" in prof.explain_flag({"fund": "C", "flag": "rows_decreased", "before": 10, "now": 8})
    assert "2.00 times higher" in prof.explain_flag({"fund": "C", "flag": "volatility_shift", "before": 0.01, "now": 0.02, "ratio": 2.0})
    assert "lower" in prof.explain_flag({"fund": "C", "flag": "volatility_shift", "before": 0.02, "now": 0.01})
    assert "changed in place" in prof.explain_flag({"fund": "*", "flag": "history_restated"})


# --- add-ons --------------------------------------------------------------

def test_addons_are_built_and_linked(built):
    dist = Path(built["dist"])
    for page in ("data-drift", "profile-timeline", "gpr-spikes", "rate-rise-atlas", "study-caveats"):
        html = (dist / "addons" / f"{page}.html").read_text()
        assert "not financial advice" in html.lower() and "http://" not in html.replace("http://www.w3.org", "")
        assert f"addons/{page}.html" in (dist / "index.html").read_text()
    meta = json.loads((dist / "data" / "meta.json").read_text())
    assert "explanations" in meta["price_profile"] and meta["engine"]["engine"] == "pandas"
    manifest = json.loads((dist / "data" / "build-manifest.json").read_text())
    assert manifest["inputs"]["price_profile_baseline_sha256"]
    assert 'id="snapshot-age"' in (dist / "index.html").read_text()
    atlas = json.loads((dist / "data" / "rate-rise-atlas.json").read_text())
    assert {p["id"] for p in atlas["panels"]} == {"rate_shock_1994", "taper_2013", "hiking_2022"}
    assert json.loads((dist / "data" / "gpr-spike-explorer.json").read_text())["spikes"]


def test_add01_drift_card_and_acknowledge_endpoint(built, monkeypatch, tmp_path):
    from tsppredictor import cli
    from tsppredictor.addons import data_drift_card

    card = data_drift_card({"price_profile_flags": [{"fund": "C", "flag": "rows_decreased", "before": 2, "now": 1}]})
    assert card["count"] == 1 and "fewer than" in card["items"][0]["sentence"]
    monkeypatch.setattr("tsppredictor.connectors.profiling.acknowledge_flags", lambda: {"acknowledged": True})
    server = cli.make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/api/profile/acknowledge"
        with pytest.raises(urllib.error.HTTPError) as no_header:
            urllib.request.urlopen(urllib.request.Request(url, method="POST"))
        assert no_header.value.code == 403
        ok = urllib.request.urlopen(urllib.request.Request(url, method="POST", headers={"X-TSP-Local": "1"}))
        assert json.loads(ok.read())["acknowledged"] is True
    finally:
        server.shutdown()


def test_add02_add03_add04_models():
    from tsppredictor.addons import profile_timeline, rate_rise_atlas, spike_explorer

    tl = profile_timeline([{"data_as_of": "a", "funds": {"C": {"ret_std": 0.01}}},
                           {"data_as_of": "b", "funds": {"C": {"ret_std": 0.02}}, "l_funds": {"L2050": {"ret_std": 0.005}}}])
    assert tl["series"] == {"C": [0.01, 0.02], "L2050": [None, 0.005]}
    px = _prices(300)
    ex = spike_explorer(px, {"spike_dates": [px.index[100].strftime("%Y-%m-%d"), px.index[290].strftime("%Y-%m-%d")]})
    assert len(ex["spikes"]) == 1 and len(ex["spikes"][0]["funds"]["C"]["path"]) == 81
    monthly = pd.DataFrame({"month": [f"1994-{m:02d}" for m in range(1, 13)], "G Fund": [0.5] * 12, "F Fund": [-0.3] * 12})
    atlas = rate_rise_atlas(px, monthly)
    assert atlas["panels"][0]["id"] == "rate_shock_1994" and atlas["panels"][0]["end"]["F"] < 0


def test_add05_restatement_alarm_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from tsppredictor import addons, cli

    store = tmp_path / "p.json"
    px = _prices()
    prof.profile_snapshot(px, store)
    assert addons.restatement_alarm(px, store)["restated"] is False
    edited = px.copy()
    edited.iloc[3, 0] = 99.0
    assert addons.restatement_alarm(edited, store)["restated"] is True
    monkeypatch.setattr(cli, "_core_prices", lambda: edited)
    monkeypatch.setattr(addons, "restatement_alarm", lambda p: {"restated": True, "flags": [{}]})
    assert CliRunner().invoke(cli.app, ["profile", "restatement-check"]).exit_code == 1


def test_add06_polars_bench():
    from tsppredictor.addons import polars_bench

    out = polars_bench(_prices(), repeats=1)
    assert out["pandas_ms"] >= 0
    try:
        import narwhals  # noqa: F401
        import polars  # noqa: F401
    except ImportError:
        assert out["polars"] is False and out["reason"]
        return
    assert out["polars"] is True and out["engine"] == "polars"


def test_add07_monthly_learning_note(built, tmp_path):
    from tsppredictor.addons import monthly_learning_lines, monthly_learning_note, simple_pdf

    dist = Path(built["dist"])
    history = json.loads((dist / "data" / "monthly-history.json").read_text())
    month = history["months"][-1]
    pdf = monthly_learning_note(month, dist, tmp_path / "note.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF") and b"/Count 1" in pdf
    lines = monthly_learning_lines(month, history, json.loads((dist / "data" / "allocation-drift.json").read_text()))
    assert any("What the rules did" in line for line in lines)
    assert not any("you should buy" in line.lower() for line in lines)
    assert b"(a \\(b\\)) Tj" in simple_pdf(["a (b)"])


def test_add08_study_caveats(built):
    from tsppredictor.addons import study_caveats

    caveats = study_caveats(Path(built["dist"]))
    assert caveats["small_sample_count"] >= 2
    assert any(c["where"].startswith("history.gpr_spikes") and c["n"] is not None for c in caveats["caveats"])


def test_add09_snapshot_age():
    from tsppredictor.addons import snapshot_age

    assert snapshot_age("2026-11-20", date(2026, 11, 20))["sessions"] == 0
    # Mon Nov 23 to Fri Nov 27 2026, minus Thanksgiving (Nov 26).
    assert snapshot_age("2026-11-20", date(2026, 11, 27)) == {
        "sessions": 4, "data_as_of": "2026-11-20", "today": "2026-11-27", "label": "Snapshot is 4 sessions old"}


def test_add10_profile_export_bundle(tmp_path):
    from tsppredictor.addons import profile_export_bundle

    store = tmp_path / "p.json"
    prof.profile_snapshot(_prices(), store, data_as_of="2021-01-01")
    out = profile_export_bundle(tmp_path / "b.zip", store, meta={"price_profile_flags": [{"fund": "C"}]})
    names = zipfile.ZipFile(out["path"]).namelist()
    assert "price_profile.json" in names and "flags.json" in names and any(n.startswith("profiles/") for n in names)


# --- connectors -----------------------------------------------------------

def test_con01_modin_bridge_without_narwhals(monkeypatch):
    from tsppredictor.connectors import frames

    fake_cls = type("DataFrame", (), {"__module__": "modin.pandas.dataframe", "_to_pandas": lambda self: pd.DataFrame({"a": [1]})})
    monkeypatch.setattr(frames, "available", lambda: False)
    assert frames.is_modin(fake_cls()) and frames.to_pandas(fake_cls())["a"].tolist() == [1]
    assert frames.engine_name(fake_cls()) == "modin"
    with pytest.raises(TypeError):
        frames.to_pandas(object())


def test_con02_parquet_cache(tmp_path):
    from tsppredictor.connectors.parquet_cache import available, load_frame, save_frame

    px = _prices(30)
    path = save_frame(px, tmp_path / "prices")
    assert path.suffix == (".parquet" if available() else ".csv")
    back = load_frame(tmp_path / "prices")
    pd.testing.assert_frame_equal(back, px, check_freq=False, check_index_type=False)
    assert save_frame(px, tmp_path / "plain", prefer_parquet=False).suffix == ".csv"


def test_con03_vega_lite_specs():
    from tsppredictor.connectors.vegalite import profile_timeline_spec, spike_explorer_spec

    spec = profile_timeline_spec({"labels": ["a", "b"], "series": {"C": [0.01, None]}})
    assert spec["$schema"].endswith("v5.json") and spec["data"]["values"] == [{"profile": "a", "fund": "C", "ret_std": 0.01}]
    sp = spike_explorer_spec({"spikes": [{"date": "2020-01-01", "offsets": [0, 1], "funds": {"C": {"path": [0, 0.1]}}}]})
    assert sp["params"][0]["bind"]["options"] == ["2020-01-01"] and len(sp["data"]["values"]) == 2


def test_con04_zarr_store(tmp_path):
    from tsppredictor.connectors.zarr_store import load_arrays, save_arrays

    arrays = {"boot": np.arange(12.0).reshape(4, 3), "weights": np.ones(5)}
    save_arrays(tmp_path / "wf", arrays)
    back = load_arrays(tmp_path / "wf")
    assert np.array_equal(back["boot"], arrays["boot"]) and np.array_equal(back["weights"], arrays["weights"])
    with pytest.raises(ValueError):
        save_arrays(tmp_path / "x", {"bad-name": np.ones(1)})


def test_con05_arrow_flight_bind_rules_and_roundtrip():
    from tsppredictor.connectors import flight

    with pytest.raises(ValueError):
        flight.check_bind("8.8.8.8", allow_lan=True)
    with pytest.raises(ValueError):
        flight.check_bind("192.168.1.20")
    assert flight.check_bind("192.168.1.20", allow_lan=True) == "192.168.1.20"
    if not flight.available():
        pytest.skip("pyarrow.flight not installed")
    px = _prices(20)
    server, location = flight.make_server({"prices": px}, port=0)
    location = f"grpc://127.0.0.1:{server.port}"
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        got = flight.fetch(location, "prices")
        assert len(got) == 20 and set("GFCSI") <= set(got.columns)
    finally:
        server.shutdown()


def test_con06_jupyter_export(built, tmp_path):
    from tsppredictor.connectors.notebook import study_notebook, write_notebook

    nb = study_notebook("gpr_spikes", Path(built["dist"]))
    assert nb["nbformat"] == 4 and len(nb["cells"]) == 3
    code = "".join(nb["cells"][1]["source"]) + "".join(nb["cells"][2]["source"])
    scope: dict = {}
    exec(compile(code.replace("frame.plot(title='Median path around GPR spikes')\n", ""), "nb", "exec"), scope)  # noqa: S102
    assert scope["frame"].shape[0] == 81
    assert write_notebook("stress", Path(built["dist"]), tmp_path / "s.ipynb").exists()
    with pytest.raises(KeyError):
        study_notebook("nope", Path(built["dist"]))


def test_con07_numbers_csv(built, tmp_path):
    from tsppredictor.connectors.numbers_csv import export_numbers

    out = export_numbers(Path(built["dist"]), tmp_path / "h.csv", "2020-01", "2020-12")
    raw = (tmp_path / "h.csv").read_bytes()
    assert raw.startswith("\ufeff".encode()) and out["rows"] == 12 and b"\r\n" in raw
    with pytest.raises(ValueError):
        export_numbers(Path(built["dist"]), tmp_path / "x.csv", "2021-01", "2020-01")


def test_con08_prophet_toy_is_labeled():
    from tsppredictor.connectors.prophet_baseline import TOY_LABEL, toy_baseline

    monthly = pd.DataFrame({"month": [f"{2000 + i // 12}-{i % 12 + 1:02d}" for i in range(36)], "C Fund": np.linspace(-1, 1, 36)})

    class FakeModel:
        def fit(self, frame):
            self.n = len(frame)

        def make_future_dataframe(self, periods, freq):
            return pd.DataFrame({"ds": pd.date_range("2003-01-01", periods=periods, freq=freq)})

        def predict(self, future):
            return future.assign(yhat=0.5)

    out = toy_baseline(monthly, model_factory=FakeModel)
    assert out["toy"] is True and out["label"] == TOY_LABEL and len(out["rows"]) == 3
    with pytest.raises(ValueError):
        toy_baseline(monthly.head(5), model_factory=FakeModel)


def test_con09_redash_sqlite(tmp_path):
    import sqlite3

    from tsppredictor.connectors.redash import export_sqlite, saved_queries

    journal = tmp_path / "journal.jsonl"
    journal.write_text(json.dumps({"id": "j1", "date": "2024-01-02", "fund": "C", "confidence": 0.6, "tags": ["x"]}) + "\nnot json\n")
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"at": "t", "params": {"data_as_of": "2024-01-01", "n_trials": 3}, "metrics": {"ensemble_cagr": 0.1}}) + "\n")
    out = export_sqlite(tmp_path / "r.sqlite", journal=journal, runs=runs)
    assert out["journal_rows"] == 1 and out["run_rows"] == 1
    con = sqlite3.connect(out["path"])
    for sql in saved_queries().values():
        con.execute(sql).fetchall()
    assert con.execute(saved_queries()["decisions_by_fund"]).fetchall() == [("C", 1, 0.6)]


def test_con10_hdf5_profiles(tmp_path):
    from tsppredictor.connectors.hdf5_profiles import available, read_profiles, write_profiles

    history = [{"data_as_of": "a", "funds": {"C": {"count": 1, "last": 2.0, "ret_mean": 0.0, "ret_std": 0.01}}, "flags": []},
               {"data_as_of": "b", "funds": {"C": {"count": 2, "last": 2.1, "ret_mean": 0.0, "ret_std": 0.02}}, "flags": [{"f": 1}]}]
    if not available():
        with pytest.raises(RuntimeError):
            write_profiles(history, tmp_path / "p.h5")
        return
    write_profiles(history, tmp_path / "p.h5")
    back = read_profiles(tmp_path / "p.h5")
    assert back["labels"] == ["a", "b"] and back["series"]["C"]["ret_std"] == [0.01, 0.02]
