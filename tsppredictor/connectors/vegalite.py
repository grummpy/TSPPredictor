"""Vega-Lite specs for the Profile Timeline and the GPR Spike Explorer.

Pure JSON (Vega-Lite v5). Render with any Vega-Lite viewer, Jupyter, or the
Vega editor; nothing here fetches a library.
"""

from __future__ import annotations

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"


def profile_timeline_spec(timeline: dict) -> dict:
    values = [{"profile": label, "fund": fund, "ret_std": series[i]}
              for fund, series in timeline.get("series", {}).items()
              for i, label in enumerate(timeline.get("labels", [])) if i < len(series) and series[i] is not None]
    return {
        "$schema": SCHEMA,
        "description": "Daily return volatility by saved price profile",
        "data": {"values": values},
        "mark": {"type": "line", "point": True},
        "encoding": {
            "x": {"field": "profile", "type": "ordinal", "title": "Saved profile (data as of)"},
            "y": {"field": "ret_std", "type": "quantitative", "title": "Std of daily returns"},
            "color": {"field": "fund", "type": "nominal"},
        },
    }


def spike_explorer_spec(explorer: dict) -> dict:
    values = []
    for spike in explorer.get("spikes", []):
        for fund, data in spike["funds"].items():
            for offset, value in zip(spike["offsets"], data["path"]):
                values.append({"spike": spike["date"], "fund": fund, "offset": offset, "cum_return": value})
    return {
        "$schema": SCHEMA,
        "description": "G, C and F cumulative return around each GPR spike",
        "data": {"values": values},
        "params": [{"name": "spike", "value": values[0]["spike"] if values else None,
                    "bind": {"input": "select", "options": sorted({v["spike"] for v in values})}}],
        "transform": [{"filter": "datum.spike == spike"}],
        "mark": "line",
        "encoding": {
            "x": {"field": "offset", "type": "quantitative", "title": "Sessions from spike"},
            "y": {"field": "cum_return", "type": "quantitative", "title": "Cumulative return", "axis": {"format": ".1%"}},
            "color": {"field": "fund", "type": "nominal"},
        },
    }
