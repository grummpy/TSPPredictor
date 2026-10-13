"""Synthetic-only tests for the local disk/browser journal interchange."""

import json
from pathlib import Path

import pytest

from tsppredictor.journal import (
    JournalError,
    append_entry,
    export_journal,
    import_interchange,
    make_interchange,
    new_entry,
    preview_import,
    read_journal,
)


def _write_interchange(path, entries):
    path.write_text(json.dumps(make_interchange(entries)), encoding="utf-8")


def test_journal_round_trip_preview_conflicts_and_recoverable_backup(tmp_path):
    source = tmp_path / "source.jsonl"
    first = new_entry(decision_date="2026-10-13", fund="C", reason="synthetic note", confidence=0.4)
    append_entry(source, first)
    exported = tmp_path / "journal.json"
    result = export_journal(source, exported)
    assert result["entries"] == 1

    target = tmp_path / "target.jsonl"
    preview = preview_import(target, exported)
    assert [row["id"] for row in preview["new_entries"]] == [first["id"]]
    imported = import_interchange(target, exported)
    assert imported["added"] == 1
    assert imported["backup"] is None
    assert read_journal(target) == [first]

    duplicate_preview = preview_import(target, exported)
    assert duplicate_preview["duplicate_ids"] == [first["id"]]
    assert import_interchange(target, exported)["added"] == 0

    conflicting = {**first, "reason": "same id, different synthetic note"}
    conflict_file = tmp_path / "conflict.json"
    _write_interchange(conflict_file, [conflicting])
    conflict_preview = preview_import(target, conflict_file)
    assert len(conflict_preview["conflicts"]) == 1
    with pytest.raises(JournalError, match="no local journal changes"):
        import_interchange(target, conflict_file, on_conflict="error")
    assert read_journal(target) == [first]
    assert import_interchange(target, conflict_file, on_conflict="keep-local")["added"] == 0

    second = new_entry(decision_date="2026-10-14", fund="G", reason="another synthetic note", confidence=0.2)
    second_file = tmp_path / "second.json"
    _write_interchange(second_file, [second])
    second_import = import_interchange(target, second_file)
    backup = second_import["backup"]
    assert second_import["added"] == 1
    assert backup is not None
    assert read_journal(Path(backup)) == [first]
    assert read_journal(target) == [first, second]


def test_journal_interchange_rejects_invalid_or_duplicate_ids_before_writing(tmp_path):
    journal = tmp_path / "journal.jsonl"
    row = new_entry(decision_date="2026-10-13", fund="S", reason="synthetic", confidence=0.5)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1, "kind": "tsp_decision_journal", "entries": [row, row]}))
    with pytest.raises(JournalError, match="duplicate entry id"):
        preview_import(journal, bad)
    missing_id = tmp_path / "missing-id.json"
    raw_without_id = {key: value for key, value in row.items() if key != "id"}
    missing_id.write_text(json.dumps({"schema_version": 1, "kind": "tsp_decision_journal", "entries": [raw_without_id]}))
    with pytest.raises(JournalError, match="stable ids"):
        preview_import(journal, missing_id)
    assert not journal.exists()
