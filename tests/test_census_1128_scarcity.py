"""Census fixes, Nov 28 2026: 12.10 (Label Truth) in studies.scarcity_upper_bound."""
from __future__ import annotations

import numpy as np

from tsppredictor.studies import scarcity_upper_bound


def test_scarcity_label_matches_the_5pct_quantile():
    rets = np.linspace(-0.05, 0.05, 100)
    raw = np.tile([0.0, 0.0, 1.0, 0.0, 0.0], (100, 1))
    held = np.tile([1.0, 0.0, 0.0, 0.0, 0.0], (100, 1))
    out = scarcity_upper_bound(raw, held, rets)
    assert out["worst_5pct_sessions"] == 5
    assert out["quantile"] == 0.05
    assert "worst_decile_sessions" not in out
    assert "decile" not in out["note"]
    assert out["of_which_limit_kept_more_g"] == 5
