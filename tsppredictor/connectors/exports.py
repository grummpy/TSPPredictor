"""Obsidian vault and Evidence.dev exports.

* Obsidian: one Markdown note per journal entry, with YAML front matter.
* Evidence.dev: a minimal project (sources + pages) over the backtest tables
  written as CSV, so report pages can be written as SQL plus Markdown.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from tsppredictor import NOT_ADVICE


def export_obsidian(entries: list[dict], vault: Path, folder: str = "TSP Journal") -> dict:
    target = Path(vault) / folder
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for entry in entries:
        # Journal IDs remain stable when a reason, date, or fund is edited.
        # Hash the full ID so file names do not expose imported IDs or contain paths.
        identity = hashlib.sha256(str(entry["id"]).encode("utf-8")).hexdigest()
        name = f"TSP entry {identity}"
        tags = ["tsp-journal", *[str(t) for t in entry.get("tags", [])]]
        body = [
            "---",
            f"id: {entry['id']}",
            f"date: {entry['date']}",
            f"fund: {entry['fund']}",
            f"confidence: {entry['confidence']}",
            "tags: [" + ", ".join(tags) + "]",
            "---",
            "",
            f"# {entry['date']} - {entry['fund']} Fund",
            "",
            entry.get("reason", "") or "_No reason recorded._",
            "",
        ]
        outcome = entry.get("outcome") or {}
        if outcome:
            body += ["## Outcome", ""] + [f"- {k}: {v}" for k, v in outcome.items()] + [""]
        body += [f"> {NOT_ADVICE}", ""]
        (target / f"{name}.md").write_text("\n".join(body), encoding="utf-8")
        written += 1
    return {"vault": str(vault), "folder": folder, "notes": written}


def export_evidence_project(scoreboard_rows: list[dict], output: Path) -> dict:
    """Write an Evidence.dev project skeleton over the scoreboard table."""
    output = Path(output)
    source_dir = output / "sources" / "tsp"
    pages = output / "pages"
    source_dir.mkdir(parents=True, exist_ok=True)
    pages.mkdir(parents=True, exist_ok=True)
    fields = ["id", "name", "cadence", "horizon", "lag", "cagr", "max_drawdown", "sharpe", "excess_cagr_vs_bh_c"]
    with (source_dir / "scoreboard.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in scoreboard_rows:
            metrics = row.get("metrics") or {}
            writer.writerow({
                "id": row.get("id"), "name": row.get("name"), "cadence": row.get("cadence"),
                "horizon": row.get("horizon"), "lag": row.get("lag"), "cagr": metrics.get("cagr"),
                "max_drawdown": metrics.get("max_drawdown"), "sharpe": metrics.get("sharpe"),
                "excess_cagr_vs_bh_c": ((row.get("versus") or {}).get("bh_c") or {}).get("excess_cagr"),
            })
    (source_dir / "connection.yaml").write_text("name: tsp\ntype: csv\noptions: {}\n", encoding="utf-8")
    (pages / "index.md").write_text(
        "---\ntitle: TSP Predictor backtests\n---\n\n"
        f"> {NOT_ADVICE}\n\n"
        "```sql scoreboard\nselect * from tsp.scoreboard order by cadence, horizon, lag, cagr desc\n```\n\n"
        "<DataTable data={scoreboard}/>\n\n"
        "```sql lag_cost\nselect a.name, a.cadence, a.horizon, a.cagr - b.cagr as cagr_lost_lag2\n"
        "from tsp.scoreboard a join tsp.scoreboard b on a.id = b.id and a.cadence = b.cadence\n"
        " and a.horizon = b.horizon and a.lag = 1 and b.lag = 2\n```\n\n"
        "<BarChart data={lag_cost} x=name y=cagr_lost_lag2/>\n",
        encoding="utf-8",
    )
    (output / "package.json").write_text(json.dumps({
        "name": "tsp-predictor-evidence", "private": True,
        "scripts": {"dev": "evidence dev", "build": "evidence build", "sources": "evidence sources"},
        "dependencies": {"@evidence-dev/evidence": "latest", "@evidence-dev/csv": "latest"},
    }, indent=2), encoding="utf-8")
    return {"project": str(output), "rows": len(scoreboard_rows)}
