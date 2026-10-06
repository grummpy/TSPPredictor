"""Diagnostics that should reject stale-price artifacts and empty edges."""

from __future__ import annotations

import pandas as pd


def stale_price_diagnostic(asset: str, trigger: str, hold_sessions: int) -> dict:
    """Flag rules that buy the I Fund off a same-day or previous-day U.S. move.

    The I Fund is fair-value priced because international markets close before
    the U.S. close. A one-session hold that keys off a large C Fund up day is
    the pattern that pricing is meant to remove, so it is marked suspect
    without being turned into a strategy.
    """
    trigger_l = trigger.lower()
    keys_off_us = any(token in trigger_l for token in ("c_up", "c fund up", "us up", "spx up", "big c"))
    suspect = asset.upper() == "I" and hold_sessions <= 1 and keys_off_us
    return {
        "suspect": suspect,
        "asset": asset,
        "trigger": trigger,
        "hold_sessions": hold_sessions,
        "reason": (
            "Suspect stale-price pattern: the I Fund uses fair-value pricing, so a one-session "
            "rule that buys I after a large U.S. up day is not a tradable edge."
            if suspect
            else "No stale-price pattern detected in this rule definition."
        ),
    }


def empirical_next_day_i(prices: pd.DataFrame, c_threshold: float = 0.02) -> dict:
    """Describe the next-session I return after a large C up day. Not a strategy."""
    c = prices["C"].pct_change()
    i_next = prices["I"].pct_change().shift(-1)
    mask = c > c_threshold
    sample = i_next[mask].dropna()
    return {
        "n": int(sample.shape[0]),
        "mean_next_i": float(sample.mean()) if len(sample) else None,
        "note": "Descriptive only. This is not a signal and is not traded.",
    }


def toy_buy_i_after_c_up() -> dict:
    return stale_price_diagnostic(asset="I", trigger="buy I after a big C up day", hold_sessions=1)
