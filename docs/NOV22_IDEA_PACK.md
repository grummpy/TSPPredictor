# Nov 22 idea pack: checklist

Source: Daily Idea Pack, Sun Nov 22 2026 (40 items). Status: **done**, **partial** (works, with a stated limit), or **skipped**.

Headline fix: backtests no longer assume CPI on the 15th and unemployment on the 8th. Both now enter on their **real BLS release dates** from a bundled, cited calendar (`data/snapshot/macro/primary/bls_release_calendar.csv`, 662 rows), with offline fallbacks. October 2024 CPI is visible from 2024-11-13 (it was the 15th before). The September 2025 jobs report, delayed by the shutdown to 2025-11-20, no longer leaks into October 2025 features. October 2025 CPI, which BLS never published, waits for the next release. Months before the calendar's coverage use a conservative fallback day (the latest normal release day in the table, so it never runs early).

## 10 improvements

| # | Item | Status | Where |
|---|------|--------|-------|
| 1 | Point-in-time macro inputs (ALFRED) | partial | `connectors/alfred.py` (output_type=4 first prints, cached under `data/cache/alfred/`); the build overlays first prints automatically when cached. No `FRED_API_KEY` is in the repo, so the shipped build still reports `first_print_vintages_available: false`. |
| 2 | Actual publication calendar | done | `data/release_calendar.py`, `features/lags.py`, `features/monthly.py` (as-of release dates instead of `shift(1)`) |
| 3 | Show unpaired lags, run the missing lag | done | New `daily h=63 lag=2` block; the Methods page lists unpaired strategies and missing runs; `lag_sensitivity()["missing_runs"]` |
| 4 | Prices on by default | done | All build paths already passed prices; `simulate_targets()` without prices now raises a `DeprecationWarning` |
| 5 | Verify command | done | `tsp verify`, `provenance.verify_build_manifest()`; the manifest now records SHA-256 for every output |
| 6 | Prefer-incoming import | done | `import_interchange(on_conflict="prefer-incoming")`, always after the backup; also in the browser |
| 7 | Not-advice in exports | done | `make_interchange()` and the browser export both include `not_advice` |
| 8 | More hand ledgers (two-IFT limit) | done | `test_hand_ledger_third_request_in_month_is_refused`, `test_hand_ledger_limit_resets_in_new_month` |
| 9 | Journal outcome column | done | `tsp journal list` (21/63 sessions vs G) and an outcome table in the browser computed from the bundled `returns.json` |
| 10 | Browser conflict view | done | Side-by-side table with "Import new only", "Prefer incoming", and "Cancel" |

## 10 new functions

| # | Function | Status | Module |
|---|----------|--------|--------|
| 1 | `verify_build_manifest()` | done | `provenance.py` |
| 2 | `entry_outcome(entry, days)` | done | `journal_insights.py` |
| 3 | `confidence_calibration()` | done | `journal_insights.py` |
| 4 | `lag_cost_table()` | done | `evidence.py` |
| 5 | `vintage_gap_report()` | done | `evidence.py` |
| 6 | `journal_diff(a, b)` | done | `journal.py` |
| 7 | `release_date(series, month)` | done | `data/release_calendar.py` |
| 8 | `drift_vs_constant(strategy)` | done | `backtest/compare.py` (in `meta.json` for every monthly rule) |
| 9 | `journal_tags(entry)` | done | `journal.py` (`--tags`, `--tag` filter; legacy ids unchanged) |
| 10 | `interchange_stats(path)` | done | `journal.py`, `tsp journal stats` |

## 10 add-on programs

| # | Add-on | Status | How |
|---|--------|--------|-----|
| 1 | Decision Journal Reviewer | done | `tsp journal review --month YYYY-MM` |
| 2 | Vintage Replay Lab | partial | `tsp vintage-replay`; needs cached ALFRED first prints (key-gated), otherwise it reports the gap and changes nothing |
| 3 | Lag Cost Explainer | done | Methods page table with plain-language rows (a table, not a chart) |
| 4 | Provenance Badge | done | `dist/data/provenance.json`, re-verified on `tsp serve`; badge at the top of the page |
| 5 | Journal File Sync | done | `tsp journal sync --folder <folder you pick>` |
| 6 | IFT Month Diary | done | `tsp ift log`, `tsp ift summary` (refuses a third unrestricted transfer; G-only moves are allowed) |
| 7 | Calibration Card | done | `tsp journal calibration --html card.html` |
| 8 | Backtest Reproducer | done | `tsp reproduce` (rebuilds into `data/cache/reproduce`, ignores timing fields) |
| 9 | Allocation Drift Viewer | done | `dist/data/allocation-drift.json` plus a per-rule viewer on the Methods page |
| 10 | Release Day Alerts | done | `tsp check` notes CPI/jobs releases in the next 7 days; `tsp releases`; `release_context()` for journal entries |

## 10 connectors/plugins (all off until installed or configured)

| # | Connector | Status | Notes |
|---|-----------|--------|-------|
| 1 | ALFRED API | partial | Implemented and unit-tested; not exercised live (needs `FRED_API_KEY`) |
| 2 | BLS release calendar ICS | partial | Parser and merge tested; BLS returns 403 to anonymous scripts, so `tsp update --release-calendar` needs `TSP_CONTACT_EMAIL` or `--ics-file` with a browser-downloaded ICS. The bundled calendar was built from the BLS archives. |
| 3 | Fed H.15 DDP | done | Real package `bf17364827e38702b42a58cf8eaa3f78`; fixture is real Fed data; `tsp update --h15` |
| 4 | Narwhals | partial | `connectors/frames.py` adapter; the pipeline is still pandas-native |
| 5 | Pointblank | partial | Optional report alongside native price checks (not installed here) |
| 6 | Evidence.dev | done | `tsp export evidence --output <dir>` writes a project skeleton (not run under Evidence here) |
| 7 | Obsidian vault export | done | `tsp export obsidian --vault <dir>` |
| 8 | LocalSend | done | `tsp export localsend --host <LAN IP>`: loopback/private only (refuses CGNAT, multicast, link-local, public); tested against a fake receiver, not a real device. LocalSend uses self-signed certificates, so TLS verification is off for that LAN hop. |
| 9 | whylogs | partial | Native profile and shift flags always run; whylogs output only when installed |
| 10 | MLflow tracking | done | Local `data/cache/runs.jsonl` always; MLflow only when `MLFLOW_TRACKING_URI` is set and mlflow is installed |

**Totals: 33 done, 7 partial, 0 skipped.**
