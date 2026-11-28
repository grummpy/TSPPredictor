# Ten-census audit 2026-11-28: grummpy/TSPPredictor

- Scanned revision: `2798d68cef4c` (origin/main, 2026-11-28)
- Fix branch: `grok/census-2026-11-28`
- Method: The PAPM plan gate. Exact inventory of every tracked file (91 artifacts), 10 batches of at most 10, one byte-hashed reduction record per batch, and a coverage ledger of 910 artifact x census rows: 460 covered, 450 NOT_APPLICABLE with a reason. 100% coverage.
- Mirrors the Nov 22 six-census audit (`docs/audits/2026-11-22/`).

## Counts

Sites are the places a census detector fired. Each one got a verdict: already correct, fixed on this branch, accepted (kept, with the reason in `sites.csv`), or NOT_APPLICABLE (the match is not the pattern the census is about).

| Census | What it looks for | Found | Already correct | Fixed | Accepted | NOT_APPLICABLE | Files scanned / N/A |
|---|---|---:|---:|---:|---:|---:|---:|
| 12.1 Double-Decode | a value is percent-decoded twice (a literal %25 or a bare % breaks) | 0 | 0 | 0 | 0 | 0 | 46 / 45 |
| 12.2 Error Regex | an error-classifying regex matches words it should not (keyboard -> auth) | 1 | 0 | 0 | 0 | 1 | 46 / 45 |
| 12.3 Timestamp Filename | a file name built from a timestamp can collide and overwrite | 3 | 3 | 0 | 0 | 0 | 46 / 45 |
| 12.4 Lock Owner | a lock records no owner, so a crash or a second run strands or steals it | 0 | 0 | 0 | 0 | 0 | 46 / 45 |
| 12.5 Silent Catch | an exception is caught and dropped with no logged reason | 18 | 0 | 0 | 18 | 0 | 46 / 45 |
| 12.6 Naive Time | a date/time is read in the wrong zone (UTC or host instead of household ET) | 17 | 8 | 0 | 1 | 8 | 46 / 45 |
| 12.7 Lossy Text | text is cut, replaced or re-encoded without telling anyone | 22 | 1 | 0 | 6 | 15 | 46 / 45 |
| 12.8 Direct Overwrite | a file is overwritten in place, so a crash leaves it truncated | 47 | 3 | 1 | 42 | 1 | 46 / 45 |
| 12.9 Unbounded Memory | an in-memory collection grows for the life of the process | 1 | 0 | 0 | 1 | 0 | 46 / 45 |
| 12.10 Label Truth | a label names a different statistic than the code computes | 86 | 57 | 7 | 0 | 22 | 46 / 45 |
| **Total** | | **195** | **72** | **8** | **68** | **47** | |

## Fixes on this branch

- `976885d8fcf4` fix(profiling): save price_profile.json atomically and describe the real volatility threshold (census 12.8, 12.10)  
  Sites: `tsppredictor/connectors/profiling.py:43`, `tsppredictor/connectors/profiling.py:44`, `tsppredictor/connectors/profiling.py:46`, `tsppredictor/connectors/profiling.py:47`, `tsppredictor/connectors/profiling.py:56`. price_profile.json is read back on the next build to compare profiles; a crash mid-write left truncated JSON and the next build raised on json.loads. Now written to a temp file and replaced. Docstring said a return std moving by more than z-fold (4x) is flagged; code flags |log ratio| > log(z)/4, i.e. about 1.41x for z=4. Label corrected to match the code; test pins 1.5x flagged and 1.3x not.
- `bd36a721dd81` fix(studies): label the scarcity bound as worst-5%, matching its 0.05 quantile (census 12.10 Label Truth)  
  Sites: `tsppredictor/studies.py:435`, `tsppredictor/studies.py:439`, `tsppredictor/studies.py:442`. Code selects sessions at or below the 0.05 quantile (worst 5%), but the key and note said worst decile. Key renamed to worst_5pct_sessions, note corrected, quantile recorded in the output; no in-repo reader used the old key.

Every fix has a test that fails before the change and passes after it; the full test suite passes on the branch.

## Accepted risks (recommendations, not changed here)

- **12.8 Direct Overwrite**, `tsppredictor/data/ingest_tsp.py` line(s) 241: validated staging CSVs are copy2'd over the live snapshot files; a crash mid-copy leaves a truncated CSV (provenance verify would flag the sha mismatch). Recommend os.replace from a staging dir on the same volume.

Files touched by open PRs (#7, #8) were left alone so the census fixes stay separate; the risks above that name an open PR are deferred until it merges.

## Error-regex word tests (12.2)

No error-classifying regexes: all 1 regex hits are NOT_APPLICABLE (see `sites.csv`). Their word-test rows are still in `error_regex_tests.csv` for the record.

## Files here

- `inventory.csv`: every tracked file at the scanned revision, with bytes, sha256, class and batch.
- `batches/B###.json` + `reductions.csv`: one canonical-JSON reduction record per batch; `record_sha256` is the sha256 of the exact file bytes.
- `coverage.csv`: one row per artifact x census, `covered` or `NOT_APPLICABLE` with a reason.
- `sites.csv`: every detector hit with its verdict and reason. `findings.csv`: just the fixed and accepted ones.
- `error_regex_tests.csv`: one row per regex x test message, before and after the fix.
- `census.json`: the totals above, machine-readable.
- `tool/`: the scanner, verdict table and ledger builder used for this run.

## Re-run

```bash
# Check this ledger as committed: hashes, one record per batch, 100% coverage
python3 docs/audits/2026-11-28/tool/ledger.py --verify docs/audits/2026-11-28

# Rebuild it from scratch at the scanned revision (needs node for the regex word tests)
cp -r docs/audits/2026-11-28/tool /tmp/census-tool
git worktree add /tmp/census-src 2798d68cef4c
python3 /tmp/census-tool/scan10.py /tmp/census-src TSPPredictor /tmp/scan.json
python3 /tmp/census-tool/ledger.py /tmp/census-src TSPPredictor /tmp/scan.json /tmp/ledger
diff /tmp/ledger/reductions.csv docs/audits/2026-11-28/reductions.csv && echo identical
```
