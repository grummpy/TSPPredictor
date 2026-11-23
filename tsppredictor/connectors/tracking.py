"""Log each backtest run's parameters and metrics (MLflow when configured).

MLflow is used only when installed AND ``MLFLOW_TRACKING_URI`` is set.  A
local JSONL run log under ``data/cache/runs.jsonl`` is always written.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tsppredictor.paths import cache_dir


def mlflow_enabled() -> bool:
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return False
    try:
        import mlflow  # noqa: F401
    except ImportError:
        return False
    return True


def log_run(params: dict, metrics: dict, *, run_name: str = "tsp-build", path: Path | None = None) -> dict:
    record = {"at": datetime.now(UTC).isoformat(), "run_name": run_name,
              "params": params, "metrics": {k: v for k, v in metrics.items() if isinstance(v, int | float)}}
    path = path or (cache_dir() / "runs.jsonl")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    record["mlflow"] = False
    if mlflow_enabled():
        import mlflow

        with mlflow.start_run(run_name=run_name):
            mlflow.log_params({k: str(v) for k, v in params.items()})
            mlflow.log_metrics(record["metrics"])
        record["mlflow"] = True
    return record
