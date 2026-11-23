"""Regression tests for stable, distinct journal export file identities."""
from tsppredictor.connectors.exports import export_obsidian
from tsppredictor.journal import new_entry


def test_obsidian_keeps_distinct_entries_and_reexports_by_id(tmp_path):
    base = new_entry(decision_date="2026-11-22", fund="C", reason="Same visible reason")
    first = dict(base, id="../same/one")
    second = dict(base, id="../same/two")
    vault = tmp_path / "vault"
    target = vault / "TSP Journal"
    target.mkdir(parents=True)
    old = target / "2026-11-22 C same-visible-reason.md"
    old.write_text("Existing note with manual changes", encoding="utf-8")

    assert export_obsidian([first, second], vault)["notes"] == 2
    generated = [path for path in target.glob("TSP entry *.md")]
    assert len(generated) == 2
    owner = next(path for path in generated if "id: ../same/one" in path.read_text())
    other = next(path for path in generated if "id: ../same/two" in path.read_text())
    old_other = other.read_bytes()
    updated = dict(first, date="2026-11-23", fund="G", reason="Updated reason")
    export_obsidian([updated], vault)

    assert set(target.glob("*.md")) == {*generated, old}
    assert "Updated reason" in owner.read_text()
    assert other.read_bytes() == old_other
    assert old.read_text() == "Existing note with manual changes"
