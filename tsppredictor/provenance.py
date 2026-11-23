"""Verify a build's SHA-256 manifest and reproduce old reports from it."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_NAME = "build-manifest.json"
PROVENANCE_NAME = "provenance.json"
# Files that legitimately differ between two otherwise identical builds.
VOLATILE_KEYS = {"elapsed_seconds"}
UNHASHED = {f"data/{MANIFEST_NAME}", f"data/{PROVENANCE_NAME}", "data/alert.json"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_hashes(dist: Path) -> dict[str, str]:
    """SHA-256 of every built output under ``dist`` except the manifest itself."""
    dist = Path(dist)
    out = {}
    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(dist).as_posix()
        if rel in UNHASHED:
            continue
        out[rel] = sha256_file(path)
    return out


def stamp_outputs(dist: Path) -> dict:
    """Add the ``outputs`` hash table to an existing build-manifest.json."""
    path = Path(dist) / "data" / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["outputs"] = output_hashes(dist)
    manifest["outputs_algorithm"] = "sha256"
    path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    return manifest


def verify_build_manifest(dist: Path, snapshot: Path | None = None) -> dict:
    """Recheck every hash in build-manifest.json (outputs and the snapshot manifest)."""
    dist = Path(dist)
    path = dist / "data" / MANIFEST_NAME
    if not path.exists():
        return {"ok": False, "checked": 0, "problems": [f"missing {MANIFEST_NAME}"]}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        problems.append("manifest has no output hashes (built before verify support)")
        outputs = {}
    checked = 0
    for rel, expected in sorted(outputs.items()):
        candidate = dist / rel
        checked += 1
        if not candidate.exists():
            problems.append(f"missing: {rel}")
        elif sha256_file(candidate) != expected:
            problems.append(f"changed: {rel}")
    current = output_hashes(dist)
    for rel in sorted(set(current) - set(outputs)):
        problems.append(f"unlisted: {rel}")
    if snapshot is not None:
        expected = (manifest.get("snapshot") or {}).get("manifest_sha256")
        actual = sha256_file(Path(snapshot) / "MANIFEST.csv") if (Path(snapshot) / "MANIFEST.csv").exists() else None
        checked += 1
        if expected != actual:
            problems.append("snapshot MANIFEST.csv differs from the one this build used")
    return {"ok": not problems, "checked": checked, "problems": problems,
            "source_revision": (manifest.get("source") or {}).get("revision"),
            "data_as_of": manifest.get("data_as_of")}


def write_provenance_badge(dist: Path, snapshot: Path | None = None) -> dict:
    """Provenance Badge: record the verify result for the report page."""
    result = verify_build_manifest(dist, snapshot)
    badge = {"verified": result["ok"], "checked": result["checked"], "problems": result["problems"][:20],
             "source_revision": result.get("source_revision"), "data_as_of": result.get("data_as_of"),
             "verified_at": datetime.now(UTC).isoformat()}
    (Path(dist) / "data" / PROVENANCE_NAME).write_text(json.dumps(badge, indent=2), encoding="utf-8")
    return badge


def _normalized_json(path: Path):
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    return strip(json.loads(path.read_text(encoding="utf-8")))


def compare_builds(reference: Path, rebuilt: Path) -> dict:
    """Backtest Reproducer: compare a rebuilt dist with the reference outputs.

    JSON outputs are compared after dropping volatile keys (build timing);
    everything else must match byte for byte.
    """
    reference, rebuilt = Path(reference), Path(rebuilt)
    ref_manifest = json.loads((reference / "data" / MANIFEST_NAME).read_text(encoding="utf-8"))
    files = sorted((ref_manifest.get("outputs") or output_hashes(reference)).keys())
    matched, differed, missing = [], [], []
    for rel in files:
        a, b = reference / rel, rebuilt / rel
        if not b.exists():
            missing.append(rel)
            continue
        if rel.endswith(".json"):
            same = _normalized_json(a) == _normalized_json(b)
        else:
            same = sha256_file(a) == sha256_file(b)
        (matched if same else differed).append(rel)
    return {"reproduced": not differed and not missing, "matched": len(matched), "differed": differed,
            "missing": missing}


def reproduce(reference_dist: Path, work_dir: Path) -> dict:
    """Rebuild into ``work_dir`` from the current snapshot and compare with ``reference_dist``."""
    import os

    from tsppredictor.build import run_build

    ref_manifest = json.loads((Path(reference_dist) / "data" / MANIFEST_NAME).read_text(encoding="utf-8"))
    previous = os.environ.get("TSP_DIST_DIR")
    os.environ["TSP_DIST_DIR"] = str(work_dir)
    try:
        run_build()
    finally:
        if previous is None:
            os.environ.pop("TSP_DIST_DIR", None)
        else:
            os.environ["TSP_DIST_DIR"] = previous
    result = compare_builds(Path(reference_dist), Path(work_dir))
    result["reference_revision"] = (ref_manifest.get("source") or {}).get("revision")
    return result
