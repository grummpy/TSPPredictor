"""Walk-forward logistic regression and gradient boosting.

Scalers, calibration, and the small hyperparameter search are fit inside each
training fold. Calibration uses sigmoid (Platt) on the last year of the fold
via CalibratedClassifierCV around a frozen estimator. Isotonic is not used:
the calibration tail is shorter than 1,000 labels.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.preprocessing import StandardScaler

from tsppredictor.backtest.walkforward import last_train_index

FUNDS = ("G", "F", "C", "S", "I")


def _impute(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    med = np.nanmedian(train, axis=0)
    med = np.where(np.isfinite(med), med, 0.0)
    def fill(block: np.ndarray) -> np.ndarray:
        out = np.array(block, dtype=float, copy=True)
        bad = ~np.isfinite(out)
        if bad.any():
            out[bad] = np.take(med, np.where(bad)[1])
        return out
    return fill(train), fill(other), med


def _align_proba(model, matrix: np.ndarray, classes: tuple[str, ...] = FUNDS) -> np.ndarray:
    raw = model.predict_proba(matrix)
    out = np.zeros((len(matrix), len(classes)))
    model_classes = [str(c) for c in model.classes_]
    for j, name in enumerate(model_classes):
        if name in classes:
            out[:, classes.index(name)] = raw[:, j]
    row_sum = out.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0] = 1.0
    return out / row_sum


def _fit_logistic(x_dev, y_dev, x_cal, y_cal, C: float):
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x_dev)
    clf = LogisticRegression(C=C, max_iter=500, solver="lbfgs", random_state=0)
    clf.fit(x_scaled, y_dev)
    model = clf
    try:
        if len(np.unique(y_cal)) >= 2 and len(y_cal) >= 30:
            calibrated = CalibratedClassifierCV(FrozenEstimator(clf), method="sigmoid")
            calibrated.fit(scaler.transform(x_cal), y_cal)
            model = calibrated
    except Exception:
        model = clf
    return scaler, model, clf


def _fit_hgb(x_dev, y_dev, x_cal, y_cal, depth: int, n_iter: int):
    clf = HistGradientBoostingClassifier(
        max_depth=depth,
        learning_rate=0.08,
        max_iter=n_iter,
        min_samples_leaf=30,
        l2_regularization=0.1,
        early_stopping=False,
        random_state=0,
    )
    clf.fit(x_dev, y_dev)
    model = clf
    try:
        if len(np.unique(y_cal)) >= 2 and len(y_cal) >= 30:
            calibrated = CalibratedClassifierCV(FrozenEstimator(clf), method="sigmoid")
            calibrated.fit(x_cal, y_cal)
            model = calibrated
    except Exception:
        model = clf
    return model, clf


def _score_logloss(model, x, y, scaler=None) -> float | None:
    if len(y) < 5 or len(np.unique(y)) < 2:
        return None
    matrix = scaler.transform(x) if scaler is not None else x
    try:
        proba = model.predict_proba(matrix)
        return float(log_loss(y, proba, labels=model.classes_))
    except Exception:
        return None


def walk_forward_models(
    features: pd.DataFrame,
    labels: np.ndarray,
    columns: list[str],
    h: int,
    lag: int,
    cadence: str = "daily",
    progress=None,
    fit_hgb: bool = True,
    min_rows: int | None = None,
    min_span_days: int | None = None,
) -> dict:
    """Monthly (daily cadence) or annual (monthly cadence) refits.

    Returns probability cubes for logistic and gradient boosting, the trial
    list, and logistic snapshots for explanations.
    """
    dates = pd.DatetimeIndex(features.index)
    x_all = features.loc[:, columns].to_numpy(dtype=float)
    x_all[~np.isfinite(x_all)] = np.nan
    y_all = np.asarray(labels, dtype=object)
    n = len(dates)
    proba_logit = np.full((n, len(FUNDS)), np.nan)
    proba_hgb = np.full((n, len(FUNDS)), np.nan)
    trials: list[dict] = []
    snapshots: list[dict] = []
    chosen = {"C": 1.0, "depth": 3, "n_iter": 30}
    if min_span_days is None:
        min_span_days = 5 * 365
    if min_rows is None:
        min_rows = 504 if cadence == "daily" else 36
    cal_len = 252 if cadence == "daily" else 12
    group = dates.to_period("M" if cadence == "daily" else "Y")
    # Segment starts: first row of each new month (daily) or year (monthly).
    change = np.flatnonzero(group.asi8[1:] != group.asi8[:-1]) + 1
    starts = np.concatenate([[0], change])
    # Predict only once a model exists; group rows between retrain points.
    retrain_points = []
    for start in starts:
        s_max = last_train_index(int(start), h, lag)
        if s_max < min_rows:
            continue
        if (dates[s_max] - dates[0]).days < min_span_days:
            continue
        retrain_points.append(int(start))
    if not retrain_points:
        return {
            "logistic": proba_logit,
            "hgb": proba_hgb,
            "trials": trials,
            "snapshots": snapshots,
            "retrain_points": [],
        }

    boundaries = retrain_points + [n]
    for i, start in enumerate(retrain_points):
        stop = boundaries[i + 1]
        s_max = last_train_index(start, h, lag)
        eligible = np.arange(0, s_max + 1)
        finite_frac = np.isfinite(x_all[eligible]).mean(axis=1)
        y_ok = np.fromiter((y_all[j] is not None for j in eligible), dtype=bool, count=len(eligible))
        train_idx = eligible[y_ok & (finite_frac > 0.6)]
        if len(train_idx) < min_rows:
            continue
        if len(train_idx) <= cal_len + 40:
            continue
        dev_idx = train_idx[:-cal_len]
        cal_idx = train_idx[-cal_len:]
        x_dev, x_cal, _med = _impute(x_all[dev_idx], x_all[cal_idx])
        y_dev = y_all[dev_idx].astype(str)
        y_cal = y_all[cal_idx].astype(str)
        if len(np.unique(y_dev)) < 2:
            continue
        do_search = len(snapshots) == 0 or pd.Timestamp(dates[start]).month == 1 or cadence == "monthly"
        if do_search and len(dev_idx) > 200:
            inner = max(80, len(dev_idx) // 8)
            x_in, x_va, _ = _impute(x_dev[:-inner], x_dev[-inner:])
            y_in = y_dev[:-inner]
            y_va = y_dev[-inner:]
            best_c, best_loss = chosen["C"], np.inf
            for C in (0.1, 1.0, 10.0):
                scaler = StandardScaler()
                clf = LogisticRegression(C=C, max_iter=400, solver="lbfgs", random_state=0)
                try:
                    clf.fit(scaler.fit_transform(x_in), y_in)
                    loss = _score_logloss(clf, x_va, y_va, scaler)
                except Exception:
                    loss = None
                trials.append(
                    {
                        "family": "logistic",
                        "params": {"C": C},
                        "fold_start": dates[start].strftime("%Y-%m-%d"),
                        "inner_log_loss": loss,
                        "cadence": cadence,
                        "lag": lag,
                        "horizon": h,
                    }
                )
                if loss is not None and loss < best_loss:
                    best_loss = loss
                    best_c = C
            chosen["C"] = best_c
            best_depth, best_hgb = chosen["depth"], np.inf
            best_iter = chosen["n_iter"]
            hgb_grid = ((2, 20), (3, 30)) if fit_hgb else ()
            for depth, n_iter in hgb_grid:
                clf = HistGradientBoostingClassifier(
                    max_depth=depth,
                    learning_rate=0.08,
                    max_iter=n_iter,
                    min_samples_leaf=30,
                    l2_regularization=0.1,
                    early_stopping=False,
                    random_state=0,
                )
                try:
                    clf.fit(x_in, y_in)
                    loss = _score_logloss(clf, x_va, y_va)
                except Exception:
                    loss = None
                trials.append(
                    {
                        "family": "hist_gradient_boosting",
                        "params": {"max_depth": depth, "max_iter": n_iter},
                        "fold_start": dates[start].strftime("%Y-%m-%d"),
                        "inner_log_loss": loss,
                        "cadence": cadence,
                        "lag": lag,
                        "horizon": h,
                        "note": "iteration budget chosen on a later slice of the training fold",
                    }
                )
                if loss is not None and loss < best_hgb:
                    best_hgb = loss
                    best_depth = depth
                    best_iter = n_iter
            chosen["depth"] = best_depth
            chosen["n_iter"] = best_iter
        scaler, model, bare = _fit_logistic(x_dev, y_dev, x_cal, y_cal, chosen["C"])
        x_seg_base = x_all[start:stop]
        # Impute the segment with the development median.
        _, x_seg, med = _impute(x_dev, x_seg_base)
        proba_logit[start:stop] = _align_proba(model, scaler.transform(x_seg))
        if fit_hgb:
            hgb_model, _hgb_bare = _fit_hgb(x_dev, y_dev, x_cal, y_cal, chosen["depth"], chosen["n_iter"])
            proba_hgb[start:stop] = _align_proba(hgb_model, x_seg)
        snapshots.append(
            {
                "date": dates[start].strftime("%Y-%m-%d"),
                "end": dates[stop - 1].strftime("%Y-%m-%d"),
                "C": chosen["C"],
                "mean": scaler.mean_.tolist(),
                "scale": scaler.scale_.tolist(),
                "classes": [str(c) for c in bare.classes_],
                "coef": bare.coef_.tolist(),
                "intercept": bare.intercept_.tolist(),
                "columns": columns,
                "median": med.tolist(),
            }
        )
        if progress and i % 12 == 0:
            progress(f"  {cadence} lag={lag} h={h} fold {dates[start].date()} ({i+1}/{len(retrain_points)})")
    return {
        "logistic": proba_logit,
        "hgb": proba_hgb,
        "trials": trials,
        "snapshots": snapshots,
        "retrain_points": retrain_points,
        "chosen": chosen,
    }


def explain_snapshot(snapshot: dict, row: np.ndarray, limit: int = 5, winner: str | None = None) -> dict:
    """Top logistic contributions for the current row, in original units where possible."""
    classes = snapshot["classes"]
    coef = np.asarray(snapshot["coef"], dtype=float)
    intercept = np.asarray(snapshot["intercept"], dtype=float)
    mean = np.asarray(snapshot["mean"], dtype=float)
    scale = np.asarray(snapshot["scale"], dtype=float)
    med = np.asarray(snapshot["median"], dtype=float)
    raw = np.asarray(row, dtype=float)
    raw = np.where(np.isfinite(raw), raw, med)
    scale_safe = np.where(np.abs(scale) < 1e-8, 1.0, scale)
    scaled = (raw - mean) / scale_safe
    scores = coef @ scaled + intercept
    argmax_winner = classes[int(np.argmax(scores))]
    if winner not in classes:
        winner = argmax_winner
    winner_index = classes.index(winner)
    g_index = classes.index("G") if "G" in classes else None
    names = snapshot["columns"]
    drivers = []
    if g_index is not None:
        margin_coef = coef[winner_index] - coef[g_index]
        contrib = margin_coef * scaled
        order = np.argsort(-np.abs(contrib))
        for pos in order[:limit]:
            drivers.append(
                {
                    "feature": names[pos],
                    "value": float(raw[pos]),
                    "contribution": float(contrib[pos]),
                    "direction": "toward the chosen fund" if contrib[pos] > 0 else "toward G",
                }
            )
        # Nearest single-feature move that ties the winner with G.
        score_gap = float(scores[winner_index] - scores[g_index])
        flips = []
        for pos in order[:limit]:
            denom = float(margin_coef[pos])
            if abs(denom) < 1e-8:
                continue
            delta_scaled = -score_gap / denom
            delta_raw = delta_scaled * float(scale_safe[pos])
            flips.append(
                {
                    "feature": names[pos],
                    "raw_change_to_tie_g": float(delta_raw),
                    "note": "Linear approximation from the logistic scores, holding other features fixed.",
                }
            )
    else:
        flips = []
    return {
        "winner": winner,
        "logistic_argmax": argmax_winner,
        "scores": {c: float(s) for c, s in zip(classes, scores, strict=False)},
        "drivers": drivers,
        "flips": flips,
    }


def policy_from_proba(proba: np.ndarray, mean_excess: np.ndarray, min_prob: float = 0.34) -> np.ndarray:
    """Pick the fund with the highest probability times in-fold mean excess.

    G is selected unless a risky fund has probability at least ``min_prob`` and a
    positive in-fold mean excess. ``mean_excess`` is shape (5,) with G at 0.
    """
    p = np.asarray(proba, dtype=float)
    mu = np.asarray(mean_excess, dtype=float)
    n = len(p)
    out = np.repeat(np.array([1.0, 0, 0, 0, 0], dtype=float).reshape(1, -1), n, axis=0)
    for i in range(n):
        if not np.isfinite(p[i]).all():
            continue
        score = p[i] * mu
        score[0] = 0.0
        best = int(np.argmax(score))
        if best != 0 and p[i, best] >= min_prob and mu[best] > 0 and score[best] > 0:
            row = np.zeros(5)
            row[best] = 1.0
            out[i] = row
    return out
