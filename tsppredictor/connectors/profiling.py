"""Profile each price snapshot and flag odd shifts (whylogs when installed).

A compact native profile (per-fund count/mean/std of daily returns, last price,
and a digest of older rows) is always computed.

Baseline and history (Nov 27 2026 pack):

* ``price_profile.json`` is the *acknowledged baseline*. A build compares
  against it but no longer overwrites it, so a flag keeps showing until you
  run ``tsp profile acknowledge`` (or press Acknowledge on the Data Drift card).
  Builds of the same snapshot therefore produce the same flags.
* Every build also saves its profile into ``profiles/`` (last ``KEEP`` kept) for
  the Profile Timeline.
* All writes go through a temp file and ``os.replace``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from tsppredictor.paths import cache_dir

FUNDS = ("G", "F", "C", "S", "I")
KEEP = 24
# A flag when a fund's daily-return volatility is this many times higher or lower
# than in the baseline. 1.414 (the square root of 2) is the threshold the old
# ``log(z)/4`` with z=4 actually applied.
VOLATILITY_RATIO = 1.414
DIGEST_KEEP_LAST = 5


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def history_digest(prices: pd.DataFrame, keep_last: int = DIGEST_KEEP_LAST, rows: int | None = None) -> dict:
    """SHA-256 of every row except the newest ``keep_last`` (or of the first ``rows`` rows).

    Values are rounded to 6 decimals and NaN is written as an empty field, so the
    digest only changes when a stored price actually changes.
    """
    if keep_last < 0:
        raise ValueError("keep_last must be >= 0")
    frame = prices.sort_index()
    n = len(frame) - keep_last if rows is None else min(int(rows), len(frame))
    n = max(n, 0)
    head = frame.iloc[:n]
    h = hashlib.sha256()
    for ts, row in zip(head.index, head.itertuples(index=False)):
        vals = ["" if (v is None or (isinstance(v, float) and math.isnan(v))) else f"{float(v):.6f}" for v in row]
        h.update((pd.Timestamp(ts).strftime("%Y-%m-%d") + "," + ",".join(vals) + "\n").encode())
    return {"rows": int(n), "columns": [str(c) for c in head.columns], "sha256": h.hexdigest()}


def _fund_profile(series: pd.Series) -> dict:
    series = pd.to_numeric(series, errors="coerce").dropna()
    rets = series.pct_change().dropna()
    return {"count": int(series.size), "last": float(series.iloc[-1]) if series.size else None,
            "ret_mean": float(rets.mean()) if rets.size else None,
            "ret_std": float(rets.std(ddof=1)) if rets.size > 1 else None}


def profile(prices: pd.DataFrame) -> dict:
    out = {}
    for fund in FUNDS:
        if fund not in prices.columns:
            continue
        out[fund] = _fund_profile(prices[fund])
    return out


def l_fund_profile(l_frame: pd.DataFrame | None) -> dict:
    """Native profile for every L Fund column (L2050, L Income, ...)."""
    if l_frame is None:
        return {}
    return {str(col): _fund_profile(l_frame[col]) for col in l_frame.columns
            if str(col).startswith("L") and pd.to_numeric(l_frame[col], errors="coerce").notna().any()}


def compare(previous: dict, current: dict, *, volatility_ratio: float = VOLATILITY_RATIO) -> list[dict]:
    """Flags: fewer rows than before, or a return std at least ``volatility_ratio`` times higher or lower."""
    if volatility_ratio <= 1:
        raise ValueError("volatility_ratio must be greater than 1")
    flags = []
    for fund, now in current.items():
        before = previous.get(fund)
        if not before or not isinstance(now, dict) or "count" not in now:
            continue
        if now["count"] < before["count"]:
            flags.append({"fund": fund, "flag": "rows_decreased", "before": before["count"], "now": now["count"]})
        if before.get("ret_std") and now.get("ret_std"):
            ratio = now["ret_std"] / before["ret_std"]
            if abs(np.log(ratio)) > np.log(volatility_ratio):
                flags.append({"fund": fund, "flag": "volatility_shift", "before": before["ret_std"],
                              "now": now["ret_std"], "ratio": round(float(ratio), 4),
                              "threshold": volatility_ratio})
    return flags


def restatement_flags(baseline: dict, prices: pd.DataFrame) -> list[dict]:
    """Compare the baseline's stored digest with the same rows of today's prices."""
    old = (baseline or {}).get("_digest")
    if not old:
        return []
    cols = [c for c in old.get("columns", []) if c in prices.columns]
    if len(cols) != len(old.get("columns", [])):
        return [{"fund": "*", "flag": "history_restated", "detail": "price columns changed"}]
    now = history_digest(prices[cols], rows=old["rows"])
    if now["rows"] < old["rows"]:
        return [{"fund": "*", "flag": "history_restated", "detail": f"only {now['rows']} of {old['rows']} rows remain"}]
    if now["sha256"] != old["sha256"]:
        return [{"fund": "*", "flag": "history_restated", "detail": f"one or more of the first {old['rows']} rows changed"}]
    return []


def explain_flag(flag: dict) -> str:
    """One plain sentence for the dashboard."""
    kind = flag.get("flag")
    fund = flag.get("fund")
    if kind == "rows_decreased":
        return f"The {fund} price history has {flag['now']} rows, fewer than the {flag['before']} in the acknowledged profile. Rows went missing."
    if kind == "volatility_shift":
        ratio = flag.get("ratio") or (flag["now"] / flag["before"])
        direction = "higher" if ratio > 1 else "lower"
        times = ratio if ratio > 1 else 1 / ratio
        return f"{fund} daily-return volatility is {times:.2f} times {direction} than in the acknowledged profile."
    if kind == "history_restated":
        return f"Older prices changed in place since the acknowledged profile ({flag.get('detail', 'digest differs')})."
    return f"{fund}: {kind}."


def _profiles_dir(store: Path) -> Path:
    return store.parent / "profiles"


def _save_history(store: Path, record: dict) -> Path:
    folder = _profiles_dir(store)
    folder.mkdir(parents=True, exist_ok=True)
    body = json.dumps(record, indent=2, sort_keys=True)
    digest = hashlib.sha256(body.encode()).hexdigest()[:12]
    path = folder / f"profile-{record.get('data_as_of') or 'unknown'}-{digest}.json"
    if not path.exists():
        _atomic_write(path, body)
    files = sorted(folder.glob("profile-*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    for old in files[:-KEEP]:
        old.unlink()
    return path


def profile_history(n: int = KEEP, store: Path | None = None) -> list[dict]:
    """The last ``n`` saved price profiles, oldest first."""
    store = store or (cache_dir() / "price_profile.json")
    folder = _profiles_dir(store)
    if not folder.exists():
        return []
    files = sorted(folder.glob("profile-*.json"), key=lambda p: (p.stat().st_mtime, p.name))[-n:] if n > 0 else []
    out = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        record["_file"] = path.name
        out.append(record)
    return out


def acknowledge_flags(store: Path | None = None) -> dict:
    """Make the latest saved profile the new baseline so current flags clear."""
    store = store or (cache_dir() / "price_profile.json")
    history = profile_history(1, store)
    if not history:
        return {"acknowledged": False, "reason": "no saved profile yet; run tsp build"}
    latest = {k: v for k, v in history[-1].items() if k != "_file"}
    baseline = {**latest.get("funds", {}), **latest.get("l_funds", {}), "_digest": latest.get("digest"),
                "_data_as_of": latest.get("data_as_of")}
    _atomic_write(store, json.dumps(baseline, indent=2, sort_keys=True))
    return {"acknowledged": True, "baseline_data_as_of": latest.get("data_as_of"), "cleared": len(latest.get("flags", []))}


def baseline_sha256(store: Path) -> str | None:
    return hashlib.sha256(store.read_bytes()).hexdigest() if store.exists() else None


def profile_snapshot(prices: pd.DataFrame, store: Path | None = None, *, l_frame: pd.DataFrame | None = None,
                     data_as_of: str | None = None) -> dict:
    store = store or (cache_dir() / "price_profile.json")
    current = profile(prices)
    l_current = l_fund_profile(l_frame)
    digest = history_digest(prices)
    previous = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    first = not previous
    flags = [] if first else compare(previous, {**current, **l_current}) + restatement_flags(previous, prices)
    if first:
        # First build: the profile becomes the baseline. Later builds compare against it.
        _atomic_write(store, json.dumps({**current, **l_current, "_digest": digest, "_data_as_of": data_as_of},
                                        indent=2, sort_keys=True))
    record = {"data_as_of": data_as_of, "funds": current, "l_funds": l_current, "digest": digest, "flags": flags}
    _save_history(store, record)
    result = {"kind": "price_profile", "funds": current, "l_funds": l_current, "flags": flags,
              "explanations": [explain_flag(f) for f in flags], "baseline_sha256": baseline_sha256(store),
              "baseline_data_as_of": (previous or {}).get("_data_as_of", data_as_of), "whylogs": False}
    try:
        import whylogs as why
    except ImportError:
        result["whylogs_reason"] = "whylogs not installed"
        return result
    try:
        view = why.log(pandas=prices.reset_index(drop=True)).view()
        view.write(str(store.with_suffix(".whylogs.bin")))
        result["whylogs"] = True
    except Exception as exc:  # noqa: BLE001 - optional add-on must never end the build
        result["whylogs_reason"] = f"whylogs failed: {type(exc).__name__}: {exc}"[:300]
    return result
