"""Build the walk-forward scoreboard and the static dashboard.

``tsp build`` runs offline from the bundled snapshot. Optional VIX and NY Fed
files are read from ``data/cache/`` when present. If they are absent, realized
volatility stands in for VIX and the NY Fed series is omitted.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tsppredictor import DATA_AS_OF_BUNDLED, I_FUND_BREAK, NOT_ADVICE, SCHEMA_VERSION
from tsppredictor.backtest.honesty import (
    block_bootstrap_excess_cagr,
    deflated_sharpe_ratio,
    multiclass_brier,
    reliability,
    verdict,
)
from tsppredictor.backtest.metrics import summarize
from tsppredictor.backtest.walkforward import (
    constant_fund_path,
    forward_excess,
    one_hot,
    portfolio_returns,
    rebalanced_mix,
    simulate_targets,
    static_mix_wealth,
    wealth_from_prices,
)
from tsppredictor.calendar import project_tsp_days
from tsppredictor.data.ingest_macro import load_cached_nyfed, load_cached_vix
from tsppredictor.data.snapshot import check_integrity, core_prices, load_snapshot
from tsppredictor.features.monthly import build_monthly_features, monthly_price_index
from tsppredictor.features.pipeline import build_features
from tsppredictor.features.spec import FEATURES, feature_dicts, model_feature_names
from tsppredictor.models.diagnostics import toy_buy_i_after_c_up
from tsppredictor.models.ensemble import average_probabilities, best_rule_probabilities, policy_over_folds
from tsppredictor.models.ml import explain_snapshot, walk_forward_models
from tsppredictor.models.regimes import rule_regime_labels, walk_forward_gmm
from tsppredictor.models.rules import RULES, all_rules
from tsppredictor.paths import cache_dir, dist_dir, snapshot_dir
from tsppredictor.studies import (
    cost_of_being_wrong,
    event_window_study,
    fan_chart,
    g_versus_f,
    gpr_spike_study,
    l_fund_xray,
    missed_best_days,
    scarcity_upper_bound,
    seasonality,
    stress_report,
)

FUNDS = ("G", "F", "C", "S", "I")
STATIC = np.array([0.40, 0.0, 0.60, 0.0, 0.0])
BLOCKS = (
    {"cadence": "daily", "h": 21, "lag": 1, "fit_hgb": True, "primary": True},
    {"cadence": "daily", "h": 21, "lag": 2, "fit_hgb": True, "primary": False},
    {"cadence": "daily", "h": 63, "lag": 1, "fit_hgb": False, "primary": False},
    {"cadence": "monthly", "h": 1, "lag": 1, "fit_hgb": True, "primary": False},
    {"cadence": "monthly", "h": 1, "lag": 2, "fit_hgb": True, "primary": False},
)


def _log(message: str) -> None:
    print(message, flush=True)


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")))


def _iso(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _finite_start(weights: np.ndarray) -> int | None:
    ok = np.isfinite(weights).all(axis=1)
    hits = np.flatnonzero(ok)
    if len(hits) == 0:
        return None
    return int(hits[0])


def _simulate(dates, prices, targets, lag: int, min_hold: int, oos_i: int) -> dict:
    matrix = np.array(targets, dtype=float, copy=True)
    matrix[:oos_i] = np.nan
    initial = matrix[oos_i].copy()
    if not np.isfinite(initial).all():
        initial = one_hot("G")
    sim = simulate_targets(dates, matrix, lag=lag, min_hold=min_hold, enforce_ift=True, initial=initial)
    returns = portfolio_returns(prices, sim["weights"])
    wealth = np.cumprod(1.0 + returns)
    sim["returns"] = returns
    sim["wealth"] = wealth
    return sim


def _rebase(wealth: np.ndarray, dates: pd.DatetimeIndex, start, end):
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    mask = (dates >= start) & (dates <= end) & np.isfinite(wealth)
    if mask.sum() < 5:
        return None
    w = np.asarray(wealth, dtype=float)[mask]
    d = dates[mask]
    if w[0] <= 0:
        return None
    return w / w[0], d


def _g_returns(prices: pd.DataFrame, dates: pd.DatetimeIndex) -> np.ndarray:
    g = prices["G"].reindex(dates).to_numpy(dtype=float)
    out = np.zeros(len(g))
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = g[1:] / g[:-1] - 1.0
    return np.where(np.isfinite(out), out, 0.0)


def _align_pair(wealth_a, dates_a, wealth_b, dates_b):
    a = pd.Series(np.asarray(wealth_a, dtype=float), index=pd.DatetimeIndex(dates_a))
    b = pd.Series(np.asarray(wealth_b, dtype=float), index=pd.DatetimeIndex(dates_b))
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if len(joined) < 5 or joined["a"].iloc[0] <= 0 or joined["b"].iloc[0] <= 0:
        return None
    return (
        (joined["a"] / joined["a"].iloc[0]).to_numpy(),
        (joined["b"] / joined["b"].iloc[0]).to_numpy(),
        pd.DatetimeIndex(joined.index),
    )


def _compare(strat_w, strat_d, base_w, base_d, n_trials: int, block: int) -> dict | None:
    aligned = _align_pair(strat_w, strat_d, base_w, base_d)
    if aligned is None:
        return None
    sw, bw, dates = aligned
    rs = np.zeros(len(sw))
    rb = np.zeros(len(bw))
    rs[1:] = sw[1:] / sw[:-1] - 1.0
    rb[1:] = bw[1:] / bw[:-1] - 1.0
    boot = block_bootstrap_excess_cagr(rs, rb, dates, block=block, n_boot=400, seed=0)
    excess_series = rs - rb
    dsr = deflated_sharpe_ratio(excess_series[1:], n_trials)
    label = verdict(boot["excess_cagr"], boot["ci90"], dsr)
    return {
        "excess_cagr": boot["excess_cagr"],
        "ci90": boot["ci90"],
        "dsr": dsr,
        "verdict": label,
        "point_estimate_below": bool(boot["excess_cagr"] < 0),
        "_excess": np.asarray(excess_series[1:], dtype=float),
    }


def _sentence(name: str, comparison: dict, baseline: str) -> str:
    excess = comparison["excess_cagr"]
    lo, hi = comparison["ci90"]
    text = (
        f"{name} versus {baseline}: out-of-sample excess compound growth is {excess * 100:.2f} "
        f"percentage points per year. The 90% block-bootstrap interval is {lo * 100:.2f} to {hi * 100:.2f}. "
        f"Verdict: {comparison['verdict']}."
    )
    if excess < 0:
        text += " The point estimate is below this baseline."
    return text


def _metrics_on(wealth, dates, weights, prices, post_dates) -> dict:
    sliced_g = _g_returns(prices, dates)
    posts = [pd.Timestamp(ts) for ts in post_dates if dates[0] <= pd.Timestamp(ts) <= dates[-1]]
    stats = summarize(wealth, dates, weights, sliced_g, posts)
    for key, value in list(stats.items()):
        if isinstance(value, float):
            stats[key] = round(value, 6)
        elif isinstance(value, dict):
            stats[key] = {k: round(v, 6) if isinstance(v, float) else v for k, v in value.items()}
    return stats


def _weights_on(weights, dates, start, end):
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    return np.asarray(weights, dtype=float)[mask]


def _pick_names(weights: np.ndarray) -> np.ndarray:
    idx = np.argmax(np.asarray(weights, dtype=float), axis=1)
    return np.array(FUNDS, dtype=object)[idx]


def _month_end_curve(dates, wealth) -> tuple[list[str], list[float]]:
    frame = pd.Series(np.asarray(wealth, dtype=float), index=pd.DatetimeIndex(dates))
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        return [], []
    sampled = frame.groupby(frame.index.to_period("M")).tail(1)
    return [_iso(ts) for ts in sampled.index], [round(float(v), 6) for v in sampled.to_numpy()]


def _forward_total(px: np.ndarray, start: int, end: int) -> float | None:
    if start < 0 or end >= len(px) or start >= end:
        return None
    a = px[start]
    b = px[end]
    if not np.isfinite(a) or not np.isfinite(b) or a <= 0:
        return None
    return float(b / a - 1.0)


def _calibration_sentence(bins: list[dict], probability: float) -> str:
    usable = [row for row in bins if row["n"] and row["mean_predicted"] is not None]
    if not usable or probability is None:
        return "There is no out-of-sample bin for this probability yet."
    holder = None
    for row in bins:
        if row["n"] and row["low"] <= probability <= row["high"]:
            holder = row
            break
    if holder is None:
        holder = min(usable, key=lambda row: abs(row["mean_predicted"] - probability))
        prefix = "No decisions fell in that exact bin. The nearest populated bin"
    else:
        prefix = "In the bin covering this probability"
    rate = holder["empirical_rate"]
    return (
        f"{prefix} had a mean predicted probability of {holder['mean_predicted']:.0%} "
        f"and was right {int(round(rate * holder['n']))} of {holder['n']} times "
        f"(empirical rate {rate:.0%})."
    )


def _optional_present() -> dict:
    root = cache_dir()
    names = {
        "vix": "macro/primary/vix_history_cboe.csv",
        "fred_dgs10": "macro/fred_dgs10.csv",
        "fama_french": "macro/fama_french_5_factors_monthly.csv",
        "shiller": "macro/shiller_ie_data.csv",
        "nyfed": "macro/nyfed_yield_curve_recession_probability.csv",
    }
    return {key: (root / rel).exists() for key, rel in names.items()}


def _compound_monthly_column(monthly: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    frame = monthly.copy()
    frame["month"] = frame["month"].astype(str).str.slice(0, 7)
    rets = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float) / 100.0
    level = np.full(len(rets), np.nan)
    acc = 1.0
    started = False
    for i, ret in enumerate(rets):
        if not np.isfinite(ret):
            if started:
                level[i] = acc
            continue
        acc *= 1.0 + ret
        level[i] = acc
        started = True
    out = pd.Series(level, index=index, name="L2050")
    return out


def _run_block(spec, features, prices, l2050: pd.Series, n_trials_box: list[int]) -> dict:
    h = spec["h"]
    lag = spec["lag"]
    cadence = spec["cadence"]
    _log(f"walk-forward {cadence} h={h} lag={lag} hgb={spec['fit_hgb']}")
    labels, excess = forward_excess(prices, h, lag)
    columns = [name for name in model_feature_names() if name in features.columns]
    ml = walk_forward_models(
        features,
        labels,
        columns,
        h=h,
        lag=lag,
        cadence=cadence,
        progress=_log,
        fit_hgb=spec["fit_hgb"],
    )
    n_trials_box[0] += len(ml["trials"])
    rules = all_rules(features)
    for key, (title, _fn) in RULES.items():
        ml["trials"].append(
            {
                "family": "rule",
                "params": {"rule": key},
                "name": title,
                "cadence": cadence,
                "lag": lag,
                "horizon": h,
                "inner_log_loss": None,
            }
        )
    n_trials_box[0] += len(RULES)
    rule_p, rule_which = best_rule_probabilities(rules, labels, h, lag)
    parts = [ml["logistic"], rule_p]
    if spec["fit_hgb"]:
        parts.append(ml["hgb"])
    ensemble_p = average_probabilities(*parts)
    dates = pd.DatetimeIndex(features.index)
    min_hold = 21 if cadence == "daily" else 1
    model_targets = {
        "logistic": policy_over_folds(ml["logistic"], excess, ml["retrain_points"], h, lag, prices),
        "ensemble": policy_over_folds(ensemble_p, excess, ml["retrain_points"], h, lag, prices),
    }
    if spec["fit_hgb"]:
        model_targets["hgb"] = policy_over_folds(ml["hgb"], excess, ml["retrain_points"], h, lag, prices)
    # Rules are already allocations. Score them on the logistic out-of-sample start.
    oos_candidates = []
    for key, (matrix, _folds) in model_targets.items():
        start = _finite_start(matrix)
        if start is not None:
            oos_candidates.append(start)
    if not oos_candidates:
        return {"rows": [], "trials": ml["trials"], "empty": True}
    oos_i = min(oos_candidates)
    oos_start = dates[oos_i]
    oos_end = dates[-1]
    paths = {}
    for key, matrix in rules.items():
        paths[key] = _simulate(dates, prices, matrix, lag, min_hold, oos_i)
    for key, (matrix, _folds) in model_targets.items():
        if _finite_start(matrix) is None:
            continue
        paths[key] = _simulate(dates, prices, matrix, lag, min_hold, oos_i)
    block = 21 if cadence == "daily" else 12
    sub_prices = prices.iloc[oos_i:]
    sub_dates = dates[oos_i:]
    baselines = {
        "bh_c": constant_fund_path(sub_prices, "C"),
        "always_g": constant_fund_path(sub_prices, "G"),
    }
    static_w, static_weights = static_mix_wealth(sub_prices, STATIC)
    baselines["static_60_40"] = {
        "wealth": static_w,
        "weights": static_weights,
        "returns": np.r_[0.0, static_w[1:] / static_w[:-1] - 1.0],
        "post_dates": [],
    }
    reb = rebalanced_mix(sub_prices, sub_dates, STATIC, lag=lag)
    baselines["rebalanced_60_40"] = reb
    l_wealth_full = wealth_from_prices(l2050.reindex(dates))
    rows = []
    curve = {}

    def add_row(key: str, name: str, kind: str, wealth, weights, row_dates, post_dates):
        window = _rebase(wealth, pd.DatetimeIndex(row_dates), oos_start, oos_end)
        if window is None:
            return None
        w, d = window
        wts = _weights_on(weights, pd.DatetimeIndex(row_dates), d[0], d[-1])
        if len(wts) != len(d):
            wts = np.repeat(one_hot("G").reshape(1, -1), len(d), axis=0)
        metrics = _metrics_on(w, d, wts, prices, post_dates)
        versus = {}
        sentences = {}
        base_windows = {
            "bh_c": (baselines["bh_c"]["wealth"], sub_dates),
            "always_g": (baselines["always_g"]["wealth"], sub_dates),
            "static_60_40": (baselines["static_60_40"]["wealth"], sub_dates),
        }
        l_window = _rebase(l_wealth_full, dates, d[0], d[-1])
        if l_window is not None:
            base_windows["l2050"] = l_window
        for base_key, (bw, bd) in base_windows.items():
            compared = _compare(w, d, bw, bd, n_trials_box[0], block)
            if compared is None:
                continue
            versus[base_key] = compared
            sentences[base_key] = _sentence(name, compared, base_key)
        xs, ys = _month_end_curve(d, w)
        curve[key] = {"dates": xs, "wealth": ys}
        row = {
            "id": key,
            "name": name,
            "kind": kind,
            "cadence": cadence,
            "lag": lag,
            "horizon": h,
            "oos_start": _iso(d[0]),
            "oos_end": _iso(d[-1]),
            "metrics": metrics,
            "versus": versus,
            "sentences": sentences,
        }
        rows.append(row)
        return row

    names = {
        "bh_c": "Buy-and-hold C",
        "always_g": "Always G",
        "static_60_40": "Static 60% C / 40% G",
        "rebalanced_60_40": "Monthly rebalanced 60% C / 40% G",
        "l2050": "L 2050",
        "logistic": "L2 logistic",
        "hgb": "Gradient boosting",
        "ensemble": "Ensemble",
    }
    for key, (title, _fn) in RULES.items():
        names[key] = title
    for key, path in baselines.items():
        add_row(key, names[key], "baseline", path["wealth"], path["weights"], sub_dates, path.get("post_dates", []))
    if l_window := _rebase(l_wealth_full, dates, oos_start, oos_end):
        lw, ld = l_window
        l_weights = np.repeat(one_hot("G").reshape(1, -1), len(ld), axis=0)
        # L 2050 is a lifecycle mix, not a G/F/C/S/I weight. Time-in-fund is left as the mix itself via a separate panel.
        metrics = _metrics_on(lw, ld, l_weights, prices, [])
        versus = {}
        sentences = {}
        for base_key in ("bh_c", "always_g", "static_60_40"):
            compared = _compare(lw, ld, baselines[base_key]["wealth"], sub_dates, max(n_trials_box[0], 1), block)
            if compared:
                versus[base_key] = compared
                sentences[base_key] = _sentence(names["l2050"], compared, base_key)
        xs, ys = _month_end_curve(ld, lw)
        curve["l2050"] = {"dates": xs, "wealth": ys}
        rows.append(
            {
                "id": "l2050",
                "name": names["l2050"],
                "kind": "baseline",
                "cadence": cadence,
                "lag": lag,
                "horizon": h,
                "oos_start": _iso(ld[0]),
                "oos_end": _iso(ld[-1]),
                "metrics": metrics,
                "versus": versus,
                "sentences": sentences,
                "note": "L 2050 is scored only on dates it has a price. It is a lifecycle fund, so the G/F/C/S/I time-in-fund fields do not describe it.",
            }
        )
    for key, path in paths.items():
        kind = "rule" if key in RULES else "model"
        add_row(key, names.get(key, key), kind, path["wealth"], path["weights"], dates, path["post_dates"])
    detail = None
    if spec.get("primary"):
        detail = _primary_detail(
            dates=dates,
            prices=prices,
            features=features,
            labels=labels,
            excess=excess,
            oos_i=oos_i,
            ml=ml,
            ensemble_p=ensemble_p,
            model_targets=model_targets,
            paths=paths,
            columns=columns,
            rows=rows,
            h=h,
            lag=lag,
        )
    return {
        "rows": rows,
        "trials": ml["trials"],
        "curve": curve if spec.get("primary") else {},
        "detail": detail,
        "oos_start": _iso(oos_start),
        "oos_end": _iso(oos_end),
        "empty": False,
    }


def _primary_detail(dates, prices, features, labels, excess, oos_i, ml, ensemble_p, model_targets, paths, columns, rows, h, lag) -> dict:
    ens_targets, folds = model_targets["ensemble"]
    path = paths.get("ensemble")
    last = len(dates) - 1
    while last > oos_i and not np.isfinite(ensemble_p[last]).all():
        last -= 1
    probs = ensemble_p[last]
    policy_row = ens_targets[last]
    if not np.isfinite(policy_row).all():
        fund = "G"
    else:
        fund = FUNDS[int(np.argmax(policy_row))]
    probability = float(probs[FUNDS.index(fund)]) if np.isfinite(probs).all() else None
    snapshot = ml["snapshots"][-1]
    row = features.iloc[last][columns].to_numpy(dtype=float)
    explained = explain_snapshot(snapshot, row, winner=fund if fund != "G" else None)
    descriptions = {spec.name: spec.description for spec in FEATURES}
    drivers = []
    for driver in explained["drivers"]:
        drivers.append(
            {
                **driver,
                "value": round(float(driver["value"]), 6),
                "contribution": round(float(driver["contribution"]), 4),
                "text": descriptions.get(driver["feature"], driver["feature"]),
            }
        )
    flips = []
    for flip in explained["flips"]:
        flips.append(
            {
                "feature": flip["feature"],
                "raw_change_to_tie_g": round(float(flip["raw_change_to_tie_g"]), 6),
                "text": descriptions.get(flip["feature"], flip["feature"]),
                "note": flip["note"],
            }
        )
    mean_excess = folds[-1]["mean_excess"] if folds else [0, 0, 0, 0, 0]
    oos_slice = slice(oos_i, None)
    conf = ensemble_p[oos_slice]
    y = np.asarray(labels[oos_slice], dtype=object)
    finite = np.isfinite(conf).all(axis=1) & np.array([lab in FUNDS for lab in y])
    conf = conf[finite]
    y = y[finite]
    pred = np.array(FUNDS)[np.argmax(conf, axis=1)] if len(conf) else np.array([])
    chosen_p = conf[np.arange(len(conf)), np.argmax(conf, axis=1)] if len(conf) else np.array([])
    right = (pred == y).astype(float) if len(conf) else np.array([])
    rel = reliability(chosen_p, right) if len(conf) else {"bins": [], "n": 0, "count_sum": 0}
    brier = multiclass_brier(conf, y, list(FUNDS)) if len(conf) else None
    picks = np.array([None] * len(dates), dtype=object)
    finite_policy = np.isfinite(ens_targets).all(axis=1)
    picks[finite_policy] = _pick_names(ens_targets[finite_policy])
    cost = cost_of_being_wrong(picks, labels, excess, fund)
    c_rets = prices["C"].pct_change().to_numpy(dtype=float)
    c_rets[:oos_i] = np.nan
    missed = missed_best_days(c_rets, path["weights"]) if path is not None else {"rows": []}
    regimes = rule_regime_labels(features)
    current_regime = str(regimes.iloc[last])
    duration = 1
    for cursor in range(last - 1, -1, -1):
        if regimes.iloc[cursor] != current_regime:
            break
        duration += 1
    try:
        gmm = walk_forward_gmm(features)
        gmm_now = gmm.iloc[last]
        gmm_label = None if pd.isna(gmm_now) else int(gmm_now)
    except Exception as exc:
        gmm = pd.Series(np.nan, index=features.index)
        gmm_label = None
        gmm_error = str(exc)
    else:
        gmm_error = None
    # Per-regime hit rate of the ensemble policy on labeled OOS rows.
    regime_table = []
    oos_regimes = regimes.iloc[oos_i:]
    oos_picks = picks[oos_i:]
    oos_labels = labels[oos_i:]
    for label_name, _count in oos_regimes.value_counts().items():
        mask = (oos_regimes == label_name).to_numpy()
        comparable = [
            (pick, lab)
            for pick, lab, keep in zip(oos_picks, oos_labels, mask, strict=False)
            if keep and pick in FUNDS and lab in FUNDS
        ]
        hits = sum(1 for pick, lab in comparable if pick == lab)
        regime_table.append(
            {
                "regime": str(label_name),
                "n": int(len(comparable)),
                "hit_rate": None if not comparable else round(hits / len(comparable), 4),
            }
        )
    replay_dates = []
    replay_fund = []
    replay_p = []
    replay_drivers = []
    reveal = []
    px = {fund: prices[fund].to_numpy(dtype=float) for fund in FUNDS}
    snaps = ml["snapshots"]
    snap_pos = 0
    for i in range(oos_i, len(dates)):
        if not np.isfinite(ensemble_p[i]).all():
            continue
        policy = ens_targets[i]
        if not np.isfinite(policy).all():
            continue
        this_fund = FUNDS[int(np.argmax(policy))]
        stamp = _iso(dates[i])
        replay_dates.append(stamp)
        replay_fund.append(this_fund)
        replay_p.append(round(float(ensemble_p[i, FUNDS.index(this_fund)]), 4))
        while snap_pos + 1 < len(snaps) and snaps[snap_pos + 1]["date"] <= stamp:
            snap_pos += 1
        local_snap = snaps[snap_pos]
        local_cols = local_snap["columns"]
        local = explain_snapshot(
            local_snap,
            features.iloc[i][local_cols].to_numpy(dtype=float),
            limit=3,
            winner=this_fund if this_fund != "G" else None,
        )
        replay_drivers.append(
            [
                {
                    "feature": item["feature"],
                    "contribution": round(float(item["contribution"]), 4),
                    "direction": item["direction"],
                }
                for item in local["drivers"][:3]
            ]
        )
        reveal.append(
            {
                "h21": _round(_forward_total(px["C"], i + lag, i + lag + 21)),
                "h63": _round(_forward_total(px["C"], i + lag, i + lag + 63)),
                "h126": _round(_forward_total(px["C"], i + lag, i + lag + 126)),
                "h252": _round(_forward_total(px["C"], i + lag, i + lag + 252)),
                "fund21": _round(_forward_total(px[this_fund], i + lag, i + lag + 21)),
                "g21": _round(_forward_total(px["G"], i + lag, i + lag + 21)),
            }
        )
    ribbon_dates = []
    ribbon_labels = []
    sampled = regimes.groupby(dates.to_period("M")).tail(1)
    for ts, label_name in sampled.items():
        ribbon_dates.append(_iso(ts))
        ribbon_labels.append(str(label_name))
    ens_row = next((row for row in rows if row["id"] == "ensemble"), None)
    return {
        "date": _iso(dates[last]),
        "fund": fund,
        "stance": "Shelter in G" if fund == "G" else ("Neutral" if fund == "F" else "Risk On"),
        "probability": None if probability is None else round(probability, 4),
        "probabilities": {name: round(float(probs[i]), 4) for i, name in enumerate(FUNDS)} if np.isfinite(probs).all() else {},
        "mean_excess": {name: round(float(mean_excess[i]), 6) for i, name in enumerate(FUNDS)},
        "min_probability": 0.34,
        "drivers": drivers,
        "flips": flips,
        "logistic_argmax": explained["logistic_argmax"],
        "logistic_scores": {k: round(v, 4) for k, v in explained["scores"].items()},
        "fold_start": snapshot["date"],
        "fold_end": snapshot["end"],
        "C": snapshot["C"],
        "calibration": rel,
        "multiclass_brier": None if brier is None else round(float(brier), 6),
        "scoreboard_row": ens_row,
        "cost": cost,
        "missed": missed,
        "regime": current_regime,
        "regime_sessions": int(duration),
        "gmm_state": gmm_label,
        "gmm_error": gmm_error,
        "regime_table": regime_table,
        "replay": {
            "dates": replay_dates,
            "fund": replay_fund,
            "probability": replay_p,
            "drivers": replay_drivers,
            "reveal": reveal,
        },
        "ribbon": {"dates": ribbon_dates, "label": ribbon_labels},
        "horizon": h,
        "lag": lag,
        "scarcity": scarcity_upper_bound(ens_targets, path["weights"], c_rets) if path is not None else {"available": False},
        "fan": fan_chart(prices[fund].pct_change().to_numpy(dtype=float), dates),
    }


def _round(value):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 6)


def _i_fund_split(prices: pd.DataFrame, n_trials: int) -> list[dict]:
    rows = []
    dates = pd.DatetimeIndex(prices.index)
    break_on = pd.Timestamp(I_FUND_BREAK)
    windows = (
        ("bh_i_before_break", "Buy-and-hold I before the 2024-10-30 benchmark change", dates[0], break_on - pd.Timedelta(days=1)),
        ("bh_i_after_break", "Buy-and-hold I on and after 2024-10-30", break_on, dates[-1]),
    )
    for key, name, start, end in windows:
        mask = (dates >= start) & (dates <= end)
        sub = prices.loc[mask]
        sub_dates = dates[mask]
        if len(sub) < 5:
            continue
        i_path = constant_fund_path(sub, "I")
        c_path = constant_fund_path(sub, "C")
        g_path = constant_fund_path(sub, "G")
        compared = _compare(i_path["wealth"], sub_dates, c_path["wealth"], sub_dates, n_trials, 21)
        versus = {}
        sentences = {}
        if compared:
            versus["bh_c"] = compared
            sentences["bh_c"] = _sentence(name, compared, "buy-and-hold C")
        g_cmp = _compare(i_path["wealth"], sub_dates, g_path["wealth"], sub_dates, n_trials, 21)
        if g_cmp:
            versus["always_g"] = g_cmp
            sentences["always_g"] = _sentence(name, g_cmp, "always G")
        metrics = _metrics_on(i_path["wealth"], sub_dates, i_path["weights"], sub, [])
        rows.append(
            {
                "id": key,
                "name": name,
                "kind": "slice",
                "cadence": "daily",
                "lag": 1,
                "horizon": None,
                "oos_start": _iso(sub_dates[0]),
                "oos_end": _iso(sub_dates[-1]),
                "metrics": metrics,
                "versus": versus,
                "sentences": sentences,
                "note": "Split at the I Fund benchmark change. This is buy-and-hold, not a timing rule.",
            }
        )
    return rows


def _restamp_verdicts(scoreboard: list[dict], n_trials: int) -> None:
    """Recompute deflated Sharpe with the full trial count, then drop the return series."""
    n_trials = max(int(n_trials), 1)
    for row in scoreboard:
        versus = row.get("versus") or {}
        sentences = row.setdefault("sentences", {})
        for key, compared in versus.items():
            series = compared.pop("_excess", None)
            if series is not None:
                compared["dsr"] = deflated_sharpe_ratio(np.asarray(series, dtype=float), n_trials)
                compared["verdict"] = verdict(compared["excess_cagr"], compared["ci90"], compared["dsr"])
                compared["point_estimate_below"] = bool(compared["excess_cagr"] < 0)
            labels = {
                "bh_c": "buy-and-hold C",
                "l2050": "L 2050",
                "always_g": "always G",
                "static_60_40": "the static 60% C / 40% G mix",
            }
            sentences[key] = _sentence(row["name"], compared, labels.get(key, key))


def _plain(detail: dict) -> str:
    fund = detail["fund"]
    prob = detail["probability"]
    probs = detail["probabilities"]
    mu = detail["mean_excess"]
    parts = [
        f"On {detail['date']} the ensemble policy selects {fund}.",
    ]
    if prob is not None:
        parts.append(
            f"Its calibrated probability for {fund} is {prob:.1%}."
        )
    parts.append(
        "The policy holds a risky fund only when that fund's probability is at least "
        f"{detail['min_probability']:.0%} and its mean excess over G inside the purged training fold is positive."
    )
    bits = []
    for name in FUNDS:
        if name in probs and name in mu:
            bits.append(f"{name} probability {probs[name]:.1%}, in-fold mean excess {mu[name] * 100:.2f} percentage points")
    if bits:
        parts.append("Fold inputs: " + "; ".join(bits) + ".")
    if detail["logistic_argmax"] != fund:
        parts.append(
            f"The logistic scores alone favor {detail['logistic_argmax']}. "
            "The published allocation also averages the gradient-boosting model and the best purged rule."
        )
    row = detail.get("scoreboard_row") or {}
    for key, label in (("bh_c", "buy-and-hold C"), ("l2050", "L 2050")):
        compared = (row.get("versus") or {}).get(key)
        if not compared:
            continue
        parts.append(_sentence("This ensemble", compared, label))
    parts.append(NOT_ADVICE)
    return " ".join(parts)


def _publish_static(dist: Path) -> None:
    src = Path(__file__).resolve().parent / "report" / "static"
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        dest = dist / item.relative_to(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def _render(dist: Path, context: dict) -> None:
    template_dir = Path(__file__).resolve().parent / "report" / "templates"
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html", "xml"]))
    html = env.get_template("index.html.j2").render(**context)
    (dist / "index.html").write_text(html)
    _publish_static(dist)


def run_build() -> dict:
    started = time.perf_counter()
    snap = load_snapshot()
    integrity = check_integrity(snap)
    if not integrity.ok:
        raise RuntimeError("snapshot failed integrity checks: " + "; ".join(integrity.errors))
    prices = core_prices(snap)
    vix = load_cached_vix()
    nyfed = load_cached_nyfed()
    _log("building daily features")
    features = build_features(prices, snap.h15, snap.bls, snap.gpr_daily, snap.events, vix=vix, nyfed=nyfed)
    _log("building monthly features")
    monthly_px = monthly_price_index(snap.monthly)
    monthly_features = build_monthly_features(snap.monthly, snap.h15, snap.bls, snap.gpr_monthly)
    monthly_l = _compound_monthly_column(snap.monthly, "L 2050", monthly_px.index)
    daily_l = snap.daily["L2050"] if "L2050" in snap.daily.columns else pd.Series(np.nan, index=prices.index)
    l_frame = pd.DataFrame(index=prices.index)
    for col in snap.daily.columns:
        if str(col).startswith("L"):
            l_frame[col] = snap.daily[col]
    n_trials_box = [0]
    scoreboard: list[dict] = []
    trials: list[dict] = []
    curves = {}
    detail = None
    for spec in BLOCKS:
        if spec["cadence"] == "daily":
            result = _run_block(spec, features, prices, daily_l, n_trials_box)
        else:
            result = _run_block(spec, monthly_features, monthly_px, monthly_l, n_trials_box)
        scoreboard.extend(result["rows"])
        trials.extend(result["trials"])
        if result.get("curve"):
            curves = result["curve"]
        if result.get("detail"):
            detail = result["detail"]
    if detail is None:
        raise RuntimeError("primary walk-forward produced no signal")
    scoreboard.extend(_i_fund_split(prices, max(n_trials_box[0], 1)))
    _restamp_verdicts(scoreboard, n_trials_box[0])
    detail["plain"] = _plain(detail)
    detail["calibration_sentence"] = _calibration_sentence(
        detail["calibration"]["bins"], detail["probability"] if detail["probability"] is not None else 0.0
    )
    as_of = _iso(prices.index.max())
    _log("studies")
    events = event_window_study(prices, snap.events)
    spikes = gpr_spike_study(prices, features["gpr_spike"])
    seasons = seasonality(prices)
    stress = stress_report(prices, snap.monthly, l_frame)
    xray = l_fund_xray(prices, daily_l.rename("L2050"))
    harbor = g_versus_f(prices, snap.monthly)
    stale = toy_buy_i_after_c_up()
    refresh_path = snapshot_dir() / "REFRESH.json"
    if refresh_path.exists():
        refresh = json.loads(refresh_path.read_text())
    else:
        refresh = {"at": None, "ok": True, "source": "bundled snapshot", "data_as_of": as_of}
    optional = _optional_present()
    meta = {
        "schema_version": SCHEMA_VERSION,
        "data_as_of": as_of,
        "bundled_as_of": DATA_AS_OF_BUNDLED,
        "not_advice": NOT_ADVICE,
        "n_trials": n_trials_box[0],
        "integrity_ok": integrity.ok,
        "warnings": integrity.warnings,
        "notes": integrity.notes,
        "stats": integrity.stats,
        "refresh": refresh,
        "optional_sources": optional,
        "vix_in_model": bool(vix is not None and not vix.empty),
        "vix_note": "Cboe VIX from the local cache." if optional["vix"] else "VIX file absent. vol_level uses 20-session realized volatility of the C Fund.",
        "nyfed_in_features": "nyfed_rec_prob" in features.columns,
        "stale_price_toy": stale,
        "i_fund_break": I_FUND_BREAK,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
    # Post-2008 slice note for the primary ensemble, already the daily window.
    today = {
        "schema_version": SCHEMA_VERSION,
        "data_as_of": as_of,
        "not_advice": NOT_ADVICE,
        "signal_date": detail["date"],
        "fund": detail["fund"],
        "stance": detail["stance"],
        "probability": detail["probability"],
        "probabilities": detail["probabilities"],
        "mean_excess": detail["mean_excess"],
        "min_probability": detail["min_probability"],
        "drivers": detail["drivers"],
        "flips": detail["flips"],
        "logistic_argmax": detail["logistic_argmax"],
        "logistic_scores": detail["logistic_scores"],
        "fold_start": detail["fold_start"],
        "fold_end": detail["fold_end"],
        "logistic_C": detail["C"],
        "plain": detail["plain"],
        "calibration_sentence": detail["calibration_sentence"],
        "versus": (detail["scoreboard_row"] or {}).get("versus", {}),
        "sentences": (detail["scoreboard_row"] or {}).get("sentences", {}),
        "oos_start": (detail["scoreboard_row"] or {}).get("oos_start"),
        "oos_end": (detail["scoreboard_row"] or {}).get("oos_end"),
        "regime": detail["regime"],
        "regime_sessions": detail["regime_sessions"],
        "gmm_state": detail["gmm_state"],
        "cost": detail["cost"],
        "missed": detail["missed"],
        "fan": detail["fan"],
        "scarcity": detail["scarcity"],
        "hypothetical_balance": 100000,
    }
    dist = dist_dir()
    data = dist / "data"
    _dump(data / "meta.json", meta)
    _dump(data / "today.json", today)
    _dump(data / "scoreboard.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "rows": scoreboard, "n_trials": n_trials_box[0]})
    _dump(data / "calibration.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "reliability": detail["calibration"], "multiclass_brier": detail["multiclass_brier"], "sentence": detail["calibration_sentence"]})
    _dump(
        data / "history.json",
        {
            "schema_version": SCHEMA_VERSION,
            "data_as_of": as_of,
            "replay": detail["replay"],
            "ribbon": detail["ribbon"],
            "regime_table": detail["regime_table"],
            "regime": detail["regime"],
            "regime_sessions": detail["regime_sessions"],
            "gmm_state": detail["gmm_state"],
            "gmm_note": "Gaussian mixture states are refit each January on earlier years only and ordered by training-set volatility. They are descriptive.",
            "events": events,
            "gpr_spikes": spikes,
            "seasonality": seasons,
        },
    )
    _dump(data / "stress.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "stress": stress, "g_versus_f": harbor, "l_xray": xray})
    _dump(data / "trials.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "n_trials": n_trials_box[0], "trials": trials})
    _dump(data / "features.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "features": feature_dicts()})
    _dump(data / "curves.json", {"schema_version": SCHEMA_VERSION, "data_as_of": as_of, "series": curves, "note": "Month-end wealth, rebased to 1 at the start of each series' scored window. Daily models, 21-session horizon, lag 1."})
    returns = prices[list(FUNDS)].pct_change()
    returns.iloc[0] = 0.0
    payload_returns = {
        "schema_version": SCHEMA_VERSION,
        "data_as_of": as_of,
        "dates": [_iso(ts) for ts in prices.index],
    }
    for fund in FUNDS:
        payload_returns[fund] = [None if not np.isfinite(v) else round(float(v), 6) for v in returns[fund].to_numpy()]
    if "L2050" in snap.daily.columns:
        lret = snap.daily["L2050"].pct_change()
        payload_returns["L2050"] = [None if not np.isfinite(v) else round(float(v), 6) for v in lret.to_numpy()]
    _dump(data / "returns.json", payload_returns)
    observed = [_iso(ts) for ts in prices.index]
    last_day = prices.index.max().date()
    projected = [d.isoformat() for d in project_tsp_days(last_day + pd.Timedelta(days=1), last_day.replace(year=last_day.year + 2))]
    _dump(
        data / "calendar.json",
        {
            "schema_version": SCHEMA_VERSION,
            "data_as_of": as_of,
            "observed": observed,
            "projected": projected,
            "projected_note": "Dates after the last share price are a projection: weekdays minus NYSE holidays, Columbus Day, and Veterans Day.",
        },
    )
    alert_path = data / "alert.json"
    if not alert_path.exists():
        _dump(
            alert_path,
            {
                "schema_version": SCHEMA_VERSION,
                "data_as_of": as_of,
                "flipped": False,
                "message": "No tsp check has been run yet.",
            },
        )
    _render(
        dist,
        {
            "not_advice": NOT_ADVICE,
            "today": today,
            "scoreboard": scoreboard,
            "features": feature_dicts(),
            "meta": meta,
            "seasonality": seasons,
            "calibration": detail["calibration"],
            "cost": detail["cost"],
            "missed": detail["missed"],
            "regime": detail["regime"],
            "regime_sessions": detail["regime_sessions"],
            "regime_table": detail["regime_table"],
            "stress": stress,
            "xray": xray,
            "harbor": harbor,
            "events_note": events["note"],
            "event_counts": [{"category": row["category"], "n": row["n_events"]} for row in events["categories"]],
        },
    )
    _log(f"build finished in {meta['elapsed_seconds']}s, {len(scoreboard)} scoreboard rows, {n_trials_box[0]} trials")
    return {"today": today, "scoreboard": scoreboard, "meta": meta, "dist": str(dist)}
