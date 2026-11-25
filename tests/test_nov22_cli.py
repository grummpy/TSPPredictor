"""CLI and edge-case coverage for the Nov 22 idea-pack commands."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from tsppredictor import NOT_ADVICE, cli
from tsppredictor.data import release_calendar as rc
from tsppredictor.journal import filter_by_tag, new_entry
from tsppredictor.provenance import stamp_outputs, verify_build_manifest, write_provenance_badge

RUNNER = CliRunner()


def _fake_dist(root: Path) -> Path:
    data = root / "data"
    data.mkdir(parents=True)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (data / "meta.json").write_text(json.dumps({"schema_version": 1, "elapsed_seconds": 1.0}), encoding="utf-8")
    (data / "today.json").write_text(
        json.dumps({"schema_version": 1, "data_as_of": "2026-10-05", "signal_date": "2026-10-05", "fund": "G", "stance": "Shelter in G"}),
        encoding="utf-8",
    )
    (data / "scoreboard.json").write_text(
        json.dumps({"rows": [{"id": "bh_c", "name": "Buy-and-hold C", "cadence": "daily", "horizon": 21, "lag": 1, "metrics": {"cagr": 0.1}}]}),
        encoding="utf-8",
    )
    snapshot_manifest = Path("data/snapshot/MANIFEST.csv")
    import hashlib

    manifest_sha = hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest()
    (data / "build-manifest.json").write_text(
        json.dumps({"schema_version": 1, "data_as_of": "2026-10-05", "source": {"revision": "abc"}, "snapshot": {"manifest_sha256": manifest_sha}}),
        encoding="utf-8",
    )
    stamp_outputs(root)
    return root


def test_verify_and_check_cli_round_trip(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path / "dist")
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(cli, "dist_dir", lambda: dist)
    monkeypatch.setattr(cli, "user_dir", lambda: user)
    monkeypatch.setattr(rc, "_eastern_today", lambda: date(2026, 12, 1))
    monkeypatch.setattr(rc, "repo_root", lambda: tmp_path)

    res = RUNNER.invoke(cli.app, ["check"])
    assert res.exit_code == 0, res.output
    assert "First check. Signal is G" in res.output
    assert "Release day: Jobs report for 2026-11 on 2026-12-04" in res.output

    # Writing alert.json and provenance.json must not invalidate tsp verify.
    write_provenance_badge(dist, Path("data/snapshot"))
    verify_res = RUNNER.invoke(cli.app, ["verify", "--dist", str(dist)])
    assert verify_res.exit_code == 0, verify_res.output
    payload = json.loads(verify_res.stdout)
    assert payload["ok"] is True
    assert verify_build_manifest(dist, Path("data/snapshot"))["ok"] is True

    # Tampering fails closed.
    (dist / "index.html").write_text("<html>tampered</html>", encoding="utf-8")
    bad_res = RUNNER.invoke(cli.app, ["verify", "--dist", str(dist)])
    assert bad_res.exit_code == 1
    assert json.loads(bad_res.stdout)["ok"] is False


def test_reproduce_cli_handles_missing_reference_and_success(tmp_path, monkeypatch):
    missing = tmp_path / "missing-dist"
    work = tmp_path / "work"
    err = RUNNER.invoke(cli.app, ["reproduce", "--reference", str(missing), "--work-dir", str(work)])
    assert err.exit_code == 1
    assert "Cannot reproduce build" in err.output

    same = RUNNER.invoke(cli.app, ["reproduce", "--reference", str(work), "--work-dir", str(work)])
    assert same.exit_code == 2

    ref = _fake_dist(tmp_path / "ref")

    def fake_run_build():
        import os

        target = Path(os.environ["TSP_DIST_DIR"])
        _fake_dist(target)
        # Differ only in volatile elapsed_seconds.
        (target / "data" / "meta.json").write_text(json.dumps({"schema_version": 1, "elapsed_seconds": 42.0}), encoding="utf-8")
        stamp_outputs(target)
        return {"dist": str(target)}

    monkeypatch.setattr("tsppredictor.build.run_build", fake_run_build)
    ok = RUNNER.invoke(cli.app, ["reproduce", "--reference", str(ref), "--work-dir", str(work)])
    assert ok.exit_code == 0, ok.output
    assert json.loads(ok.stdout)["reproduced"] is True


def test_journal_and_ift_and_export_cli_end_to_end(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path / "dist")
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(cli, "dist_dir", lambda: dist)
    monkeypatch.setattr(cli, "user_dir", lambda: user)

    add1 = RUNNER.invoke(
        cli.app,
        ["journal", "add", "--date", "2024-01-05", "--fund", "C", "--reason", "trend", "--confidence", "0.8", "--tags", "IFT Limit,news"],
    )
    assert add1.exit_code == 0, add1.output
    add2 = RUNNER.invoke(
        cli.app,
        ["journal", "add", "--date", "2024-02-05", "--fund", "G", "--reason", "cautious", "--confidence", "0.4", "--tags", "defensive"],
    )
    assert add2.exit_code == 0, add2.output

    # Tag filtering + whitespace edge case + invalid overlong tag
    listed = RUNNER.invoke(cli.app, ["journal", "list", "--tag", "ift limit"])
    assert listed.exit_code == 0, listed.output
    assert NOT_ADVICE in listed.output
    items = json.loads(listed.stdout.split(NOT_ADVICE)[0])
    assert len(items) == 1 and items[0]["fund"] == "C"
    assert items[0]["outcome"]["21d"]["status"] == "complete"

    blank_tag = RUNNER.invoke(cli.app, ["journal", "list", "--tag", "   "])
    assert blank_tag.exit_code == 0, blank_tag.output
    all_items = json.loads(blank_tag.stdout.split(NOT_ADVICE)[0])
    assert len(all_items) == 2

    long_tag = RUNNER.invoke(cli.app, ["journal", "list", "--tag", "x" * 41])
    assert long_tag.exit_code == 1

    review = RUNNER.invoke(cli.app, ["journal", "review", "--month", "2024-01"])
    assert review.exit_code == 0, review.output
    assert "Decision journal review - 2024-01" in review.output

    card_path = tmp_path / "nested" / "card.html"
    cal = RUNNER.invoke(cli.app, ["journal", "calibration", "--html", str(card_path)])
    assert cal.exit_code == 0, cal.output
    assert card_path.exists() and "Calibration card" in card_path.read_text(encoding="utf-8")

    exported = tmp_path / "journal.json"
    assert RUNNER.invoke(cli.app, ["journal", "export", "--path", str(exported)]).exit_code == 0
    stats = RUNNER.invoke(cli.app, ["journal", "stats", "--path", str(exported)])
    assert stats.exit_code == 0 and json.loads(stats.stdout)["count"] == 2
    diff = RUNNER.invoke(cli.app, ["journal", "diff", "--path", str(exported)])
    assert diff.exit_code == 0 and len(json.loads(diff.stdout)["identical"]) == 2
    preview = RUNNER.invoke(cli.app, ["journal", "preview", "--path", str(exported)])
    assert preview.exit_code == 0 and len(json.loads(preview.stdout)["duplicate_ids"]) == 2

    # Mutate exported entry and import with --on-conflict prefer-incoming
    doc = json.loads(exported.read_text(encoding="utf-8"))
    doc["entries"][0]["reason"] = "updated reason"
    exported.write_text(json.dumps(doc), encoding="utf-8")
    imp = RUNNER.invoke(cli.app, ["journal", "import", "--path", str(exported), "--on-conflict", "prefer-incoming"])
    assert imp.exit_code == 0, imp.output
    assert json.loads(imp.stdout)["replaced"] == 1

    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    synced = RUNNER.invoke(cli.app, ["journal", "sync", "--folder", str(sync_dir)])
    assert synced.exit_code == 0 and json.loads(synced.stdout)["exported"] == 2

    # IFT diary CLI
    log1 = RUNNER.invoke(cli.app, ["ift", "log", "--date", "2024-03-04", "--from", "100 G", "--to", "100 C", "--reason", "trend"])
    assert log1.exit_code == 0, log1.output
    log2 = RUNNER.invoke(cli.app, ["ift", "log", "--date", "2024-03-11", "--from", "100 C", "--to", "100 S", "--reason", "rot"])
    assert log2.exit_code == 0, log2.output
    blocked = RUNNER.invoke(cli.app, ["ift", "log", "--date", "2024-03-18", "--from", "100 S", "--to", "100 I", "--reason", "no"])
    assert blocked.exit_code == 1
    summary = RUNNER.invoke(cli.app, ["ift", "summary", "--month", "2024-03"])
    assert summary.exit_code == 0 and json.loads(summary.stdout)["unrestricted_left"] == 0

    # Exports
    vault = tmp_path / "vault"
    obs = RUNNER.invoke(cli.app, ["export", "obsidian", "--vault", str(vault)])
    assert obs.exit_code == 0 and json.loads(obs.stdout)["notes"] == 2
    ev_dir = tmp_path / "evidence"
    ev = RUNNER.invoke(cli.app, ["export", "evidence", "--output", str(ev_dir)])
    assert ev.exit_code == 0 and json.loads(ev.stdout)["rows"] == 1
    bad_ls = RUNNER.invoke(cli.app, ["export", "localsend", "--host", "8.8.8.8"])
    assert bad_ls.exit_code == 1


def test_filter_by_tag_whitespace_returns_all():
    e1 = new_entry(decision_date="2024-01-02", fund="C", tags=["news"])
    e2 = new_entry(decision_date="2024-01-03", fund="G")
    assert len(filter_by_tag([e1, e2], "   ")) == 2
    assert filter_by_tag([e1, e2], "NEWS") == [e1]


def test_upcoming_display_sorted_when_schedule_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "repo_root", lambda: tmp_path)
    rows, status = rc.upcoming_display(today=date(2026, 10, 30), days=20)
    assert status["state"] == "missing"
    assert [r.release_date for r in rows] == sorted(r.release_date for r in rows)
    assert len(rows) >= 2


def test_vintage_replay_with_first_print_cache(snap):
    from tsppredictor.vintage_replay import replay

    bls = snap.bls.copy()
    first_print = {
        "CPIAUCSL": pd.DataFrame({"month": bls["month"].astype(str).str.slice(0, 7), "value": pd.to_numeric(bls["cpi_u_sa"], errors="coerce")}).dropna(),
        "UNRATE": pd.DataFrame({"month": bls["month"].astype(str).str.slice(0, 7), "value": pd.to_numeric(bls["unemployment_rate_sa"], errors="coerce")}).dropna(),
    }
    res = replay(snap, first_print=first_print)
    assert res["available"] is True
    assert len(res["rows"]) >= 3
    assert all(row["months_with_different_holdings"] == 0 for row in res["rows"])
    cli_res = RUNNER.invoke(cli.app, ["vintage-replay"])
    assert cli_res.exit_code == 0 and "gap_report" in json.loads(cli_res.stdout)
