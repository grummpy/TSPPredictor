"""Repository paths. The snapshot ships in the repo; cache and user data do not."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Directory that contains ``data/snapshot/MANIFEST.csv``."""
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "data" / "snapshot" / "MANIFEST.csv").exists():
            return candidate
    cwd = Path.cwd()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "data" / "snapshot" / "MANIFEST.csv").exists():
            return candidate
    raise FileNotFoundError("Could not find data/snapshot/MANIFEST.csv")


def snapshot_dir() -> Path:
    return repo_root() / "data" / "snapshot"


def cache_dir() -> Path:
    path = repo_root() / "data" / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir() -> Path:
    path = repo_root() / "data" / "user"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dist_dir() -> Path:
    path = repo_root() / "dist"
    path.mkdir(parents=True, exist_ok=True)
    return path
