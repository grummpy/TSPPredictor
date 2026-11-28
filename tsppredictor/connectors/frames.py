"""Narwhals: one dataframe API so pipeline helpers can accept pandas or faster engines.

Narwhals is optional.  When installed, ``to_pandas`` accepts any frame Narwhals
supports (polars, pyarrow, modin, ...).  Without it, only pandas is accepted.
"""

from __future__ import annotations

import pandas as pd


def available() -> bool:
    try:
        import narwhals  # noqa: F401
    except ImportError:
        return False
    return True


def is_modin(frame) -> bool:
    """Modin DataFrames (``modin.pandas``) are a drop-in pandas engine."""
    return type(frame).__module__.split(".")[0] == "modin" and hasattr(frame, "_to_pandas")


def to_pandas(frame) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame
    if is_modin(frame) and not available():
        # Modin works without Narwhals: it ships its own pandas conversion.
        converted = frame._to_pandas()
        if not isinstance(converted, pd.DataFrame):
            raise TypeError("modin frame did not convert to pandas")
        return converted
    if not available():
        raise TypeError("non-pandas frames need the optional 'narwhals' package")
    import narwhals as nw

    return nw.from_native(frame, eager_only=True).to_pandas()


def engine_name(frame) -> str:
    if isinstance(frame, pd.DataFrame):
        return "pandas"
    if available():
        import narwhals as nw

        try:
            return str(nw.get_native_namespace(nw.from_native(frame, eager_only=True)).__name__)
        except TypeError:
            pass
    return type(frame).__module__.split(".")[0]
