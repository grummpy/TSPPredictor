"""Redash: saved SQL dashboards over a local copy of the journal and run log.

The local side is real: ``export_sqlite`` copies the journal and the run log
into one SQLite file and ``saved_queries`` returns the dashboard SQL. Redash
itself is an outside server (self-hosted); point its SQLite data source at the
file. Nothing here talks to a Redash instance.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SAVED_QUERIES = {
    "decisions_by_fund": "SELECT fund, COUNT(*) AS decisions, AVG(confidence) AS avg_confidence FROM journal GROUP BY fund ORDER BY decisions DESC;",
    "decisions_by_month": "SELECT substr(decision_date, 1, 7) AS month, COUNT(*) AS decisions FROM journal GROUP BY month ORDER BY month;",
    "build_runs": "SELECT at, data_as_of, n_trials, ensemble_cagr FROM runs ORDER BY at DESC LIMIT 50;",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def export_sqlite(out: Path, *, journal: Path, runs: Path) -> dict:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    try:
        con.execute("CREATE TABLE journal (id TEXT, decision_date TEXT, fund TEXT, reason TEXT, confidence REAL, tags TEXT)")
        con.execute("CREATE TABLE runs (at TEXT, data_as_of TEXT, n_trials INTEGER, ensemble_cagr REAL, raw TEXT)")
        j = _read_jsonl(Path(journal))
        con.executemany("INSERT INTO journal VALUES (?,?,?,?,?,?)", [
            (r.get("id"), r.get("decision_date") or r.get("date"), r.get("fund"), r.get("reason"),
             r.get("confidence"), ",".join(r.get("tags") or [])) for r in j])
        rr = _read_jsonl(Path(runs))
        con.executemany("INSERT INTO runs VALUES (?,?,?,?,?)", [
            (r.get("at") or r.get("time"), (r.get("params") or {}).get("data_as_of"), (r.get("params") or {}).get("n_trials"),
             (r.get("metrics") or {}).get("ensemble_cagr"), json.dumps(r, sort_keys=True)) for r in rr])
        con.commit()
    finally:
        con.close()
    return {"path": str(out), "journal_rows": len(j), "run_rows": len(rr), "queries": sorted(SAVED_QUERIES)}


def saved_queries() -> dict[str, str]:
    return dict(SAVED_QUERIES)
