"""PyArrow Parquet cache for price frames (optional ``pyarrow``).

``save_frame`` writes Parquet when pyarrow is installed and CSV otherwise, and
``load_frame`` reads whichever exists. Writes are atomic.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def available() -> bool:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


def save_frame(frame: pd.DataFrame, path: Path, *, prefer_parquet: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if prefer_parquet and available():
        target = path.with_suffix(".parquet")
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        frame.to_parquet(tmp, engine="pyarrow", index=True)
    else:
        target = path.with_suffix(".csv")
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        frame.to_csv(tmp, index=True, date_format="%Y-%m-%d")
    os.replace(tmp, target)
    return target


def load_frame(path: Path) -> pd.DataFrame:
    path = Path(path)
    parquet, csv = path.with_suffix(".parquet"), path.with_suffix(".csv")
    if parquet.exists():
        if not available():
            raise RuntimeError(f"{parquet.name} needs pyarrow to read")
        return pd.read_parquet(parquet, engine="pyarrow")
    if csv.exists():
        return pd.read_csv(csv, index_col=0, parse_dates=True)
    raise FileNotFoundError(f"no cache at {parquet} or {csv}")
