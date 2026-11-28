"""Nov 27 2026 add-on programs.

Each add-on reads the local snapshot, the cache, or the built ``dist/`` data and
writes local files only. Pages go to ``dist/addons/`` and load the bundled
Plotly from ``dist/vendor``; nothing is fetched from the network.
"""

from __future__ import annotations

import html
import json
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tsppredictor import NOT_ADVICE
from tsppredictor.calendar import project_tsp_days

# --- shared page shell ----------------------------------------------------

def _page(title: str, body: str, script: str = "", plotly: bool = True) -> str:
    vendor = '<script src="../vendor/plotly.min.js"></script>' if plotly else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)} · TSP Predictor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="../app.css"></head>
<body><main class="addon"><p><a href="../index.html">Back to the dashboard</a></p>
<h1>{html.escape(title)}</h1>
<p class="banner">{html.escape(NOT_ADVICE)}</p>
{body}
</main>{vendor}<script>{script}</script></body></html>
"""


def _json_for_script(payload) -> str:
    return json.dumps(payload, sort_keys=True).replace("</", "<\\/")


# --- 1 Data Drift Card ----------------------------------------------------

def data_drift_card(meta: dict) -> dict:
    """Card model: current price-profile flags, each with a plain sentence."""
    from tsppredictor.connectors.profiling import explain_flag

    flags = meta.get("price_profile_flags") or []
    return {"count": len(flags), "items": [{**f, "sentence": explain_flag(f)} for f in flags],
            "baseline_data_as_of": (meta.get("price_profile") or {}).get("baseline_data_as_of"),
            "acknowledge": {"method": "POST", "path": "/api/profile/acknowledge", "header": "X-TSP-Local"}}


def data_drift_page(card: dict) -> str:
    rows = "".join(f"<li><strong>{html.escape(str(i['fund']))}</strong> {html.escape(i['sentence'])}</li>" for i in card["items"])
    body = (f"<p>{card['count']} flag(s) against the profile acknowledged on "
            f"{html.escape(str(card['baseline_data_as_of'] or 'the first build'))}.</p>"
            f"<ul id='flags'>{rows or '<li>No flags. The price data looks like the acknowledged profile.</li>'}</ul>"
            "<button id='ack' type='button'>Acknowledge these flags</button> <span id='ack-status' aria-live='polite'></span>"
            "<p class='muted'>Acknowledge works when the dashboard is opened through <code>tsp serve</code>. "
            "It makes the latest profile the new baseline; the next <code>tsp build</code> drops these flags.</p>")
    script = """document.getElementById('ack').onclick=async()=>{const s=document.getElementById('ack-status');
try{const r=await fetch('/api/profile/acknowledge',{method:'POST',headers:{'X-TSP-Local':'1'}});const j=await r.json();
s.textContent=j.acknowledged?('Acknowledged. Run tsp build to refresh.'):('Not acknowledged: '+(j.reason||r.status));}
catch(e){s.textContent='Open this page through tsp serve to acknowledge.';}};"""
    return _page("Data Drift Card", body, script, plotly=False)


# --- 2 Profile Timeline ---------------------------------------------------

def profile_timeline(history: list[dict]) -> dict:
    """Return volatility for each fund across saved profiles (oldest first)."""
    labels, series = [], {}
    for i, record in enumerate(history):
        labels.append(record.get("data_as_of") or f"profile {i + 1}")
        merged = {**(record.get("funds") or {}), **(record.get("l_funds") or {})}
        for fund in merged:
            series.setdefault(fund, [None] * i)
        for fund, values in series.items():
            std = (merged.get(fund) or {}).get("ret_std")
            values.append(None if std is None else round(float(std), 8))
    return {"labels": labels, "series": series, "n": len(labels)}


def profile_timeline_page(timeline: dict) -> str:
    body = "<div id='chart' class='chart' role='img' aria-label='Daily return volatility by saved profile'></div>"
    script = f"""const t={_json_for_script(timeline)};
Plotly.newPlot('chart',Object.entries(t.series).map(([k,v])=>({{x:t.labels,y:v,name:k,mode:'lines+markers'}})),
{{yaxis:{{title:'Std of daily returns'}},xaxis:{{title:'Saved profile (data as of)'}}}},{{displayModeBar:false}});"""
    return _page("Profile Timeline", body, script)


# --- 3 GPR Spike Explorer -------------------------------------------------

def spike_explorer(prices: pd.DataFrame, spikes: dict, pre: int = 20, post: int = 60) -> dict:
    from tsppredictor.studies import spike_paths

    out = []
    for d in spikes.get("spike_dates", []):
        try:
            out.append(spike_paths(prices, d, pre=pre, post=post))
        except ValueError:
            continue
    return {"spikes": out, "offsets": list(range(-pre, post + 1)), "note": spikes.get("note", "")}


def spike_explorer_page(data: dict) -> str:
    body = ("<label>Spike date <select id='pick'></select></label>"
            "<div id='chart' class='chart' role='img' aria-label='G, C and F around the chosen GPR spike'></div>"
            f"<p class='muted'>{html.escape(data.get('note', ''))}</p><p id='filled' class='muted'></p>")
    script = f"""const d={_json_for_script(data)};const sel=document.getElementById('pick');
d.spikes.forEach((s,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=s.date;sel.appendChild(o);}});
function paint(){{const s=d.spikes[sel.value];if(!s)return;
Plotly.newPlot('chart',Object.entries(s.funds).map(([k,v])=>({{x:s.offsets,y:v.path,name:k}})),{{xaxis:{{title:'Sessions from spike'}},yaxis:{{title:'Cumulative return',tickformat:'.1%'}}}},{{displayModeBar:false}});
document.getElementById('filled').textContent='Filled sessions (missing returns set to 0): '+Object.entries(s.funds).map(([k,v])=>k+' '+v.filled_sessions).join(', ');}}
sel.onchange=paint;paint();"""
    return _page("GPR Spike Explorer", body, script)


# --- 4 Rate-Rise Window Atlas ---------------------------------------------

RATE_RISE_WINDOWS = (
    ("rate_shock_1994", "monthly", "1994-01", "1994-12"),
    ("taper_2013", "daily", "2013-05-22", "2013-12-31"),
    ("hiking_2022", "daily", "2022-01-03", "2022-12-30"),
)


def rate_rise_atlas(prices: pd.DataFrame, monthly: pd.DataFrame) -> dict:
    """G versus F wealth paths for the 1994, 2013 and 2022 rate-rise windows."""
    panels = []
    for wid, cadence, start, end in RATE_RISE_WINDOWS:
        if cadence == "daily":
            mask = (prices.index >= pd.Timestamp(start)) & (prices.index <= pd.Timestamp(end))
            px = prices.loc[mask, ["G", "F"]].dropna()
            if len(px) < 2:
                continue
            wealth = px / px.iloc[0]
            x = [ts.strftime("%Y-%m-%d") for ts in wealth.index]
            paths = {f: [round(float(v), 6) for v in wealth[f]] for f in ("G", "F")}
        else:
            month = monthly["month"].astype(str).str.slice(0, 7)
            mask = (month >= start) & (month <= end)
            x = month[mask].tolist()
            paths = {}
            for src, f in (("G Fund", "G"), ("F Fund", "F")):
                rets = pd.to_numeric(monthly.loc[mask, src], errors="coerce").fillna(0).to_numpy(dtype=float) / 100
                paths[f] = [round(float(v), 6) for v in np.cumprod(1 + rets)]
            if len(x) < 2:
                continue
        panels.append({"id": wid, "cadence": cadence, "x": x, "paths": paths,
                       "end": {f: round(paths[f][-1] - 1, 6) for f in paths}})
    return {"panels": panels, "note": "Buy-and-hold wealth rebased to 1 at the start of each window. History, not a forecast."}


def rate_rise_page(atlas: dict) -> str:
    divs = "".join(f"<section><h2>{html.escape(p['id'])}</h2><div id='c{i}' class='chart' role='img' "
                   f"aria-label='G versus F in {html.escape(p['id'])}'></div></section>" for i, p in enumerate(atlas["panels"]))
    body = f"<div class='atlas' style='display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem'>{divs}</div><p class='muted'>{html.escape(atlas['note'])}</p>"
    script = f"""const a={_json_for_script(atlas)};
a.panels.forEach((p,i)=>Plotly.newPlot('c'+i,['G','F'].map(f=>({{x:p.x,y:p.paths[f],name:f}})),{{yaxis:{{title:'Wealth'}}}},{{displayModeBar:false}}));"""
    return _page("Rate-Rise Window Atlas", body, script)


# --- 5 Restatement Alarm --------------------------------------------------

def restatement_alarm(prices: pd.DataFrame, store: Path | None = None) -> dict:
    """Compare the acknowledged baseline's history digest with today's prices."""
    from tsppredictor.connectors.profiling import restatement_flags
    from tsppredictor.paths import cache_dir

    store = store or (cache_dir() / "price_profile.json")
    if not store.exists():
        return {"checked": False, "restated": False, "reason": "no baseline yet; run tsp build"}
    baseline = json.loads(store.read_text(encoding="utf-8"))
    if not baseline.get("_digest"):
        return {"checked": False, "restated": False, "reason": "baseline predates history digests; run tsp profile acknowledge after a build"}
    flags = restatement_flags(baseline, prices)
    return {"checked": True, "restated": bool(flags), "flags": flags, "rows_checked": baseline["_digest"]["rows"]}


# --- 6 Polars Fast Path Bench ---------------------------------------------

def polars_bench(prices: pd.DataFrame, repeats: int = 5) -> dict:
    """Time the profile step on pandas, and on a Polars frame passed through frames.to_pandas()."""
    from tsppredictor.connectors.frames import available, engine_name, to_pandas
    from tsppredictor.connectors.profiling import profile

    def timed(fn) -> float:
        best = float("inf")
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - t0)
        return round(best * 1000, 3)

    frame = prices.reset_index().rename(columns={prices.index.name or "index": "date"})
    out = {"pandas_ms": timed(lambda: profile(prices)), "repeats": repeats}
    try:
        import polars as pl
    except ImportError:
        out.update({"polars": False, "reason": "polars not installed (pip install polars narwhals)"})
        return out
    if not available():
        out.update({"polars": False, "reason": "narwhals not installed; frames.to_pandas() cannot accept Polars"})
        return out
    pl_frame = pl.from_pandas(frame)
    out["engine"] = engine_name(pl_frame)
    out["convert_ms"] = timed(lambda: to_pandas(pl_frame))
    out["polars_path_ms"] = timed(lambda: profile(to_pandas(pl_frame).set_index("date")))
    out["polars"] = True
    out["note"] = "Polars only feeds the same pandas profile here, so the conversion cost is what you are measuring."
    return out


# --- 7 Monthly Learning Note (PDF) ----------------------------------------

def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def simple_pdf(lines: list[str], title: str = "TSP Predictor") -> bytes:
    """A one-page Letter PDF of plain text lines (Helvetica). No dependencies."""
    content = ["BT", "/F1 16 Tf", "72 750 Td", f"({_pdf_escape(title)}) Tj", "/F1 10 Tf", "0 -8 Td"]
    for line in lines[:58]:
        content.append("0 -12 Td")
        content.append(f"({_pdf_escape(line[:110])}) Tj")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def monthly_learning_lines(month: str, monthly_history: dict, drift: dict) -> list[str]:
    """What the rules did in ``month`` (YYYY-MM) and how each fund returned. No recommendations."""
    lines = [f"Month: {month}", "What the rules did, not what to buy.", ""]
    months = monthly_history.get("months", [])
    if month in months:
        i = months.index(month)
        lines.append("Official fund returns this month:")
        for fund, data in (monthly_history.get("funds") or {}).items():
            value = (data.get("return_pct") or [None] * len(months))[i]
            lines.append(f"  {data.get('label', fund)}: {'n/a' if value is None else f'{value:+.2f}%'}")
    else:
        lines.append("No official monthly return for this month in the bundled history.")
    lines.append("")
    lines.append("Monthly rule backtests (holdings drift between transfers):")
    for rule, view in sorted((drift.get("rules") or {}).items()):
        active = [s for s in view.get("segments", []) if s["from"][:7] <= month <= s["to"][:7]]
        if not active:
            lines.append(f"  {rule}: no holding period covers this month.")
            continue
        seg = active[-1]
        mix = ", ".join(f"{f} {v:.0%}" for f, v in seg["end_mix"].items() if v >= 0.005)
        moved = "a transfer started this period" if seg["from"][:7] == month else "held from " + seg["from"]
        lines.append(f"  {rule}: {mix or 'no holdings'} ({moved}).")
    lines += ["", NOT_ADVICE]
    return lines


def monthly_learning_note(month: str, dist: Path, out: Path) -> Path:
    data = Path(dist) / "data"
    history = json.loads((data / "monthly-history.json").read_text(encoding="utf-8"))
    drift = json.loads((data / "allocation-drift.json").read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(simple_pdf(monthly_learning_lines(month, history, drift), title=f"TSP Predictor learning note, {month}"))
    return out


# --- 8 Study Caveat Panel -------------------------------------------------

def _walk_notes(node, path: str, out: list[dict]) -> None:
    if isinstance(node, dict):
        note = node.get("note")
        if isinstance(note, str):
            n = node.get("n", node.get("n_events"))
            out.append({"where": path, "note": note, "n": n if isinstance(n, int) else None,
                        "small_sample": "Small samples" in note})
        for key, value in node.items():
            if key != "note":
                _walk_notes(value, f"{path}.{key}" if path else key, out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            label = value.get("id") or value.get("category") if isinstance(value, dict) else None
            _walk_notes(value, f"{path}[{label or i}]", out)


def study_caveats(dist: Path) -> dict:
    """Every study note and sample count from history.json and stress.json in one place."""
    out: list[dict] = []
    for name in ("history.json", "stress.json"):
        path = Path(dist) / "data" / name
        if path.exists():
            _walk_notes(json.loads(path.read_text(encoding="utf-8")), name.removesuffix(".json"), out)
    return {"caveats": out, "small_sample_count": sum(1 for c in out if c["small_sample"])}


def study_caveats_page(caveats: dict) -> str:
    rows = "".join(f"<tr><td>{html.escape(c['where'])}</td><td>{'' if c['n'] is None else c['n']}</td>"
                   f"<td>{html.escape(c['note'])}</td></tr>" for c in caveats["caveats"])
    body = (f"<p>{caveats['small_sample_count']} study note(s) warn about small samples.</p>"
            f"<table class='data-table'><thead><tr><th>Study</th><th>n</th><th>Caveat</th></tr></thead><tbody>{rows}</tbody></table>")
    return _page("Study Caveat Panel", body, plotly=False)


# --- 9 Snapshot Age Badge -------------------------------------------------

def snapshot_age(data_as_of: str, today: date | None = None) -> dict:
    """Projected TSP sessions between the snapshot's last price and today."""
    last = date.fromisoformat(str(data_as_of)[:10])
    today = today or date.today()
    if today <= last:
        return {"sessions": 0, "data_as_of": last.isoformat(), "today": today.isoformat(), "label": "Snapshot is current"}
    sessions = len(project_tsp_days(last + timedelta(days=1), today))
    label = "Snapshot is current" if sessions == 0 else f"Snapshot is {sessions} session{'s' if sessions != 1 else ''} old"
    return {"sessions": sessions, "data_as_of": last.isoformat(), "today": today.isoformat(), "label": label}


# --- 10 Profile Export Bundle ---------------------------------------------

def profile_export_bundle(out: Path, store: Path | None = None, meta: dict | None = None) -> dict:
    """Zip the native profile baseline, saved profiles, the whylogs file and the current flags."""
    from tsppredictor.paths import cache_dir

    store = store or (cache_dir() / "price_profile.json")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        if store.exists():
            z.write(store, "price_profile.json")
            names.append("price_profile.json")
        whylogs = store.with_suffix(".whylogs.bin")
        if whylogs.exists():
            z.write(whylogs, whylogs.name)
            names.append(whylogs.name)
        folder = store.parent / "profiles"
        for path in sorted(folder.glob("profile-*.json")) if folder.exists() else []:
            z.write(path, f"profiles/{path.name}")
            names.append(f"profiles/{path.name}")
        flags = (meta or {}).get("price_profile_flags", [])
        z.writestr("flags.json", json.dumps(flags, indent=2, sort_keys=True))
        names.append("flags.json")
    return {"path": str(out), "files": names}


# --- build hook -----------------------------------------------------------

def write_addon_pages(dist: Path, *, meta: dict, history: list[dict], prices: pd.DataFrame, spikes: dict,
                      monthly: pd.DataFrame) -> list[str]:
    """Write the add-on pages and their data under dist/addons and dist/data."""
    dist = Path(dist)
    folder = dist / "addons"
    folder.mkdir(parents=True, exist_ok=True)
    card = data_drift_card(meta)
    timeline = profile_timeline(history)
    explorer = spike_explorer(prices, spikes)
    atlas = rate_rise_atlas(prices, monthly)
    caveats = study_caveats(dist)
    pages = {
        "data-drift.html": data_drift_page(card),
        "profile-timeline.html": profile_timeline_page(timeline),
        "gpr-spikes.html": spike_explorer_page(explorer),
        "rate-rise-atlas.html": rate_rise_page(atlas),
        "study-caveats.html": study_caveats_page(caveats),
    }
    for name, body in pages.items():
        (folder / name).write_text(body, encoding="utf-8")
    data = dist / "data"
    for name, payload in (("data-drift.json", card), ("profile-timeline.json", timeline), ("gpr-spike-explorer.json", explorer),
                          ("rate-rise-atlas.json", atlas), ("study-caveats.json", caveats)):
        (data / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return sorted(pages)
