# TSP Predictor handoff

Educational decision support. Not financial advice. Nothing in this record is a recommendation to move money.

The numbers below were read from `dist/data/scoreboard.json` and `dist/data/today.json` after `python -m pytest` rebuilt `dist/` on 2026-10-06. `dist/` is gitignored. Share prices in the committed snapshot run through 2026-10-05.

## Commands actually run

From `/workspace`, with `/workspace/.venv` (Python 3.12.3):

- `pip install click==8.1.8` — Typer 0.12.5 treated valued options as flags under Click 8.5.0. Click is now pinned at 8.1.8 in `pyproject.toml` and `requirements.lock`. After that, `tsp serve --help` lists `--port`.
- `tsp serve --port 8765` — printed `Serving dist on 127.0.0.1 port 8765` and `curl http://127.0.0.1:8765/index.html` returned HTTP 200.
- `ruff check /workspace` — all checks passed.
- `python -m pytest --tb=line -q` — exit code 0, about 98 seconds. Progress line `....................s.......` is 27 passed and 1 skipped. The skip is `tests/test_site.py::test_28_browser_smoke_optional` (`pytest -rs` confirmed the skip reason: Playwright is not a pinned dependency). Sklearn emitted calibration warnings (rare classes versus `n_splits=5`). Those warnings are not failures. The build inside that test finished in 91.0 seconds, 464 logged trials, `data_as_of` 2026-10-05.
- Browser check against that local server, with the Playwright MCP tools, after the CSS overflow fix was copied into `dist/`. This is separate from pytest. Test 28 stayed skipped.

Not run: `tsp update` (it would change snapshot hashes), and the Tier B/C fetchers were not exercised against the network. The engine path used here is the snapshot only.

## Browser check

On `http://127.0.0.1:8765/index.html`:

- Today shows Shelter in G, calibrated probability 15.5%, the not-advice statement, real logistic drivers, and "VIX file absent".
- The meter reads "0 of 2 unrestricted transfers", not a six-transfer budget. The page text does not contain "guaranteed", "beat the market", "AI knows", "can't lose", or "2/6".
- Scoreboard filters: daily lag 1 shows 27 rows, monthly lag 1 shows 13, daily lag 2 shows 13. Beat count on each of those views was 0. Show table opened the wealth table (2,818 rows).
- Replay moved from 2008-08-01 (G, probability 0.1555) to 2017-08-29 (G, probability 0.1169) with different drivers. Reveal printed the forward C, selected-fund, and G returns.
- Transfer log, civilian account: 2026-10-06 to C accepted and counted; 2026-10-07 to S accepted and counted; 2026-10-08 to F rejected; 2026-10-09 to G accepted and not counted; 2026-10-30 17:00 to C posted on 2026-11-02 and was accepted against November. The meter then read "2 of 2 unrestricted transfers used in 2026-10".
- Journal save, export (`tsp-journal.json`), and import round-trip worked in local storage. Retirement year 2032 displayed L 2030. Tab from Today moved focus to Scoreboard.
- At 375px CSS width the document no longer scrolls sideways. Wide tables scroll inside `main`.

## Headline results

No comparison received a **Beat** verdict. Beat requires excess compound growth above zero, a 90% block-bootstrap interval entirely above zero, and a deflated Sharpe of at least 0.95. With 464 trials, deflated Sharpes on these rows are near zero, so a positive interval is still Inconclusive. Buy-and-hold C versus always-G on the daily window is the clearest case: excess about +9.98 percentage points per year, interval about +2.09 to +15.85, deflated Sharpe about 0.27, verdict Inconclusive.

Full-sample buy-and-hold C, which test 19 checks, is a calendar CAGR of about 11.44% from 2003-05-31 to 2026-10-05. The scoreboard CAGRs below are the out-of-sample window, not that full sample.

Daily, horizon 21 sessions, lag 1, window 2008-08-01 to 2026-10-05 (L 2050 only where it has a price, from 2011-01-31). Excess versus buy-and-hold C:

| Strategy | CAGR | Versus buy-and-hold C |
| --- | --- | --- |
| Buy-and-hold C | 12.65% | Inconclusive +0.00 [0.00, 0.00] |
| Always G | 2.67% | Underperformed -9.98 [-15.85, -2.09] |
| Static 60% C / 40% G | 10.23% | Inconclusive -2.42 [-4.58, 0.18] |
| Monthly rebalanced 60/40 | 8.93% | Underperformed -3.72 [-6.28, -0.38] |
| L 2050 | 10.36% | Underperformed -3.87 [-5.54, -2.03] |
| 10-month SMA | 9.58% | Inconclusive -3.07 [-8.07, 3.03] |
| Dual momentum | 6.80% | Inconclusive -5.85 [-10.96, 0.60] |
| Yield curve plus trend | 9.57% | Inconclusive -3.08 [-8.60, 3.99] |
| Volatility target | 11.04% | Inconclusive -1.61 [-4.20, 1.10] |
| Sell in May | 8.33% | Inconclusive -4.32 [-8.75, 0.74] |
| L2 logistic | 5.86% | Underperformed -6.79 [-12.01, -1.05] |
| Gradient boosting | 7.90% | Inconclusive -4.75 [-10.58, 2.82] |
| Ensemble | 6.21% | Inconclusive -6.44 [-11.94, 1.38] |

The ensemble versus L 2050 on that same daily window is Inconclusive, excess about -4.26 percentage points [-10.22, 1.14]. The point estimate is below both buy-and-hold C and L 2050.

Today, 2026-10-05: the ensemble policy selects G (Shelter in G). Calibrated P(G) is 15.5%. No risky fund cleared the 34% probability bar. Fold probabilities were about G 15.5%, F 8.2%, C 19.5%, S 25.6%, I 31.2%. The logistic scores alone favor S.

Other windows, excess versus buy-and-hold C:

- Daily lag 2, horizon 21: rules and models stay Inconclusive, with negative point estimates (ensemble about -6.96 [-14.01, 0.11]).
- Daily lag 1, horizon 63, from 2009-01-02: the 10-month SMA, dual momentum, curve-plus-trend, volatility target, Sell in May, and the ensemble Underperformed. Logistic is Inconclusive, about -4.71 [-10.86, 1.87].
- Monthly lag 1, from 1993-01-31: the 10-month SMA is Inconclusive +0.45 [-3.21, 4.28] (deflated Sharpe about 0.001). Dual momentum is Inconclusive +0.53 [-2.85, 4.00]. Those are the only positive point estimates versus buy-and-hold C among the rules and models, and they are not Beat. The ensemble Underperformed, about -5.35 [-7.77, -3.09].
- Monthly lag 2: the SMA and dual-momentum point estimates flip negative and stay Inconclusive. Logistic, boosting, the ensemble, and the volatility target Underperformed.
- Buy-and-hold I before 2024-10-30: CAGR about 7.14%, Underperformed versus C, about -3.78 [-7.09, -0.37]. On and after the benchmark change the window is short.

## Data

Tier A snapshot is committed under `data/snapshot/`. Manifest check: present files match `MANIFEST.csv`; Tier B and C paths listed there are absent on purpose. VIX is absent, so `vol_level` is 20-session realized volatility of the C Fund. FRED copies are not read by the trainer.

`docs/cover.jpg` and `docs/ui-art-reference.jpg` follow the attached art direction. The original JPEG bytes were not on disk when those files were written, so they are reconstructions, not the original pixels. The dashboard meter implements two unrestricted transfers and then G-only. The reference sheet's "2/6" figure is not what the app shows.

## Limitations

- No searched strategy beat buy-and-hold C under the stated verdict rule.
- Macro series are the latest vintage, not the first print.
- Daily out-of-sample start is 2008-08-01, a few weeks after a five-year warmup would suggest "about 2008-06". The embargo was not loosened to force that date.
- The I Fund benchmark changes on 2024-10-30. The post-break window is short.
- NBER dates are not features. The NY Fed probability is used only if a cache file exists, and then only shifted back 12 months. That file was not present for this build.
- The browser transfer log rejects any non-G target after two unrestricted transfers. The Python backtest also accepts a partial move that raises G without raising F, C, S, or I.
- Event studies are small samples. Seasonality tables carry a multiple-testing warning.
- Sklearn calibration warns when a fold has a rare class. The build still completes.
- Test 28 does not launch a browser. The browser check above was a manual pass with Playwright MCP, not a pytest pass.
