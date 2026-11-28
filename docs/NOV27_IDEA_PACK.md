# Nov 27 idea pack: TSP Predictor

Branch `grok/nov27-tsp-idea-pack`, based on main @ 2798d68. Every item has a test in
`tests/test_nov27_idea_pack.py`. **Built** means real code that runs here with no outside
account. **Stub** means the code and tests are real, but the item needs a package or server
this repo does not ship, so it has only been checked against a stand-in.

## Improvements (10 built)

| # | Item | Where |
|---|---|---|
| 1 | Worst 5% labeled as 5%, not a decile (`worst_5pct_sessions`, `quantile`, label) | `studies.scarcity_upper_bound` |
| 2 | Threshold described as a plain volatility ratio (`VOLATILITY_RATIO = 1.414`) | `connectors/profiling.py` |
| 3 | Flags persist until acknowledged; builds no longer overwrite the baseline | `profiling.profile_snapshot`, `tsp profile acknowledge` |
| 4 | Builds stay reproducible: the baseline sha256 is a recorded build input | `build._build_manifest(..., profile_baseline_sha256)` |
| 5 | Restated history caught by a digest of all rows but the newest | `profiling.history_digest`, `restatement_flags` |
| 6 | L funds profiled | `profiling.l_fund_profile` |
| 7 | Spike windows don't overlap (cooldown = post window, `skipped_overlapping`) | `studies.spike_starts`, `gpr_spike_study` |
| 8 | Missing is not zero: `filled_sessions` counts missing prices and non-finite returns | `studies.gpr_spike_study` |
| 9 | Profile written atomically (temp file + rename) | `profiling` |
| 10 | A whylogs failure is caught and reported; the build continues | `profiling` |

## Functions (10 built)

`profile_history`, `history_digest`, `acknowledge_flags`, `spike_starts`, `filled_sessions`,
`engine_report` (in build meta as `engine`), `scarcity_at`, `f_drawdown_by_window` (in
`harbor`), `l_fund_profile`, `explain_flag`.

## Add-ons (10 built)

Written by `tsppredictor/addons.py` into `dist/addons/*.html` and `dist/data/*.json` on every build.

1. Data Drift Card on the dashboard. Its acknowledge button POSTs to `/api/profile/acknowledge`
   on the loopback server, which requires the `X-TSP-Local: 1` header (403 otherwise).
2. Profile Timeline. 3. GPR Spike Explorer. 4. Rate-Rise Window Atlas.
5. Restatement Alarm: `tsp profile restatement-check` exits non-zero when old prices changed.
6. Polars Fast Path Bench: `tsp lab bench`.
7. Monthly Learning Note PDF: `tsp lab note` (what the rules did, never what to buy).
8. Study Caveat Panel: `tsp lab caveats` and `dist/addons/caveats.html`.
9. Snapshot Age Badge: computed in the browser from `calendar.json`, so `dist/` stays reproducible.
10. Profile Export Bundle: `tsp profile export`.

## Connectors (7 built, 3 stubs)

| # | Connector | Status | Notes |
|---|---|---|---|
| 1 | Modin | **stub** | `frames.is_modin` / `to_pandas` accept a Modin frame. Modin is not installed; tested with a stand-in class only. |
| 2 | PyArrow Parquet cache | built | `connectors/parquet_cache.py` (falls back to pickle without pyarrow). |
| 3 | Vega-Lite | built | `tsp export vega` writes the Profile Timeline and Spike Explorer specs. |
| 4 | Zarr | built (adapter) | `connectors/zarr_store.py`, tested with real zarr. Not wired into `tsp build` yet. |
| 5 | Arrow Flight | built | `tsp lab flight`. Loopback by default; a LAN bind needs `--allow-lan` and a private address. |
| 6 | Jupyter export | built | `tsp export notebook --study ...`. |
| 7 | Apple Numbers CSV | built | `tsp export numbers --start YYYY-MM --end YYYY-MM`. |
| 8 | Prophet | **stub** | Labeled a toy baseline, shown only beside the real out-of-sample record. Prophet is not installed; tested with a fake model. |
| 9 | Redash | **stub** | `tsp export redash` writes a SQLite copy plus saved queries. Redash itself is an outside server. |
| 10 | HDF5 (h5py) | built | `tsp profile hdf5`. |

Optional extras: `pip install -e ".[fast,arrays]"`.
