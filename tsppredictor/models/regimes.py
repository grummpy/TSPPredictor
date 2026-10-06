"""Rule regimes, plus an optional Gaussian mixture refit on past data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture


def rule_regime_labels(features: pd.DataFrame) -> pd.Series:
    trend = np.where(features["c_above_sma200"].fillna(0).to_numpy() > 0.5, "Uptrend", "Downtrend")
    vol = features["c_vol_pct"]
    # Before the expanding window fills, treat volatility as not high.
    high = np.where(vol.fillna(0).to_numpy() >= 0.70, "High vol", "Low vol")
    curve = np.where(features["curve_inverted"].fillna(0).to_numpy() > 0.5, "Inverted curve", "Normal curve")
    labels = pd.Series([f"{a} · {b} · {c}" for a, b, c in zip(trend, high, curve, strict=False)], index=features.index)
    unknown = features["c_above_sma200"].isna() | features["spread_10y_3m"].isna()
    labels = labels.mask(unknown, "Unavailable")
    return labels


def relabel_by_volatility(labels: np.ndarray, vol: np.ndarray) -> np.ndarray:
    """Order state ids so 0 is the lowest mean volatility. Same inputs, same output."""
    labels = np.asarray(labels).astype(int)
    vol = np.asarray(vol, dtype=float)
    states = sorted(set(labels.tolist()))
    means = []
    for state in states:
        sample = vol[labels == state]
        sample = sample[np.isfinite(sample)]
        means.append(float(np.mean(sample)) if len(sample) else np.inf)
    order = np.argsort(np.asarray(means))
    remap = {int(states[int(old_pos)]): new for new, old_pos in enumerate(order)}
    return np.array([remap[int(value)] for value in labels], dtype=int)


def fit_gmm_states(features: np.ndarray, vol: np.ndarray, n_states: int = 3, seed: int = 0) -> np.ndarray:
    """Fit a mixture and return volatility-ordered labels. ``features`` rows align with ``vol``."""
    model = GaussianMixture(
        n_components=n_states,
        covariance_type="full",
        random_state=seed,
        n_init=1,
        reg_covar=1e-5,
        max_iter=200,
    )
    model.fit(features)
    raw = model.predict(features)
    return relabel_by_volatility(raw, vol)


def walk_forward_gmm(frame: pd.DataFrame, seed: int = 0) -> pd.Series:
    """Refit at each January on rows strictly before that January, then label the year.

    States are ordered by mean realized volatility inside the training window.
    """
    cols = ["c_rv63", "c_dd", "spread_10y_3m", "vol_level"]
    work = frame[cols].replace([np.inf, -np.inf], np.nan).dropna()
    labels = pd.Series(np.nan, index=frame.index, dtype=float)
    if len(work) < 400:
        return labels
    years = sorted(set(work.index.year))
    for year in years:
        train = work[work.index.year < year]
        test = work[work.index.year == year]
        if len(train) < 400 or test.empty:
            continue
        model = GaussianMixture(
            n_components=3,
            covariance_type="full",
            random_state=seed,
            n_init=1,
            reg_covar=1e-5,
            max_iter=200,
        )
        model.fit(train.to_numpy(dtype=float))
        train_raw = model.predict(train.to_numpy(dtype=float))
        train_ordered = relabel_by_volatility(train_raw, train["c_rv63"].to_numpy(dtype=float))
        # Map raw component -> ordered id using the training relabel.
        mapping = {}
        for raw, ordered in zip(train_raw, train_ordered, strict=False):
            mapping[int(raw)] = int(ordered)
        test_raw = model.predict(test.to_numpy(dtype=float))
        labels.loc[test.index] = [mapping[int(v)] for v in test_raw]
    return labels
