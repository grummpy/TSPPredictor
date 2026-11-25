# Six-census audit: TSPPredictor, 2026-11-22

Inventory only. Nothing in this PR changes app code or fixes a finding.

- Revision audited: `main` at `6718278`
- Launcher OS targets: none. TSPPredictor is a CLI-only Python package, so per-OS launcher checks are NOT_APPLICABLE.
- Data: synthetic and public only. The snapshot probe worked on a temporary copy that was deleted afterwards.

## Counts

| Census | Rows | Breakdown |
|---|---|---|
| Host allowlist | 0 decision sites | The only host literal is the bind constant `BIND_HOST = "127.0.0.1"` (`cli.py:20`); `serve` binds there unconditionally. No allow/deny check exists to probe |
| Verify path | 6 | 5 fail-closed, 1 NOT_APPLICABLE (test helper) |
| Judge independence | 0 | No model-graded evaluation |
| Media twins | 2 | `docs/cover.jpg`, `docs/ui-art-reference.jpg`; both unique |
| Platform paths | 1 | `git` subprocess in `build.py:106` (resolved on PATH; no launcher) |
| User fields | 8 | 6 user, 1 system-overwrite, 1 system-append (5 heuristic plus 3 manual addenda) |

## Findings

No high or medium flaws.

1. **Verify:** `snapshot.verify_manifest` only reports, but `load_snapshot` refuses on mismatched or required-missing files, and `MANIFEST.csv` is itself required. Probe result: a deleted manifest plus a tampered CSV is refused. This differs from the HUD's legacy-restore hole.
2. **User fields (low):** the browser journal import saves a single `JOURNAL_BACKUP_KEY` snapshot (`app.js:592`), so each import replaces the previous backup. Import itself only appends new entries and keeps local entries on conflict.
3. **Host (informational):** loopback-only serving is enforced by the bind address alone, which is the correct shape here because there's nothing to allowlist.

## Method

- Verify, platform, and user-field rows come from the static heuristic scanner. Every row was hand-reviewed.
- Media: sha256 of tracked media; earliest add commit for lineage.
