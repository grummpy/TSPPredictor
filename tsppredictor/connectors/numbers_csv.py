"""Apple Numbers CSV: one-click export of the History lab month range.

Numbers opens UTF-8 CSV with a byte-order mark cleanly and keeps the header row.
Percent values are written as plain numbers (e.g. 1.23 for 1.23%).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path


def history_rows(monthly_history: dict, start: str, end: str, funds: list[str] | None = None) -> list[dict]:
    months = monthly_history.get("months", [])
    if start > end:
        raise ValueError("start month must not be after end month")
    picked = [i for i, m in enumerate(months) if start <= m <= end]
    if not picked:
        raise ValueError(f"no months between {start} and {end}")
    all_funds = monthly_history.get("funds", {})
    funds = funds or list(all_funds)
    unknown = [f for f in funds if f not in all_funds]
    if unknown:
        raise KeyError(f"unknown fund(s): {unknown}")
    rows = []
    for i in picked:
        row = {"Month": months[i]}
        for f in funds:
            value = all_funds[f]["return_pct"][i]
            row[f"{all_funds[f].get('label', f)} return %"] = "" if value is None else value
        rows.append(row)
    return rows


def numbers_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff".encode() + buf.getvalue().encode("utf-8")


def export_numbers(dist: Path, out: Path, start: str, end: str, funds: list[str] | None = None) -> dict:
    history = json.loads((Path(dist) / "data" / "monthly-history.json").read_text(encoding="utf-8"))
    rows = history_rows(history, start, end, funds)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(numbers_csv(rows))
    return {"path": str(out), "rows": len(rows), "columns": list(rows[0].keys())}
