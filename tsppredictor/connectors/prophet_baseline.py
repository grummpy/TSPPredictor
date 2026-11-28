"""Prophet: an optional seasonal *toy* baseline (optional ``prophet``).

STUB status: ``prophet`` is not a project dependency and was not installed or
tested against a real fit here. The adapter fits monthly C Fund returns only
when prophet is importable, and every result carries ``toy: True`` and is meant
to be shown only next to the existing models' out-of-sample record.
"""

from __future__ import annotations

import pandas as pd

TOY_LABEL = "Toy seasonal baseline (Prophet). Not a model of record and not a forecast you should act on."


def available() -> bool:
    try:
        import prophet  # noqa: F401
    except ImportError:
        return False
    return True


def prophet_frame(monthly: pd.DataFrame, column: str = "C Fund") -> pd.DataFrame:
    frame = pd.DataFrame({"ds": pd.to_datetime(monthly["month"].astype(str).str.slice(0, 7) + "-01"),
                          "y": pd.to_numeric(monthly[column], errors="coerce")}).dropna()
    if len(frame) < 24:
        raise ValueError("need at least 24 months")
    return frame.sort_values("ds").reset_index(drop=True)


def toy_baseline(monthly: pd.DataFrame, *, column: str = "C Fund", periods: int = 3, model_factory=None) -> dict:
    frame = prophet_frame(monthly, column)
    if model_factory is None:
        if not available():
            return {"available": False, "toy": True, "label": TOY_LABEL, "reason": "prophet not installed"}
        from prophet import Prophet

        def model_factory():
            return Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model = model_factory()
    model.fit(frame)
    future = model.make_future_dataframe(periods=periods, freq="MS")
    forecast = model.predict(future).tail(periods)
    return {"available": True, "toy": True, "label": TOY_LABEL, "column": column,
            "rows": [{"month": pd.Timestamp(r.ds).strftime("%Y-%m"), "yhat_pct": round(float(r.yhat), 4)}
                     for r in forecast.itertuples()]}
