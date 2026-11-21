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
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

FUNDS = {"G", "F", "C", "S", "I"}
INTERCHANGE_KIND = "tsp_decision_journal"
INTERCHANGE_SCHEMA_VERSION = 1


class JournalError(ValueError):
    """Raised when a local journal or an interchange document is invalid."""


def _canonical_payload(row: Mapping) -> dict:
    return {
        "date": row["date"],
        "fund": row["fund"],
        "reason": row["reason"],
        "confidence": row["confidence"],
    }


def _legacy_id(payload: Mapping) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
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
    supplied_id = entry_id if entry_id is not None else raw.get("id")
    stable_id = str(supplied_id) if supplied_id is not None else _legacy_id(payload)
    if not stable_id or len(stable_id) > 160:
        raise JournalError("journal entry id must be a non-empty string of at most 160 characters")
    return {"id": stable_id, **payload}


def new_entry(*, decision_date: str, fund: str, reason: str = "", confidence: float = 0.0) -> dict:
    """Create a new journal entry with a fresh stable id."""
    return normalize_entry(
        {"date": decision_date, "fund": fund, "reason": reason, "confidence": confidence},
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
    makes no change at all.  There intentionally is no overwrite option.
    """
    if on_conflict not in {"keep-local", "error"}:
        raise JournalError("on_conflict must be 'keep-local' or 'error'")
    preview = preview_import(journal_path, interchange_path)
    if preview["conflicts"] and on_conflict == "error":
        raise JournalError("interchange conflicts found; no local journal changes were made")
    new_entries = preview["new_entries"]
    if not new_entries:
        return {**preview, "added": 0, "backup": None}
    existing = read_journal(journal_path)
    backup = _backup(journal_path) if journal_path.exists() else None
    _write_jsonl_atomically(journal_path, [*existing, *new_entries])
    return {**preview, "added": len(new_entries), "backup": None if backup is None else str(backup)}
