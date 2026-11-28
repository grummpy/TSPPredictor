"""Census fixes, Nov 28 2026: 12.8 (Direct Overwrite) and 12.10 (Label Truth) in connectors/profiling.py."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from tsppredictor.connectors import profiling


def _profile(std: float) -> dict:
    return {"C": {"count": 100, "last": 1.0, "ret_mean": 0.0, "ret_std": std}}


def test_volatility_flag_threshold_is_fourth_root_of_z():
    """Docstring now says z**(1/4)-fold; check the code does exactly that (z=4 -> ~1.41x)."""
    flagged = profiling.compare(_profile(0.01), _profile(0.015))
    assert [f["flag"] for f in flagged] == ["volatility_shift"]
    assert profiling.compare(_profile(0.01), _profile(0.013)) == []
    assert profiling.compare(_profile(0.015), _profile(0.01))  # downward moves count too
    assert "z**(1/4)" in profiling.compare.__doc__


def test_profile_snapshot_writes_atomically(tmp_path, monkeypatch):
    store = tmp_path / "price_profile.json"
    store.write_text(json.dumps(_profile(0.01)), encoding="utf-8")
    prices = pd.DataFrame({"C": np.linspace(10.0, 12.0, 50)})
    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((os.path.basename(src), os.path.basename(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(profiling.os, "replace", spy)
    profiling.profile_snapshot(prices, store=store)
    assert replaced and replaced[0][1] == "price_profile.json" and replaced[0][0].endswith(".tmp")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["price_profile.json"]
    assert json.loads(store.read_text(encoding="utf-8"))["C"]["count"] == 50


def test_failed_profile_write_keeps_previous_profile(tmp_path, monkeypatch):
    store = tmp_path / "price_profile.json"
    store.write_text(json.dumps(_profile(0.01)), encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(profiling.os, "replace", boom)
    try:
        profiling.profile_snapshot(pd.DataFrame({"C": np.linspace(10.0, 12.0, 50)}), store=store)
    except OSError:
        pass
    assert json.loads(store.read_text(encoding="utf-8")) == _profile(0.01)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["price_profile.json"]
