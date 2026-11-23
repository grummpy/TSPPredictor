"""What journal decisions actually did: outcomes, calibration, reviews, IFT diary.

Everything here is a historical look-back over the local journal and bundled
share prices.  It is educational, never advice, and never contacts TSP.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tsppredictor import NOT_ADVICE

OUTCOME_HORIZONS = (21, 63)
CONFIDENCE_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0001))


def entry_outcome(entry: Mapping, days: int, prices: pd.DataFrame) -> dict:
    """The chosen fund's return over the next ``days`` trading days after the decision.

    The window runs from the last close at or before the decision date to the
    close ``days`` sessions later, and also reports the G Fund over the same
    window plus whether the fund beat G.
    """
    index = pd.DatetimeIndex(prices.index)
    decided = pd.Timestamp(entry["date"])
    start = int(index.searchsorted(decided, side="right"))
    fund = entry["fund"]
    if start == 0:
        return {"days": days, "status": "no_price", "fund": fund, "return": None, "g_return": None, "beat_g": None}
    base_i = start - 1  # last close at or before the decision
    end = base_i + days
    if end >= len(index):
        return {"days": days, "status": "pending", "fund": fund, "return": None, "g_return": None, "beat_g": None}
    px = prices[fund].to_numpy(dtype=float)
    gx = prices["G"].to_numpy(dtype=float)
    if not (np.isfinite(px[base_i]) and np.isfinite(px[end])):
        return {"days": days, "status": "no_price", "fund": fund, "return": None, "g_return": None, "beat_g": None}
    ret = float(px[end] / px[base_i] - 1.0)
    g_ret = float(gx[end] / gx[base_i] - 1.0)
    return {"days": days, "status": "complete", "fund": fund, "from": str(index[base_i].date()),
            "to": str(index[end].date()), "return": ret, "g_return": g_ret, "beat_g": ret > g_ret}


def with_outcomes(entries: Iterable[Mapping], prices: pd.DataFrame,
                  horizons: tuple[int, ...] = OUTCOME_HORIZONS) -> list[dict]:
    """Journal Outcome Column: each entry plus its 21- and 63-session outcome."""
    out = []
    for entry in entries:
        row = dict(entry)
        row["outcome"] = {f"{h}d": entry_outcome(entry, h, prices) for h in horizons}
        out.append(row)
    return out


def confidence_calibration(entries: Iterable[Mapping], prices: pd.DataFrame, days: int = 21) -> dict:
    """Hit rate (fund beat G over ``days``) grouped by the confidence you gave."""
    bins = []
    rows = [(float(e["confidence"]), entry_outcome(e, days, prices)) for e in entries]
    for low, high in CONFIDENCE_BINS:
        members = [o for c, o in rows if low <= c < high and o["status"] == "complete"]
        hits = sum(1 for o in members if o["beat_g"])
        stated = [c for c, o in rows if low <= c < high and o["status"] == "complete"]
        bins.append({"confidence_from": low, "confidence_to": min(high, 1.0), "n": len(members),
                     "hit_rate": hits / len(members) if members else None,
                     "mean_stated_confidence": float(np.mean(stated)) if stated else None})
    complete = [o for _c, o in rows if o["status"] == "complete"]
    return {"kind": "confidence_calibration", "days": days, "bins": bins, "n_complete": len(complete),
            "n_pending": sum(1 for _c, o in rows if o["status"] != "complete"),
            "note": "A hit means the chosen fund beat the G Fund over the window. Small samples are noisy."}


def monthly_review(entries: Iterable[Mapping], prices: pd.DataFrame, month: str) -> dict:
    """Decision Journal Reviewer: every entry in ``month`` and how it turned out."""
    rows = [e for e in with_outcomes(entries, prices) if str(e["date"]).startswith(month)]
    complete = [e for e in rows if e["outcome"]["21d"]["status"] == "complete"]
    beat = sum(1 for e in complete if e["outcome"]["21d"]["beat_g"])
    lines = [f"# Decision journal review - {month}", ""]
    for e in rows:
        o21, o63 = e["outcome"]["21d"], e["outcome"]["63d"]

        def pct(o):
            return "pending" if o["return"] is None else f"{o['return'] * 100:+.2f}% (G {o['g_return'] * 100:+.2f}%)"

        lines.append(f"- {e['date']} {e['fund']} (confidence {e['confidence']:.2f}): 21d {pct(o21)}, 63d {pct(o63)}"
                     + (f" - {e['reason']}" if e.get("reason") else ""))
    if not rows:
        lines.append("- No entries this month.")
    lines += ["", f"{beat} of {len(complete)} completed decisions beat G over 21 sessions.", "", f"> {NOT_ADVICE}"]
    return {"month": month, "entries": rows, "beat_g_21d": beat, "complete_21d": len(complete),
            "markdown": "\n".join(lines)}


def calibration_card_html(calibration: Mapping) -> str:
    """Calibration Card: one printable HTML page."""
    rows = "".join(
        f"<tr><td>{b['confidence_from']:.2f}-{b['confidence_to']:.2f}</td><td>{b['n']}</td>"
        f"<td>{'-' if b['hit_rate'] is None else f'{b['hit_rate'] * 100:.0f}%'}</td>"
        f"<td>{'-' if b['mean_stated_confidence'] is None else f'{b['mean_stated_confidence'] * 100:.0f}%'}</td></tr>"
        for b in calibration["bins"]
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Calibration card</title>"
        "<style>body{font-family:system-ui;margin:2rem;max-width:40rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #999;padding:.4rem;text-align:center}</style></head><body>"
        f"<h1>How often were confident calls right?</h1><p>Window: {calibration['days']} trading days. "
        f"Completed: {calibration['n_complete']}, pending: {calibration['n_pending']}.</p>"
        "<table><thead><tr><th>Confidence</th><th>Decisions</th><th>Beat G</th><th>Stated</th></tr></thead>"
        f"<tbody>{rows}</tbody></table><p>{calibration['note']}</p><p><small>{NOT_ADVICE}</small></p></body></html>"
    )


# --- IFT Month Diary --------------------------------------------------------

def _diary_path(user_dir: Path) -> Path:
    return Path(user_dir) / "ift_diary.jsonl"


def _classify_ift_rows(rows: list[dict]) -> list[tuple[int, dict]]:
    """Classify by posting date and use append order for ties on the same date."""
    out = []
    for order, (index, original) in enumerate(sorted(enumerate(rows), key=lambda pair: pair[1]["date"]), 1):
        row = {
            **original,
            "unrestricted_number": order if order <= 2 else None,
            "status": "unrestricted" if order <= 2 else "g_only" if original["g_only"] else "over_limit",
        }
        out.append((index, row))
    return out


def record_ift(user_dir: Path, *, when: date, from_mix: str, to_mix: str, reason: str,
               g_only: bool = False) -> dict:
    """Log one posted transfer, manually flagging if only reallocating to G.

    This is a personal diary only: it never submits or verifies transfers at TSP.
    """
    month = when.strftime("%Y-%m")
    existing = [row for row in read_ift_diary(user_dir) if row["month"] == month]
    old_over_limit = {i for i, old in _classify_ift_rows(existing) if old["status"] == "over_limit"}
    candidate = {"logged_at": datetime.now(UTC).isoformat(), "date": when.isoformat(), "month": month,
                 "from": from_mix, "to": to_mix, "reason": reason, "g_only": bool(g_only)}
    classified = dict(_classify_ift_rows([*existing, candidate]))
    if classified[len(existing)]["status"] == "over_limit":
        raise ValueError(f"{month} already has two unrestricted transfers; only G-only moves remain this month")
    if any(old["status"] == "over_limit" and i not in old_over_limit for i, old in classified.items()):
        raise ValueError("Backdated entry would put an existing transfer over the two unrestricted transfer limit")
    row = classified[len(existing)]
    path = _diary_path(user_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def read_ift_diary(user_dir: Path) -> list[dict]:
    path = _diary_path(user_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ift_month_summary(user_dir: Path, month: str) -> dict:
    rows = [row for row in read_ift_diary(user_dir) if row["month"] == month]
    classified = [row for _, row in _classify_ift_rows(rows)]
    unrestricted = min(2, len(classified))
    return {"month": month, "transfers": classified, "unrestricted_used": unrestricted,
            "unrestricted_left": 2 - unrestricted,
            "over_limit_logged": sum(row["status"] == "over_limit" for row in classified)}


# --- Allocation Drift Viewer ------------------------------------------------

def allocation_drift(weights: np.ndarray, dates: pd.DatetimeIndex, post_dates: Iterable,
                     funds: tuple[str, ...] = ("G", "F", "C", "S", "I")) -> dict:
    """How holdings drifted between transfers: max absolute drift from the posted mix."""
    dates = pd.DatetimeIndex(dates)
    # The posting-day weight applies to that session's returns. The transfer
    # resets the holdings at the close and appears in the following row.
    resets = {int(dates.get_loc(pd.Timestamp(d))) + 1 for d in post_dates if pd.Timestamp(d) in dates}
    boundaries = [0, *sorted(resets - {len(dates)}), len(dates)]
    segments = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=False):
        if end - start < 2:
            continue
        anchor = weights[start]
        block = weights[start:end]
        drift = np.abs(block - anchor).max(axis=0)
        segments.append({"from": str(dates[start].date()), "to": str(dates[end - 1].date()),
                         "start_mix": {f: round(float(anchor[i]), 4) for i, f in enumerate(funds)},
                         "end_mix": {f: round(float(block[-1][i]), 4) for i, f in enumerate(funds)},
                         "max_drift": {f: round(float(drift[i]), 4) for i, f in enumerate(funds)}})
    worst = max((max(s["max_drift"].values()) for s in segments), default=0.0)
    return {"kind": "allocation_drift", "segments": segments, "max_drift_any_fund": worst}


def release_context(entry: Mapping, window_days: int = 3) -> list[dict]:
    """Release Day Alerts context: CPI/jobs releases within ``window_days`` before a decision."""
    from datetime import timedelta

    from tsppredictor.data.release_calendar import releases_between

    decided = date.fromisoformat(str(entry["date"]))
    return [{"series": r.series, "reference_month": r.reference_month, "released": r.release_date.isoformat()}
            for r in releases_between(decided - timedelta(days=window_days), decided)]
