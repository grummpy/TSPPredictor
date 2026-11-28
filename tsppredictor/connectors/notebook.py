"""Jupyter export: a notebook that reproduces one study from the built dist/ data.

Writes nbformat 4 JSON by hand (no jupyter dependency). The notebook reads
``dist/data/*.json`` with the standard library and pandas only.
"""

from __future__ import annotations

import json
from pathlib import Path

from tsppredictor import NOT_ADVICE

STUDIES = {
    "gpr_spikes": ("history.json", "gpr_spikes", "Median G, C and F paths around GPR spikes."),
    "seasonality": ("history.json", "seasonality", "Turn-of-month and seasonal return tables."),
    "stress": ("stress.json", "stress", "Named historical stress windows."),
    "g_versus_f": ("stress.json", "g_versus_f", "G versus F through rate-rise windows."),
}


def _cell(kind: str, source: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        cell.update({"execution_count": None, "outputs": []})
    return cell


def study_notebook(study: str, dist: Path) -> dict:
    if study not in STUDIES:
        raise KeyError(f"unknown study {study!r}; choose from {sorted(STUDIES)}")
    file, key, title = STUDIES[study]
    data_path = (Path(dist) / "data" / file).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} is missing; run tsp build first")
    code_load = (
        "import json\nfrom pathlib import Path\nimport pandas as pd\n\n"
        f"DATA = Path({str(data_path)!r})\n"
        f"payload = json.loads(DATA.read_text())[{key!r}]\n"
        "print(payload.get('note', ''))\n"
    )
    if study == "gpr_spikes":
        code_show = ("frame = pd.DataFrame({f: v['median'] for f, v in payload['funds'].items() if v['median']},\n"
                     "                     index=payload['offsets'])\nframe.plot(title='Median path around GPR spikes')\nframe.tail()\n")
    elif study in ("stress", "g_versus_f"):
        code_show = ("rows = [{'window': w['id'], 'fund': f, **s} for w in payload['windows'] for f, s in w['funds'].items()]\n"
                     "pd.DataFrame(rows)\n")
    else:
        code_show = "pd.json_normalize(payload)\n"
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                     "tsppredictor": {"study": study, "source": str(data_path)}},
        "cells": [_cell("markdown", f"# {title}\n\n{NOT_ADVICE}\n"), _cell("code", code_load), _cell("code", code_show)],
    }


def write_notebook(study: str, dist: Path, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(study_notebook(study, dist), indent=1), encoding="utf-8")
    return out
