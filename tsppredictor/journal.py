"""Local, reviewable interchange for the disk and browser decision journals.

The journal is educational notes only: importing it never calls a TSP service
or creates a transfer.  Import is deliberately additive.  Entries with the
same stable id and different content are reported as conflicts, never silently
overwritten, and any changed local file receives a timestamped backup first.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from tsppredictor import NOT_ADVICE

FUNDS = {"G", "F", "C", "S", "I"}
INTERCHANGE_KIND = "tsp_decision_journal"
INTERCHANGE_SCHEMA_VERSION = 1


class JournalError(ValueError):
    """Raised when a local journal or an interchange document is invalid."""


def _canonical_payload(row: Mapping) -> dict:
    payload = {
        "date": row["date"],
        "fund": row["fund"],
        "reason": row["reason"],
        "confidence": row["confidence"],
    }
    if row.get("tags"):
        payload["tags"] = list(row["tags"])
    return payload


def _legacy_id(payload: Mapping) -> str:
    # Legacy ids hash only the original four fields so adding tags never re-keys an entry.
    core = {key: payload[key] for key in ("date", "fund", "reason", "confidence")}
    raw = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "legacy-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_entry(raw: Mapping, *, entry_id: str | None = None) -> dict:
    """Validate one note and return its portable, stable representation."""
    if not isinstance(raw, Mapping):
        raise JournalError("journal entry must be an object")
    try:
        decision_date = date.fromisoformat(str(raw["date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalError("journal entry date must be YYYY-MM-DD") from exc
    fund = str(raw.get("fund", "")).upper()
    if fund not in FUNDS:
        raise JournalError("journal entry fund must be G, F, C, S, or I")
    reason = str(raw.get("reason", ""))
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError) as exc:
        raise JournalError("journal entry confidence must be a number from 0 to 1") from exc
    if not 0.0 <= confidence <= 1.0:
        raise JournalError("journal entry confidence must be a number from 0 to 1")
    payload = {
        "date": decision_date.isoformat(),
        "fund": fund,
        "reason": reason,
        "confidence": confidence,
    }
    tags = normalize_tags(raw.get("tags"))
    supplied_id = entry_id if entry_id is not None else raw.get("id")
    stable_id = str(supplied_id) if supplied_id is not None else _legacy_id(payload)
    if not stable_id or len(stable_id) > 160:
        raise JournalError("journal entry id must be a non-empty string of at most 160 characters")
    entry = {"id": stable_id, **payload}
    if tags:
        entry["tags"] = tags
    return entry


def normalize_tags(raw) -> list[str]:
    """Free-form tags such as 'ift-limit' or 'news': lower-case, unique, sorted."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list | tuple):
        raise JournalError("journal entry tags must be a list of strings")
    tags = sorted({str(tag).strip().lower().replace(" ", "-") for tag in raw if str(tag).strip()})
    if any(len(tag) > 40 for tag in tags) or len(tags) > 20:
        raise JournalError("journal entry tags must be at most 20 tags of at most 40 characters")
    return tags


def journal_tags(entry: Mapping) -> list[str]:
    """The tags on one entry (normalized)."""
    return normalize_tags(entry.get("tags"))


def filter_by_tag(entries: Iterable[Mapping], tag: str) -> list[dict]:
    wanted = normalize_tags([tag])[0]
    return [dict(entry) for entry in entries if wanted in journal_tags(entry)]


def new_entry(*, decision_date: str, fund: str, reason: str = "", confidence: float = 0.0,
              tags: Iterable[str] | None = None) -> dict:
    """Create a new journal entry with a fresh stable id."""
    return normalize_entry(
        {"date": decision_date, "fund": fund, "reason": reason, "confidence": confidence, "tags": list(tags or [])},
        entry_id="journal-" + uuid4().hex,
    )


def _normalize_entries(entries: Iterable[Mapping], *, source: str) -> list[dict]:
    """Normalize entries while giving repeated legacy rows deterministic ids."""
    rows = []
    seen: dict[str, int] = {}
    for raw in entries:
        row = normalize_entry(raw)
        base_id = row["id"]
        duplicate_number = seen.get(base_id, 0)
        if duplicate_number:
            if raw.get("id") is not None:
                raise JournalError(f"{source} contains duplicate entry id {base_id!r}")
            row["id"] = f"{base_id}-{duplicate_number + 1}"
        seen[base_id] = duplicate_number + 1
        rows.append(row)
    return rows


def read_journal(path: Path) -> list[dict]:
    """Read JSONL notes without changing legacy rows on disk."""
    if not path.exists():
        return []
    raw_rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise JournalError(f"journal line {line_no} is not valid JSON") from exc
        raw_rows.append(raw)
    try:
        return _normalize_entries(raw_rows, source="journal")
    except JournalError as exc:
        raise JournalError(f"journal: {exc}") from exc


def append_entry(path: Path, entry: Mapping) -> dict:
    """Append one validated note.  This is the ordinary local journal action."""
    normalized = normalize_entry(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, sort_keys=True) + "\n")
    return normalized


def make_interchange(entries: Iterable[Mapping]) -> dict:
    """Return the versioned document shared by the disk and browser journals."""
    normalized = _normalize_entries(entries, source="journal entries")
    return {
        "schema_version": INTERCHANGE_SCHEMA_VERSION,
        "kind": INTERCHANGE_KIND,
        "not_advice": NOT_ADVICE,
        "entries": normalized,
    }


def export_journal(journal_path: Path, output_path: Path) -> dict:
    """Export disk JSONL to a portable, versioned JSON document."""
    payload = make_interchange(read_journal(journal_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"output": str(output_path), "entries": len(payload["entries"]), "kind": INTERCHANGE_KIND}


def read_interchange(path: Path) -> list[dict]:
    """Validate an interchange file before an import preview or write."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JournalError(f"could not read interchange file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JournalError("interchange file is not valid JSON") from exc
    if not isinstance(document, Mapping):
        raise JournalError("interchange document must be an object")
    if document.get("kind") != INTERCHANGE_KIND:
        raise JournalError(f"interchange kind must be {INTERCHANGE_KIND!r}")
    if document.get("schema_version") != INTERCHANGE_SCHEMA_VERSION:
        raise JournalError(f"interchange schema_version must be {INTERCHANGE_SCHEMA_VERSION}")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise JournalError("interchange entries must be an array")
    if any(not isinstance(row, Mapping) or row.get("id") is None for row in entries):
        raise JournalError("interchange entries must include stable ids")
    return _normalize_entries(entries, source="interchange")


def preview_import(journal_path: Path, interchange_path: Path) -> dict:
    """Compare an interchange document with disk notes without writing either."""
    existing = {row["id"]: row for row in read_journal(journal_path)}
    incoming = read_interchange(interchange_path)
    new_entries = []
    duplicate_ids = []
    conflicts = []
    for row in incoming:
        present = existing.get(row["id"])
        if present is None:
            new_entries.append(row)
        elif _canonical_payload(present) == _canonical_payload(row):
            duplicate_ids.append(row["id"])
        else:
            conflicts.append(
                {
                    "id": row["id"],
                    "local": _canonical_payload(present),
                    "incoming": _canonical_payload(row),
                }
            )
    return {
        "kind": INTERCHANGE_KIND,
        "journal": str(journal_path),
        "interchange": str(interchange_path),
        "new_entries": new_entries,
        "duplicate_ids": duplicate_ids,
        "conflicts": conflicts,
    }


def _write_jsonl_atomically(path: Path, entries: Iterable[Mapping]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        for entry in entries:
            handle.write(json.dumps(dict(entry), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.replace(path)


def _backup(path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1
    shutil.copy2(path, candidate)
    return candidate


def import_interchange(
    journal_path: Path,
    interchange_path: Path,
    *,
    on_conflict: str = "keep-local",
) -> dict:
    """Append previewed entries, retaining local conflicts and a backup copy.

    ``keep-local`` imports only new entries.  ``error`` reports conflicts and
    makes no change at all.  ``prefer-incoming`` also replaces conflicting
    local entries with the incoming version, always after the timestamped
    backup of the local file is written.
    """
    if on_conflict not in {"keep-local", "error", "prefer-incoming"}:
        raise JournalError("on_conflict must be 'keep-local', 'error', or 'prefer-incoming'")
    preview = preview_import(journal_path, interchange_path)
    if preview["conflicts"] and on_conflict == "error":
        raise JournalError("interchange conflicts found; no local journal changes were made")
    new_entries = preview["new_entries"]
    replace = {}
    if on_conflict == "prefer-incoming" and preview["conflicts"]:
        incoming = {row["id"]: row for row in read_interchange(interchange_path)}
        replace = {conflict["id"]: incoming[conflict["id"]] for conflict in preview["conflicts"]}
    if not new_entries and not replace:
        return {**preview, "added": 0, "replaced": 0, "backup": None}
    existing = read_journal(journal_path)
    backup = _backup(journal_path) if journal_path.exists() else None
    merged = [replace.get(row["id"], row) for row in existing]
    _write_jsonl_atomically(journal_path, [*merged, *new_entries])
    return {**preview, "added": len(new_entries), "replaced": len(replace),
            "backup": None if backup is None else str(backup)}


def journal_diff(a: Iterable[Mapping], b: Iterable[Mapping]) -> dict:
    """Entries only in ``a``, only in ``b``, identical, and same-id conflicts."""
    left = {row["id"]: row for row in _normalize_entries(a, source="a")}
    right = {row["id"]: row for row in _normalize_entries(b, source="b")}
    conflicts = [
        {"id": key, "a": _canonical_payload(left[key]), "b": _canonical_payload(right[key])}
        for key in sorted(left.keys() & right.keys())
        if _canonical_payload(left[key]) != _canonical_payload(right[key])
    ]
    return {
        "only_in_a": [left[key] for key in sorted(left.keys() - right.keys())],
        "only_in_b": [right[key] for key in sorted(right.keys() - left.keys())],
        "identical": sorted(key for key in left.keys() & right.keys()
                            if _canonical_payload(left[key]) == _canonical_payload(right[key])),
        "conflicts": conflicts,
    }


def interchange_stats(path: Path) -> dict:
    """Count, date range, funds and tags in an interchange file."""
    entries = read_interchange(path)
    dates = sorted(row["date"] for row in entries)
    funds: dict[str, int] = {}
    tags: dict[str, int] = {}
    for row in entries:
        funds[row["fund"]] = funds.get(row["fund"], 0) + 1
        for tag in row.get("tags", []):
            tags[tag] = tags.get(tag, 0) + 1
    return {"path": str(path), "count": len(entries), "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None, "funds": dict(sorted(funds.items())),
            "tags": dict(sorted(tags.items()))}


def sync_folder(journal_path: Path, folder: Path, *, on_conflict: str = "keep-local",
                filename: str = "tsp-journal.json") -> dict:
    """Journal File Sync: import the shared file from ``folder`` (if any), then export back to it.

    The folder is one you pick (a USB stick, a NAS share, a synced folder).  The
    import step keeps local entries on conflict unless told otherwise and always
    backs up the local journal first; the export step writes atomically.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise JournalError(f"sync folder does not exist: {folder}")
    shared = folder / filename
    imported = None
    if shared.exists():
        imported = import_interchange(journal_path, shared, on_conflict=on_conflict)
    payload = make_interchange(read_journal(journal_path))
    temporary = shared.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(shared)
    return {"shared_file": str(shared), "imported": None if imported is None else {
        "added": imported["added"], "replaced": imported.get("replaced", 0),
        "conflicts": len(imported["conflicts"]), "backup": imported["backup"]},
        "exported": len(payload["entries"])}
