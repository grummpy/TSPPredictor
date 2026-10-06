# TSP Predictor data snapshot: sources, coverage, licenses

Retrieved: **Tuesday, October 6, 2026**, between about 5:58 and 6:30 AM ET, from the box (`/workspace/tsp-data/`).
No API keys were used, and none are stored in any file.
`MANIFEST.csv` lists every CSV with its row count, first/last key, and a truncated SHA-256.

Licensing tiers used below:
- **A: bundle in the repo.** U.S. government work or an explicit open license.
- **B: personal or local use with attribution.** Copyrighted, but use is allowed with a citation. Fetch it on the user's machine with the update script. Do not commit it to a public repo unless the owner allows that.
- **C: do not bundle.** Pre-approval is required, or redistribution needs a license.

---

## 1. TSP.gov (official, Tier A)

TSP.gov is operated by the Federal Retirement Thrift Investment Board (FRTIB), a federal agency, so its published statistics are U.S. government works. Cite "Source: TSP.gov (FRTIB)". Note: tsp.gov returns **403 Access Denied** unless the request has a full browser-style `User-Agent`. Polite single requests with a normal UA and `Referer: https://www.tsp.gov/share-price-history/` work. These are the same CSV files the public pages load.

| File | Source URL (verified 2026-10-06) | Range | Rows |
|---|---|---|---|
| `tsp_daily_share_prices.csv` (cleaned, ascending, wide) | `https://www.tsp.gov/data/fund-price-history.csv` (loaded by `/share-price-history/` via `/assets/converge/js/tsp_share_price/share-price-history.js`; S3/CloudFront, `last-modified: Tue, 06 Oct 2026 03:07:22 GMT` = Oct 5, 11:07 PM ET) | 2003-05-31 → 2026-10-05 | 5,830 dates |
| `raw/tsp_fund_price_history_raw.csv` | same, untouched (descending, trailing blank row) | same | 5,831 + header |
| `tsp_monthly_returns_pct.csv` (monthly % returns, funds **and benchmark indexes**) | `https://www.tsp.gov/data/getMonthlyReturnsSummary.csv?Lfunds=1&InvFunds=1&IndexFunds=1&Lifetime=1&Inception=1&Trailing=1` (loaded by `/rates-return/`) | 1987-04 → 2026-09 | 474 months |
| `tsp_annual_returns_pct.csv` | same file, `type=y` rows (2026 row is YTD through Sep, `is_partial_year=True`) | 1987 → 2026 | 40 |
| `raw/tsp_returns_summary_rows.csv` | same file: lifetime, 1/3/5/10-yr trailing and inception-date rows as of Sep 30, 2026 | n/a | 7 |
| `tsp_retired_lfunds_monthly_returns_pct.csv` | `https://www.tsp.gov/data/getRetiredRatesOfReturn.csv` (loaded by `/l-funds-retired/`) | L 2010 2005-08→2010-12; L 2020 2005-08→2020-06; L 2025 2020-07→2025-05 | 238 months |

Daily coverage per column (non-empty rows):

| Fund | First date | Last date | Rows |
|---|---|---|---|
| G, F, C, S, I | 2003-05-31 (base 10.0000 on a Saturday; first trading day 2003-06-02) | 2026-10-05 | 5,830 |
| L Income, L 2030, L 2040 | 2005-07-29 | 2026-10-05 | 5,288 |
| L 2050 | 2011-01-31 | 2026-10-05 | 3,913 |
| L 2035, L 2045, L 2055, L 2060, L 2065 | 2020-07-01 | 2026-10-05 | 1,560 |
| L 2070 | 2024-07-26 | 2026-10-05 | 546 |
| L 2075 | 2025-06-30 | 2026-10-05 | 317 |

Monthly coverage: G from 1987-04; F, C, and the Bloomberg U.S. Aggregate and S&P 500 benchmark columns from 1988-01; S, I, and the "DJ TSM" and "EAFE" benchmark columns from 2001-05. L funds start 2005-08 (or later for newer funds).

Integrity check: month-end returns computed from the daily file match TSP's published monthly returns for G/F/C/S/I for every month from 2003-07 through 2026-09 (279 months, max absolute difference 0.00 pp). L 2050 is within 0.01 pp.

Important data facts for the engine:
- **The daily share-price history starts June 2003.** TSP moved to daily valuation then and the prices were rebased to $10. Before that, use TSP's official **monthly** returns (back to 1987/1988) or index proxies.
- **The TSP business-day calendar is not the NYSE calendar.** No TSP prices are posted on Columbus Day or Veterans Day (for example 2023-10-09, 2024-10-14, 2024-11-11, 2025-11-11) even though NYSE is open. NYSE-only closures are missing too (for example 2012-10-29/30 Sandy, 2018-12-05, 2025-01-09). **Use the dates present in the TSP file as the authoritative trading calendar.**
- **There is no daily file for L 2025 or L 2020** (both retired into L Income). Only monthly returns exist (retired file).
- **I Fund daily prices use fair-value pricing**, and there is a stale-close issue: international markets close hours before 4 PM ET. Expect large I Fund days that reverse or lag (for example +12.9% on 2008-10-14). A naive daily backtest can "discover" stale-price momentum that fair value pricing exists to prevent. See `rules/tsp_share-price-calculation_2026-10-06.txt`.
- **Benchmarks changed.** The I Fund tracked MSCI EAFE until 2024. The transition to the **MSCI ACWI IMI ex USA ex China ex Hong Kong** index was announced complete **Oct 30, 2024** (https://www.tsp.gov/news/plan-news/2024-10-30-I-Fund-benchmark-index-change-complete/; background at https://www.tsp.gov/news/plan-news/2024-02-05-I-Fund-benchmark-index-change-in-2024/). In the monthly file the I Fund benchmark column is still labeled "EAFE", but the page's JS labels it "International Index". Treat it as the then-current benchmark, not as pure EAFE after 2024. S Fund: Dow Jones U.S. Completion Total Stock Market Index (`/s-fund/`). F Fund: Bloomberg U.S. Aggregate Bond Index (`/f-fund/`). C Fund: S&P 500 (`/c-fund/`). G Fund: per `/g-fund/`, the rate is "calculated by the U.S. Treasury as the weighted average yield of ... U.S. Treasury securities on the last day of the previous month" (the statutory formula is in 5 U.S.C. § 8438(e)(2); not re-verified here). G Fund principal is guaranteed and its price never falls.
- **Index-name caveat:** C, S, F, and I benchmark index levels are proprietary (S&P DJI, Bloomberg, MSCI) and are **not** included. The TSP-published monthly benchmark *returns* in the TSP file are the only benchmark data bundled.

## 2. Longer-history proxies (pre-2003 daily / pre-1988 monthly)

| File | Source | Range / rows | Tier and license notes |
|---|---|---|---|
| `macro/ff3_factors_daily.csv` (Mkt-RF, SMB, HML, RF, plus `mkt_total_pct` = Mkt-RF + RF) | Kenneth R. French Data Library, `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip` (built from CRSP 202608) | 1926-07-01 → 2026-08-31, 26,317 | **B.** The file says "Copyright 2026 Eugene F. Fama and Kenneth R. French". Free download; no explicit redistribution license. A total-U.S.-market proxy for the C/S blend (not the S&P 500 itself). |
| `macro/ff3_factors_monthly.csv` | `.../F-F_Research_Data_Factors_CSV.zip` | 1926-07 → 2026-08, 1,202 | **B** (same as above) |
| `macro/shiller_ie_data_monthly.csv` (S&P Composite price, dividend, earnings, CPI, GS10, real TR price, CAPE) | Robert Shiller, `https://shillerdata.com/` → `ie_data.xls` (the old econ.yale.edu URL timed out) | 1871-01 → 2026-09, 1,869 | **B.** No license stated; it carries Shiller's disclaimer and is derived from S&P data. Prices are monthly averages of daily closes. Use for valuation (CAPE) and long-run regime context only. |
| TSP monthly benchmark columns (above) | TSP.gov | S&P 500 / US Agg from 1988 | **A** |

Not obtained (proprietary or no free redistributable source): daily S&P 500 total return before 2003; DJ U.S. Completion, MSCI EAFE/ACWI-ex-US, and Bloomberg Aggregate index levels. FRED's `SP500` series covers only the last 10 years and is "Copyrighted: Pre-Approval Required" (**C**), so it was downloaded and then **deleted**. The same applies to ICE BofA `BAMLH0A0HYM2` (3 years only, **C**).

## 3. Macro and market-stress series

### 3a. Primary-source copies (preferred for modeling; see the FRED ML restriction below)

| File | Source | Range / rows | Tier |
|---|---|---|---|
| `macro/primary/fed_h15_treasury_cmt_and_effr_daily.csv` (3m, 2y, 10y CMT yields, EFFR, 10y–2y and 10y–3m spreads) | Federal Reserve Board H.15 Data Download Program, full release zip `https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&filetype=zip` (series RIFLGFCM03_N.B, RIFLGFCY02_N.B, RIFLGFCY10_N.B, RIFSPFF_N.B) | 1954-07-01 → 2026-10-02 (10y from 1962, 2y from 1976, 3m from 1981), 18,852 | **A** (Federal Reserve Board publication). **The DDP is being retired:** the file header says "Build Your Package" goes away the week of Nov 9 (2026). The fallback for yields is Treasury's daily par yield curve CSV, `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{YEAR}/all?type=daily_treasury_yield_curve&field_tdr_date_value={YEAR}&page&_format=csv` (verified for 2026; data from 1990). |
| `macro/primary/bls_cpi_unemployment_monthly.csv` (CPI-U SA `CUSR0000SA0`, unemployment rate SA `LNS14000000`) | BLS Public Data API v1 (no key), `https://api.bls.gov/publicAPI/v1/timeseries/data/` (POST, 10-year windows) | 1977-01 → 2026-09 (CPI through 2026-08), 597 | **A** (BLS, public domain). **2025-10 is missing in both series** (federal shutdown; BLS did not publish). `download.bls.gov` flat files returned 403 to scripted requests. |
| `macro/primary/vix_history_cboe.csv` (VIX OHLC) | Cboe, `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` (redirects to cdn-api.cboe.com) | 1990-01-02 → 2026-10-05, 9,287 | **C for redistribution.** The free public download states no terms, and Cboe's data policies require a license to redistribute historical data. Fetch it locally for personal use; **do not commit it to a public repo.** |

### 3b. FRED copies (`macro/fred_*.csv`, endpoint `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES`, no key)

The full list, with title, license label, range, rows, and missing count, is in `macro/macro_manifest.csv`. Summary:

| Series | What | Range | FRED license label |
|---|---|---|---|
| VIXCLS | VIX close | 1990-01-02 → 2026-10-02 | Copyrighted: Citation Required (Cboe) |
| DGS10, DGS2, DGS3MO, DTB3 | Treasury yields | 1954/1962/1976/1981 → 2026-10-02 | Public Domain: Citation Requested |
| T10Y2Y, T10Y3M | Yield-curve spreads | 1976/1982 → 2026-10-05 | Copyrighted: Citation Required (compute from DGS* instead) |
| UNRATE, CPIAUCSL, CPILFESL, PAYEMS, ICSA, INDPRO | Labor / prices / activity | 1919–1967 → 2026-08/09 | Public Domain: Citation Requested |
| FEDFUNDS, DFF | Fed funds | 1954 → 2026 | Public Domain: Citation Requested |
| USREC, USRECD | NBER recession flags | 1854 → 2026 | Copyrighted: Citation Required (derive from NBER dates instead) |
| NFCI, STLFSI4, BAA10Y, T10YIE | Financial conditions / credit / breakevens | 1971–2003 → 2026 | Copyrighted: Citation Required |
| DCOILWTICO, DTWEXBGS, USEPUINDXD | Oil, dollar, policy uncertainty | 1985/1986/2006 → 2026 | Public Domain: Citation Requested |

**FRED terms of use (https://fred.stlouisfed.org/legal/, read 2026-10-06), which matter for this app:**
- "Copyrighted: Citation required" series may be used with attribution ("Source: X via FRED").
- The terms of use prohibit using "the FRED® Services or FRED® Content in connection with the development or training of any software program or system or machine learning, including ... deep learning, generative artificial intelligence...". They also prohibit disruptive scraping and redistributing FRED content in another database without permission.
- **Recommendation:** use the FRED snapshot only for exploration and charts. The engine's trained models should ingest the same public-domain data from the **primary publishers** (Fed H.15 or Treasury, BLS, NBER) and compute spreads and recession flags itself. VIX comes from Cboe locally, for personal use. Treat this as a conservative reading, not legal advice.

### 3c. Other free sources

| File | Source | Range / rows | Tier |
|---|---|---|---|
| `macro/nber_business_cycle_dates.csv` (peak, trough) | NBER, `https://data.nber.org/data/cycles/business_cycle_dates.json` (redirects to `/cycles//business_cycle_dates.json`) | troughs 1854 → peak 2020-02 / trough 2020-04, 35 cycles | **A-ish** (dates are facts; cite NBER, https://www.nber.org/research/business-cycle-dating). **Recession flags must respect announcement lag:** NBER announces peaks and troughs months to more than a year after the fact, so never use them as a real-time feature. Use them only for labeling and evaluation. |
| `macro/nyfed_yield_curve_recession_probability.csv` | Federal Reserve Bank of New York, `https://www.newyorkfed.org/medialibrary/media/research/capital_markets/allmonth.xls` | 1959-01 → 2027-08 (forward-dated), 824 | **B** (cite the NY Fed). **Look-ahead trap:** `rec_prob_12m_ahead` for month *t+12* is computed from the spread at month *t*. Align it back by 12 months before use. |
| `macro/gpr_daily_caldara_iacoviello.csv` (GPRD, acts/threats, MA7/MA30, event labels) | Caldara & Iacoviello Geopolitical Risk Index, `https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls` | 1985-01-01 → 2026-10-05, 15,253 | **A: Creative Commons BY** ("permission to use, distribute, and reproduce these in any medium, provided the source and authors are credited", https://www.matteoiacoviello.com/gpr.htm). Cite Caldara, D. and M. Iacoviello (2022), "Measuring Geopolitical Risk," *American Economic Review*. **This is the "war trends" signal.** |
| `macro/gpr_monthly_caldara_iacoviello.csv` (GPR, GPRT, GPRA, historical GPRH from 1900) | `.../data_gpr_export.xls` | 1900-01 → 2026-09 (GPR from 1985), 1,521 | **A (CC BY)** |
| `macro/fred_USEPUINDXD.csv` | Baker-Bloom-Davis Economic Policy Uncertainty (via FRED; original at policyuncertainty.com) | 1985 → 2026-10-04 | Public Domain: Citation Requested (via FRED, so the FRED ML clause applies; fetch from policyuncertainty.com for models) |

Raw originals (xls/zip/json) are kept in `macro/raw/`.

## 4. Event dataset

`events.csv` has 56 hand-curated events from 1987-10-19 to 2026-07-07: 13 war, 10 financial crisis, 6 rate shock, 5 fiscal/credit, 4 NBER recession, 3 terrorism, 3 policy response, 3 market structure, 2 market crash, 2 trade policy, 2 pandemic, 1 natural disaster, 1 geopolitical, and 1 TSP structural. Each row has one source URL. On 2026-10-06 every URL returned HTTP 200 to a plain or browser user agent, except britannica.com, which blocks curl but was read through a fetch tool. `first_reaction_tsp_date` is the first TSP price date on or after the event, adjusted to the next session for after-close and weekend events. It is blank before June 2003. Descriptions are kept factual. Return statistics are deliberately *not* stored; the engine computes them.

## 5. Rules evidence (`rules/`)

- `tsp_how-to-change-your-tsp-investments_2026-10-06.txt`: https://www.tsp.gov/how-to-change-your-tsp-investments/
- `ecfr_5cfr1601.32_2026-10-06.txt`: https://www.ecfr.gov/current/title-5/section-1601.32
- `tspbk08_summary_of_the_tsp_1-2026_excerpt.txt`: https://www.tsp.gov/publications/tspbk08.pdf (TSPBK08, 1/2026)
- `tsp_share-price-calculation_2026-10-06.txt`: https://www.tsp.gov/share-price-calculation/

## 6. Failures and gaps

- FRED rejected requests with a browser user agent (HTTP/2 INTERNAL_ERROR, then timeouts). The default curl UA worked.
- `http://www.econ.yale.edu/~shiller/data/ie_data.xls` timed out. shillerdata.com worked.
- `download.bls.gov` flat files returned 403 (BLS requires a contact-identifying UA). API v1 worked.
- Cboe VIX history, S&P 500 levels, ICE BofA spreads, MSCI/Bloomberg/DJ index levels: obtained but not redistributable, or not obtained.
- I did not verify the exact statutory G Fund formula text or NY Fed and Cboe redistribution terms in full.
