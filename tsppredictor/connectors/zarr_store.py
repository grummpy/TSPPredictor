"""Chunked storage for bootstrap and walk-forward arrays (optional ``zarr``).

``save_arrays`` writes a Zarr group when zarr is installed, else a compressed
``.npz``. ``load_arrays`` reads either. The build does not use this cache yet;
it is the storage layer for a later rebuild cache.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np


def available() -> bool:
    try:
        import zarr  # noqa: F401
    except ImportError:
        return False
    return True


def save_arrays(path: Path, arrays: dict[str, np.ndarray], *, chunk_rows: int = 4096) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for name in arrays:
        if not name.isidentifier():
            raise ValueError(f"array name {name!r} must be an identifier")
    if available():
        import zarr

        target = path.with_suffix(".zarr")
        group = zarr.open_group(str(target), mode="w")
        for name, arr in arrays.items():
            arr = np.asarray(arr)
            chunks = (min(chunk_rows, max(arr.shape[0], 1)),) + arr.shape[1:] if arr.ndim else ()
            group.create_array(name, shape=arr.shape, dtype=arr.dtype, chunks=chunks or None)[...] = arr
        return target
    target = path.with_suffix(".npz")
    tmp = target.with_name(f".{target.stem}.{os.getpid()}.tmp.npz")
    np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in arrays.items()})
    os.replace(tmp, target)
    return target


def load_arrays(path: Path) -> dict[str, np.ndarray]:
    path = Path(path)
    z, npz = path.with_suffix(".zarr"), path.with_suffix(".npz")
    if z.exists():
        if not available():
            raise RuntimeError(f"{z.name} needs zarr to read")
        import zarr

        group = zarr.open_group(str(z), mode="r")
        return {name: np.asarray(group[name][...]) for name in group.array_keys()}
    if npz.exists():
        with np.load(npz) as data:
            return {k: data[k] for k in data.files}
    raise FileNotFoundError(f"no array store at {z} or {npz}")
