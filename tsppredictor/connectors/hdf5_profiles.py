"""HDF5 (h5py): one file holding every saved price profile (optional ``h5py``)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FIELDS = ("count", "last", "ret_mean", "ret_std")


def available() -> bool:
    try:
        import h5py  # noqa: F401
    except ImportError:
        return False
    return True


def write_profiles(history: list[dict], out: Path) -> dict:
    if not available():
        raise RuntimeError("HDF5 export needs h5py (pip install h5py)")
    import h5py

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    labels = [str(r.get("data_as_of") or r.get("_file") or i) for i, r in enumerate(history)]
    funds = sorted({f for r in history for f in {**(r.get("funds") or {}), **(r.get("l_funds") or {})}})
    with h5py.File(out, "w") as h5:
        h5.attrs["kind"] = "tsppredictor_price_profiles"
        h5.create_dataset("labels", data=np.array(labels, dtype="S32"))
        for fund in funds:
            group = h5.create_group(fund.replace("/", "_"))
            for field in FIELDS:
                values = []
                for r in history:
                    merged = {**(r.get("funds") or {}), **(r.get("l_funds") or {})}
                    v = (merged.get(fund) or {}).get(field)
                    values.append(np.nan if v is None else float(v))
                group.create_dataset(field, data=np.array(values, dtype="f8"))
        h5.create_dataset("flags_json", data=np.array([json.dumps(r.get("flags", [])) for r in history], dtype=h5py.string_dtype()))
    return {"path": str(out), "profiles": len(history), "funds": funds}


def read_profiles(path: Path) -> dict:
    import h5py

    with h5py.File(path, "r") as h5:
        labels = [x.decode() for x in h5["labels"][...]]
        series = {name: {f: h5[name][f][...].tolist() for f in FIELDS} for name in h5 if isinstance(h5[name], h5py.Group)}
    return {"labels": labels, "series": series}
