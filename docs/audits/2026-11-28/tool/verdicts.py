"""Verdict rules + manual overrides for the ten censuses (Nov 28 2026 run).

verdict buckets: ok (already correct), fixed, accepted (known limit kept, with reason), NOT_APPLICABLE (with reason).
`detail` carries the census-specific label (single-decode, collision-safe, owner=.., zone=.., atomic, bounded, ...).
"""
import re

SHORT = {"master-chief-hologram": "MC", "commander-nova": "NOVA", "Decker-Family-HUD": "HUD", "TSPPredictor": "TSP"}

# ---------------------------------------------------------------- manual overrides
# key: (repo, census, file, line) -> (verdict, detail, reason). A key may also end with "*" file glob handled below.
OV = {}


def ov(repo, census, file, lines, verdict, detail, reason):
    for ln in (lines if isinstance(lines, (list, tuple)) else [lines]):
        OV[(repo, census, file, ln)] = (verdict, detail, reason)


# 12.1 Double-Decode
ov("NOVA", "12.1", "app/shared/media-path.mjs", 12, "fixed", "double-decode -> single-decode",
   "dispatch.mjs already decodes url.pathname once; this second decodeURIComponent turned a literal '%25' into '%' and threw on a bare '%', so files with % in the name 404'd. Removed; resolveMediaPath now takes the already-decoded path.")
ov("NOVA", "12.1", "app/shared/dispatch.mjs", 66, "ok", "single-decode",
   "The one boundary decode of the percent-encoded url.pathname; malformed escapes return 404.")

# 12.3 Timestamp Filename
NA_TS = "timestamp is a record field or display value, not part of an output filename"
for f, l in [("diagnostics-store.js", 8), ("main.js", 424), ("main.js", 1979), ("main.js", 2370), ("main.js", 2513), ("main.js", 2894),
             ("project-store.js", 28), ("renderer.js", 101), ("renderer.js", 376), ("retrieval-provenance.js", 3), ("workspace-experience.js", 12),
             ("scripts/media-auto-art-eval.js", 43), ("scripts/media-auto-art-eval.js", 52), ("scripts/run-agent-20-local-smoke.js", 168),
             ("training-data.js", 65), ("conversation-store.js", 29)]:
    ov("MC", "12.3", f, l, "NOT_APPLICABLE", "not a filename", NA_TS)
ov("NOVA", "12.3", "addons/caption-burner/index.mjs", 9, "NOT_APPLICABLE", "not a filename", "SRT cue timestamps inside the file body")
for f, l in [("app/backend/app/services/recovery_addons_service.py", 84), ("scripts/update-and-restart.sh", 16),
             ("scripts/update_build_manifest.py", 2), ("scripts/update_build_manifest.py", 41)]:
    ov("HUD", "12.3", f, l, "NOT_APPLICABLE", "not a filename", NA_TS)
ov("MC", "12.3", "document-generator.js", [114, 125], "fixed", "collision-safe (counter + exclusive create)",
   "Name had one-second resolution plus the title, so two Word/PDF exports with the same title in the same second silently replaced the first. Now opens with 'wx' and adds -2, -3... on EEXIST.")
ov("MC", "12.3", "commander-nova.js", 59, "accepted", "ms + pose + seed",
   "Collision needs the same pose and seed in the same millisecond from one sequential loop; copyFileSync would overwrite, but that cannot happen in practice.")
ov("MC", "12.3", "deepteam-bridge.js", 159, "accepted", "ms ISO stamp directory", "One red-team run at a time (UI-triggered); millisecond directory stamp.")
ov("MC", "12.3", "nova-lora-bench.js", 376, "accepted", "ms + seed", "Sequential bench loop; name also carries family, tag and seed.")
ov("MC", "12.3", "productivity-artifacts.js", [43, 55, 59], "accepted", "ms + title",
   "Millisecond stamp plus title; artifacts are generated one at a time per request. Lower risk than document-generator's one-second stamp.")
ov("MC", "12.3", "project-store.js", 48, "accepted", "exists-check + ms fallback", "Only used when the plain name already exists; ms suffix on the fallback.")
ov("MC", "12.3", "main.js", [2464, 2484], "NOT_APPLICABLE", "save-dialog default", "Default name in the OS save dialog; the dialog itself asks before replacing a file.")
ov("MC", "12.3", "scripts/run-p2-assessment.js", 3, "accepted", "ms ISO stamp", "Manual dev script, run one at a time.")
for f, l in [("scripts/live-detail-controls-readiness.js", 15), ("scripts/live-faceid-readiness.js", 17), ("scripts/live-identity-benchmark.js", 24),
             ("scripts/live-openpose-readiness.js", 20), ("scripts/live-pose-extractor-readiness.js", 18), ("scripts/live-remacri-readiness.js", 14),
             ("scripts/live-structure-controls-readiness.js", 15)]:
    ov("MC", "12.3", f, l, "accepted", "ms upload name (overwrite=true)",
       "ComfyUI upload sends overwrite=true, so a same-millisecond collision would replace the input; these are manual readiness scripts run one at a time.")
ov("MC", "12.3", "scripts/install-downloaded-sdxl-assets.ps1", 96, "accepted", "seconds stamp", "Manual one-off installer manifest.")
ov("MC", "12.3", "scripts/install-sdxl-model.ps1", 10, "accepted", "seconds stamp", "Manual one-off installer backup of an invalid model file.")
ov("HUD", "12.3", "app/backend/app/services/backup_service.py", 362, "accepted", "seconds stamp + label (risk)",
   "Two backups with the same label in the same second would reuse the file, and a failed second backup unlinks it. Not fixed here because backup_service.py is under open PR #8; fix after #8 merges (open with 'x' or add a counter).")
ov("TSP", "12.3", "tsppredictor/journal.py", [248, 249, 252], "ok", "collision-safe (counter loop)", "Backup name gets .N suffix until unused.")

# 12.4 Lock Owner
ov("MC", "12.4", "agent-task-ledger.js", 18, "NOT_APPLICABLE", "temp file, not a lock", "O_EXCL creates a unique pid+uuid temp file for an atomic write; it is not a lock.")
ov("MC", "12.4", "workflow-schedule-store.js", 39, "NOT_APPLICABLE", "temp file, not a lock", "O_EXCL creates a unique temp file for an atomic write; it is not a lock.")
ov("MC", "12.4", "agent-task-ledger.js", 73, "accepted", "owner=no timestamp=no recovery=manual",
   "mkdir lock for adapter dispatch. A crash leaves it until removed by hand; that is deliberate (the error says to reconcile before replaying an ambiguous dispatch). Recommend recording pid/time in the lock for the message.")
ov("MC", "12.4", "scripts/launch-mac.sh", 24, "accepted", "owner=no timestamp=no recovery=reboot",
   "Lock is in /tmp, so a crash-left lock clears on reboot; a second click just opens the running app. Trap is set after the lock is taken (correct).")
ov("HUD", "12.4", "scripts/update-and-restart.sh", 29, "fixed", "owner=pid timestamp=yes recovery=stale-pid",
   "trap cleanup EXIT was set before mkdir, so a second update that found the lock busy deleted the first update's lock on exit. Traps now arm only after the lock is taken; the lock stores pid + UTC time and a lock whose pid is dead is reclaimed.")
ov("HUD", "12.4", "app/backend/app/services/asset_register_service.py", 198, "NOT_APPLICABLE", "in-process lock",
   "threading.Lock in one server process, not a mkdir/file lock.")

# 12.9 Unbounded Memory
def b(repo, f, l, verdict, detail, reason):
    ov(repo, "12.9", f, l, verdict, detail, reason)
LOCAL = "function-local working list; freed when the call returns"
b("MC", "long-report.js", 131, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "main.js", 603, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "media-body-builder.js", [609, 610], "NOT_APPLICABLE", "local", LOCAL)
b("MC", "nova-lora-bench.js", 292, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "renderer.js", 746, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "voice-installation.js", 23, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "workflow-registry.js", 29, "NOT_APPLICABLE", "local", LOCAL)
b("MC", "scripts/run-canonical-scorecard-parity.py", 18, "NOT_APPLICABLE", "script", "one-shot script results list; process exits")
b("MC", "renderer.js", [117, 543], "NOT_APPLICABLE", "replaced whole", "reassigned wholesale from a fresh server response")
b("MC", "three-scene.js", 9, "NOT_APPLICABLE", "fixed table", "fixed texture table built once")
for f, l in [("main.js", 37), ("main.js", 175), ("main.js", 198), ("main.js", 200), ("main.js", 205), ("main.js", 358), ("main.js", 363), ("main.js", 1996),
             ("agent-execution-control.js", 11), ("agent-execution-control.js", 12), ("agent-media-approval.js", 29), ("agent-preview-guidance.js", 10),
             ("media-prompt-provenance.js", 101), ("src/providers/session-consent.js", 7)]:
    b("MC", f, l, "ok", "bounded by live work", "entries are deleted when the job/session/consent finishes; size tracks concurrent work, not history")
b("MC", "main.js", 359, "ok", "bounded by live work", "standby queue drains as jobs start")
b("MC", "credential-store.js", 4, "ok", "bounded by key set", "keyed by a fixed set of provider credential names")
b("MC", "nova-lora-bench.js", 187, "accepted", "per-host catalog", "one entry per ComfyUI host per bench process; worst case = number of hosts")
b("MC", "src/functions/b3.js", [10, 11], "accepted", "per-provider budget", "one entry per provider name; worst case = providers configured")
b("MC", "renderer.js", 97, "ok", "user-capped", "attachments are removed on send/remove and each is capped at 25 MB")
b("MC", "renderer.js", 114, "ok", "user-managed", "LoRA stack edited by the user; reset per render")
b("NOVA", "app/shared/tts-cache.mjs", 19, "accepted", "unbounded TTS cache (risk; fix is in open PR #10)",
  "Process-lifetime cache of MP3 buffers keyed by every distinct line spoken; on main it grows by one clip per new line forever. Open PR #10 (Nov 27 idea pack) already adds a 32 MB least-recently-used byte budget to this file, so this branch leaves it alone to avoid a conflict; merging PR #10 closes it.")
b("NOVA", "app/shared/metrics.mjs", 2, "fixed", "per-route counters",
  "Stored one row per API request for the life of the server (worst case = total requests). Now keeps per-route counters; snapshot() output is unchanged.")
b("NOVA", "app/shared/chat-tools.mjs", 62, "accepted", "<=500 chars x notes",
  "Session notes, each capped at 500 chars, kept until reset; worst case = notes added by hand. chat-tools.mjs is under open PR #8, so no change here.")
b("NOVA", "app/shared/inflight.mjs", 2, "ok", "bounded by live work", "entries deleted on finish/cancel")
b("NOVA", "addons/hash-ledger/index.mjs", 4, "accepted", "per-asset hash", "one entry per distinct asset in a ledger run; worst case = assets scanned")
b("NOVA", "addons/latency-watch/index.mjs", 2, "accepted", "addon session samples", "addon-local sample list, created per watch session; worst case = samples recorded in that session")
b("NOVA", "app/shared/fallback-chain.mjs", 3, "NOT_APPLICABLE", "local", LOCAL)
b("NOVA", "app/shared/manifest-cache.mjs", 4, "ok", "watch handles", "one handle per watched folder (2)")
b("NOVA", "app/shared/zip-store.mjs", [12, 13, 14], "NOT_APPLICABLE", "local", LOCAL)
b("NOVA", "launchers/launcher-core.mjs", 12, "NOT_APPLICABLE", "local", LOCAL)
b("HUD", "app/backend/app/services/connector_service.py", 31, "ok", "bounded by live flows", "device-flow entries are popped on completion/expiry")
b("TSP", "tsppredictor/calendar.py", 65, "accepted", "one set per year", "keyed by calendar year (about 11 holidays each); worst case = distinct years queried, a few dozen")

# 12.10 Label Truth
def lt(repo, f, l, verdict, detail, reason):
    ov(repo, "12.10", f, l, verdict, detail, reason)
lt("TSP", "tsppredictor/studies.py", [435, 439, 442], "fixed", "renamed: worst_decile -> worst 5%",
   "Code selects sessions at or below the 0.05 quantile (worst 5%), but the key and note said worst decile. Key renamed to worst_5pct_sessions, note corrected, quantile recorded in the output; no in-repo reader used the old key.")
lt("TSP", "tsppredictor/connectors/profiling.py", [43, 44, 46, 47], "fixed", "renamed: z-fold -> z**(1/4)-fold",
   "Docstring said a return std moving by more than z-fold (4x) is flagged; code flags |log ratio| > log(z)/4, i.e. about 1.41x for z=4. Label corrected to match the code; test pins 1.5x flagged and 1.3x not.")
lt("TSP", "tsppredictor/connectors/profiling.py", 30, "ok", "confirmed", "ret_std is the sample std (ddof=1) of daily returns")
lt("TSP", "tsppredictor/studies.py", [328, 329, 330, 335, 336, 339, 340, 321, 322], "ok", "confirmed",
   "median, mean and worst_10pct match np.median, np.mean and the 0.10 quantile")
lt("TSP", "tsppredictor/backtest/honesty.py", [32, 44], "ok", "confirmed", "ci90 is the 5th-95th percentile bootstrap interval of excess CAGR")
lt("TSP", "tsppredictor/build.py", 245, "ok", "confirmed", "text says 90% block-bootstrap interval; values come from honesty.ci90")
lt("TSP", "tsppredictor/backtest/metrics.py", 193, "ok", "confirmed", "hit_rate_vs_g = share of periods beating G")
lt("TSP", "tsppredictor/build.py", 640, "ok", "confirmed", "hit_rate = hits / comparable")
lt("TSP", "tsppredictor/journal_insights.py", [70, 103], "ok", "confirmed", "hit_rate = hits / members, shown as percent")
lt("TSP", "tsppredictor/build.py", 832, "ok", "confirmed", "in-fold mean excess shown in percentage points (x100)")
lt("TSP", "tsppredictor/evidence.py", 217, "ok", "confirmed", "per-step CAGR change shown in percentage points (x100)")
lt("TSP", "tsppredictor/features/pipeline.py", [57, 117, 118, 242], "ok", "confirmed", "rolling mean/std windows match the feature names")
lt("TSP", "tsppredictor/features/spec.py", [81, 201, 203], "ok", "confirmed", "spec text matches the expanding-percentile computation")
lt("TSP", "tsppredictor/models/ml.py", [256, 276, 278], "ok", "confirmed", "median/mean snapshot fields match np.median/np.mean")
lt("TSP", "tsppredictor/studies.py", [59, 93, 108], "ok", "confirmed", "median uses np.nanmedian; mean uses .mean()")
lt("TSP", "tsppredictor/data/snapshot.py", [232, 234], "ok", "confirmed", "gap reported in percentage points against a 0.01 pp limit")
lt("TSP", "tsppredictor/models/regimes.py", [12, 14, 22, 23, 25, 27, 37, 38], "ok", "confirmed", "states ordered by mean volatility; 0.70 percentile split labeled High/Low vol")
lt("TSP", "tsppredictor/vintage_replay.py", 41, "ok", "confirmed", "revised vs first-print CAGR fields match their sources")
lt("TSP", "tsppredictor/report/static/app.js", [795, 796], "ok", "confirmed", "biggest drift = max of max_drift, shown in points (x100)")
lt("TSP", "tsppredictor/journal_insights.py", 198, "ok", "confirmed", "worst = largest max_drift")
lt("TSP", "tsppredictor/backtest/metrics.py", [30, 103], "ok", "confirmed", "drawdown definition and mean weights match the code")
lt("TSP", "tsppredictor/models/ensemble.py", 82, "ok", "confirmed", "averages finite rows only, as documented")
lt("TSP", "tsppredictor/models/rules.py", [25, 39, 44], "ok", "confirmed", "rule docstrings match the moving-average and vol-target code")
lt("MC", "ollama-evaluator.js", [40, 41], "ok", "confirmed (nearest-rank)", "medianMs/p95 use nearest-rank on sorted latencies; for an even count the median is the lower middle value")
lt("MC", "src/media/comfy-gates.js", [38, 40], "ok", "confirmed", "meanMs is the arithmetic mean of durations")
lt("NOVA", "app/shared/metrics.mjs", 24, "ok", "confirmed", "avgMs = totalMs / count")
lt("HUD", "app/backend/app/services/assets_service.py", 226, "ok", "confirmed", "avg_monthly = total / months")
lt("HUD", "app/backend/app/services/retirement_service.py", 191, "ok", "confirmed", "High-3 proxy = mean of the last 3 years' pay, as labeled")
lt("HUD", "app/backend/app/services/retirement_service.py", 572, "ok", "confirmed", "annual FERS = High-3 x years x multiplier")
lt("HUD", "scripts/verify-served-frontend.js", [20, 21], "ok", "confirmed", "guard that APR percentages are not multiplied by 100 again")

# 12.2 Error Regex classifier kinds (site -> kinds the regex is meant to catch). Missing => NOT_APPLICABLE.
KINDS = {
    ("MC", "agent-runner.js", 33): {"ambiguous"}, ("MC", "agent-runner.js", 36): {"network", "timeout"},
    ("MC", "agent-runner.js", 37): {"model"}, ("MC", "agent-runner.js", 38): {"stale"}, ("MC", "agent-runner.js", 39): {"auth"},
    ("MC", "comfyui-client.js", 171): {"network", "timeout"}, ("MC", "comfyui-client.js", 304): {"network", "timeout"},
    ("MC", "evaluation/agent-capability-20/acceptance.js", 183): {"network", "timeout"},
    ("MC", "evaluation/agent-capability-20/acceptance.js", 206): {"auth"}, ("MC", "evaluation/agent-capability-20/acceptance.js", 209): {"auth"},
    ("MC", "job-contract.js", 50): {"config"}, ("MC", "job-contract.js", 51): {"network"}, ("MC", "job-contract.js", 52): {"model"},
    ("MC", "job-contract.js", 53): {"log"}, ("MC", "job-contract.js", 54): {"cancel"},
    ("MC", "main.js", 787): {"phrase"}, ("MC", "main.js", 809): {"phrase"}, ("MC", "main.js", 1055): {"network", "timeout"},
    ("MC", "main.js", 1181): {"cancel"}, ("MC", "main.js", 1907): {"auth", "network", "timeout"}, ("MC", "main.js", 2127): {"cancel", "auth"},
    ("MC", "provider-contract.js", 12): None,  # per-pattern below
    ("MC", "renderer.js", 49): {"cancel"}, ("MC", "renderer.js", 611): {"phrase"}, ("MC", "src/release/quality-gate.js", 16): {"phrase"},
    ("MC", "agent-task-ledger.js", 109): {"phrase"}, ("MC", "src/functions/b3.js", 53): {"anyfailure"},
}
PROVIDER_KINDS = {"abort|cancel": {"cancel"}, "timeout|network|fetch|ECONN": {"network", "timeout"},
                  "credential|key|auth": {"auth"}, "limit|rate|quota": {"rate_limit"}}
REGEX_FIXED = {("MC", "provider-contract.js", 12, "credential|key|auth"), ("MC", "provider-contract.js", 12, "limit|rate|quota"),
               ("MC", "job-contract.js", 53, "log")}
REGEX_NA_REASON = {
    "artifact-intent.js": "classifies the user's request intent (pdf/docx/xlsx/pptx), not errors",
    "comfyui-client.js:138": "matches legacy SD1.5 model filenames, not errors",
    "context-engine.js": "tags memory/context lines (blocked, todo, decision), not runtime errors",
    "media-auto-lora.js": "LoRA filename match, not errors",
    "renderer.js:476": "scanner read a division sign inside minified code as a regex; no error regex here",
    "renderer.js:569": "scanner read a division sign inside minified code as a regex; no error regex here",
    "renderer.js:672": "scanner read a division sign inside minified code as a regex; no error regex here",
    "scripts/run-agent-20-local-smoke.js": "checks a model's reply text in a smoke test, not error kinds",
    "security.js": "flags dangerous command verbs for approval, not errors",
    "connectors/": "checks for the placeholder host example.invalid, not errors",
    "release_calendar.py": "parses an ICS STATUS line, not errors",
}

lt("MC", "generative-benchmark.js", 65, "ok", "confirmed (nearest-rank)", "median/p95 use nearest-rank percentile on sorted values")
lt("TSP", "tsppredictor/studies.py", [270, 276, 283, 284], "ok", "confirmed", "best/worst 50 come from the sorted C Fund returns, as the note says")
lt("TSP", "tsppredictor/build.py", [235, 803], "ok", "confirmed", "point_estimate_below is excess_cagr < 0")

# 12.6 Naive Time
def nt(repo, f, l, verdict, detail, reason):
    ov(repo, "12.6", f, l, verdict, detail, reason)
nt("HUD", "app/backend/app/services/life_service.py", 25, "fixed", "host zone -> settings zone (America/New_York)",
   "_today() used the host clock's zone while the same service builds day windows in settings.timezone; a host or container on UTC would roll the HUD's 'today' over at 7 PM ET. Now uses settings.timezone.")
nt("HUD", "app/backend/app/services/life_service.py", 33, "ok", "assumes UTC = stored zone",
   "_aware() tags naive SQLite values as UTC; writers store UTC (connector_service and life_service convert with astimezone(timezone.utc)).")
nt("HUD", "app/backend/app/services/life_service.py", [104, 105, 106, 157, 185, 207, 224], "ok", "explicit settings zone",
   "Local day/time built in settings.timezone (default America/New_York), then converted to UTC")
nt("HUD", "app/backend/app/services/life_service.py", [137, 236], "ok", "UTC sentinel", "datetime.min tagged UTC only as a sort key")
nt("HUD", "app/backend/app/api/agenda.py", 24, "ok", "explicit settings zone", "today in settings.timezone")
nt("HUD", "app/backend/app/services/scheduler.py", [28, 30], "ok", "explicit America/New_York", "scheduler zone from settings, default America/New_York")
nt("HUD", "app/backend/app/services/connector_service.py", [101, 104, 117], "ok", "explicit settings zone",
   "floating calendar times get settings.timezone (default America/New_York), then UTC")
nt("HUD", "app/backend/app/services/automation_service.py", [361, 385, 758], "ok", "assumes UTC = stored zone", "naive DB timestamps are stored UTC")
nt("HUD", "app/backend/app/services/backup_service.py", 105, "ok", "UTC by name", "backup stamp is written with a trailing Z (UTC)")
nt("HUD", "app/backend/app/services/recovery_addons_service.py", 60, "ok", "aware ISO", "value written with datetime.now(timezone.utc).isoformat(), so it carries +00:00")
nt("HUD", "app/backend/app/services/weather_service.py", 29, "ok", "aware ISO", "fetched_at is written as an aware UTC ISO string")
nt("TSP", "tsppredictor/calendar.py", [18, 208, 227], "ok", "explicit America/New_York", "TSP request cutoffs are Eastern time; naive request times are tagged ET")
nt("TSP", "tsppredictor/data/ingest_tsp.py", 136, "ok", "aware -> ET", "aware timestamp converted to ET before taking the date")
nt("TSP", "tsppredictor/data/release_calendar.py", 194, "ok", "explicit America/New_York", "today in ET")
nt("TSP", "tsppredictor/data/release_calendar.py", 307, "accepted", "host zone (ET on the iMac)",
   "default today=date.today() uses the host zone; matches ET on the iMac. release_calendar.py is under open PR #8.")
nt("TSP", "tsppredictor/report/static/app.js", [156, 157], "ok", "explicit America/New_York", "Intl formatter pinned to ET")
nt("TSP", "tsppredictor/report/static/app.js", 179, "ok", "UTC-noon cursor, UTC getters",
   "cursor is built as T12:00:00Z and stepped with setUTCDate, so toISOString().slice(0,10) is the intended calendar day")
nt("TSP", "tsppredictor/features/pipeline.py", [70, 92], "NOT_APPLICABLE", "calendar dates", "naive midnight of a market calendar date; no time of day or zone involved")
nt("TSP", "tsppredictor/features/pipeline.py", 269, "ok", "drops exchange tz", "yfinance index is exchange-local; tz removed after normalizing to the trading date")
nt("NOVA", "app/shared/chat-tools.mjs", 134, "accepted", "UTC date shown as 'today' (risk)",
   "Daily brief title uses toISOString().slice(0,10), the UTC date; after 7 PM EST (8 PM EDT) it shows tomorrow's date. chat-tools.mjs is under open PR #8; fix after it merges (format in America/New_York).")
nt("NOVA", "app/shared/extra-routes.mjs", [164, 187], "accepted", "date-only string parsed as UTC (risk)",
   "new Date('YYYY-MM-DD') is UTC midnight, which is the previous evening in ET if read with local getters. extra-routes.mjs is under open PR #8.")
nt("NOVA", "app/shared/mode-persona.mjs", 56, "ok", "host local (ET)", "hour of day for persona mood; local zone is intended")
nt("NOVA", "app/shared/zip-store.mjs", [5, 6], "ok", "local by ZIP spec", "ZIP DOS timestamps are local time by format")
nt("MC", "main.js", [2464, 2484], "accepted", "UTC date in default filename (cosmetic)",
   "Save-dialog default name uses the UTC date; after 7 PM ET it shows tomorrow. main.js is under open PR #56.")
nt("MC", "long-report.js", 69, "ok", "UTC on a UTC-parsed month", "month built from a YYYY-MM value parsed as UTC, so formatting in UTC keeps the same month")
nt("MC", "renderer.js", 5, "ok", "host local (ET)", "day/night theme from local hour")
nt("MC", "renderer.js", 523, "ok", "local offset for datetime-local", "shifts by getTimezoneOffset so the datetime-local input shows local time")

# 12.8 Direct Overwrite (named targets)
def dw(repo, f, l, verdict, detail, reason):
    ov(repo, "12.8", f, l, verdict, detail, reason)
dw("TSP", "tsppredictor/connectors/profiling.py", 56, "fixed", "atomic (temp + os.replace)",
   "price_profile.json is read back on the next build to compare profiles; a crash mid-write left truncated JSON and the next build raised on json.loads. Now written to a temp file and replaced.")
dw("HUD", "app/backend/app/services/documents_backup_service.py", 70, "fixed", "atomic (temp + replace)",
   "The documents manifest is the integrity record for a backup's zip; a partial write left a manifest that fails verification. Now temp + replace, like the zip beside it.")
dw("MC", "document-generator.js", [116, 128], "fixed", "exclusive create", "See 12.3: now opens with 'wx' so an existing export is never replaced.")

# 12.5 Silent Catch named fixes
def sc(repo, f, l, verdict, detail, reason):
    ov(repo, "12.5", f, l, verdict, detail, reason)
sc("MC", "extension-sdk.js", 12, "fixed", "logged reason",
   "discoverRecipes() returned [] for an unreadable folder and silently dropped any recipe whose JSON or manifest was invalid. Each skip now logs a console.warn with the folder or file and the reason; return values are unchanged.")
sc("HUD", "app/backend/app/services/retirement_service.py", [178, 836], "fixed", "logged reason",
   "An unparseable high3_override / target_retirement_age assumption silently fell back to the default. Now logs a warning naming the assumption and the bad value; the fallback is unchanged.")
sc("HUD", "app/backend/app/services/secure_store.py", 31, "fixed", "logged reason",
   "delete_secret() swallowed every keyring error, so a failed delete left a credential behind with no trace. Now logs the failure (without the secret); behavior is otherwise unchanged.")

# 12.7 Lossy Text named fixes
def lx(repo, f, l, verdict, detail, reason):
    ov(repo, "12.7", f, l, verdict, detail, reason)
lx("HUD", "app/backend/app/utils/simple_pdf.py", 13, "fixed", "latin-1 -> cp1252 (WinAnsi)",
   "The PDF font is declared /WinAnsiEncoding (cp1252) but text was encoded latin-1, so en/em dashes, curly quotes, bullets and the ellipsis printed as '?'. Now encoded cp1252; characters outside WinAnsi (emoji, CJK) still become '?' by design of the base-14 font.")
lx("HUD", "app/backend/app/utils/simple_pdf.py", 37, "ok", "byte-preserving", "stream re-encodes the cp1252 byte values 1:1 (latin-1 maps code points 0-255 to the same bytes)")
lx("NOVA", "app/shared/api.mjs", 216, "accepted", "silent 2,500-char TTS cut (risk)",
   "Speech text over 2,500 characters is cut without telling the caller. api.mjs is under open PR #8; recommend returning a truncated flag or splitting into chunks after it merges.")
lx("HUD", "app/backend/app/services/document_financial_extraction_service.py", 86, "ok", "decode fallback chain", "tries utf-8-sig, utf-16, then latin-1 so any byte string decodes; extraction is best-effort")
lx("TSP", "tsppredictor/data/ingest_macro.py", 91, "ok", "source encoding", "the GPR zip's CSV is latin-1 encoded at the source")
lx("MC", "png-workflow-metadata.js", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], "ok", "PNG tEXt is latin-1 by spec", "PNG tEXt chunks are defined as Latin-1")


# ---------------------------------------------------------------- rules
def _rule(census, s):
    code, f = s["code"], s["file"]
    if census == "12.5":
        if s.get("comment"):
            return "accepted", "exception note (inline)", f"inline note: {s['comment'][:160]}"
        if re.search(r"\.json\(\)\s*\.catch", code) or re.search(r"\.json\(\)\.catch", s.get("body", "")):
            return "accepted", "exception note", "non-JSON HTTP error body falls back to {}; the caller still checks response.ok/status and throws"
        if re.search(r"(freeMemory|\.cancel\(|/interrupt|'/queue'|destroy\(\))[^;]*\.catch\(\s*\(\)\s*=>", code):
            return "accepted", "exception note", "best-effort cleanup after the main result; a failure here has no user-visible effect"
        if re.search(r"\.play\(\)\s*\.catch", code):
            return "accepted", "exception note", "media autoplay rejected by browser policy is expected and harmless"
        ctx = s.get("try_ctx", "")
        if re.search(r"localStorage|sessionStorage", ctx[-250:]):
            return "accepted", "exception note", "missing or corrupt saved preference falls back to defaults"
        exc = s.get("exc", "")
        if "ImportError" in exc:
            return "accepted", "exception note", "optional dependency probe; absence is a normal configuration"
        if "FileNotFoundError" in exc:
            return "accepted", "exception note", "missing file is a normal state here"
        if re.search(r"except \(?(ValueError|InvalidOperation|IndexError|UnicodeDecodeError|TypeError|KeyError|JSONDecodeError|json\.JSONDecodeError)", exc) and re.search(r"\|\s*(continue|pass|return None|return False|\w+ = (None|0|\{\}))", code):
            return "accepted", "exception note", "unparseable optional value is skipped or defaulted by design; parse helper returns None/default to its caller"
        if re.search(r"(OSError|SubprocessError|URLError)", exc):
            return "accepted", "exception note", "probe of an optional external tool/file; caller treats None/False as unavailable"
        return None
    if census == "12.7":
        if s.get("auto") == "warned":
            return "ok", "warned", "truncation marker or warning next to the cut"
        if re.search(r"\[\s*:\s*\w+\s*\]\s*=", code) or re.search(r"(matrix|excess|labels|c_rets|order|ranked|worst|starts|files|rows|items|jobs|history|checks|issues|pulls|attachments|Threads|threads|schemas|metrics|archive|recoverable|previous|results|entries|list|matches|conflicts|failed|problems|seen|sorted\(|\]\)|values|lines|records|samples|steps|candidates|tags|models|nodes|events|messages|keys|parts|sources|hits|facts|ids|paths|urls|cases|queue|objects|options|chunks|sections|blocks|errors|warnings|names|refs|commits|branches)\w*\)?\.slice\(\s*0\s*,", code) and not re.search(r"String\(|text|content|message|prompt", code.split(".slice(")[0][-30:] if ".slice(" in code else ""):
            return "NOT_APPLICABLE", "list cap", "caps a list/array length, not text content"
        if re.search(r"(order|ranked|worst|starts|manifest\[.files.\]|failed|problems|sorted\(.*\))\s*\[\s*:", code):
            return "NOT_APPLICABLE", "list cap", "caps a list/array length, not text content"
        if re.search(r"(sha|hash|Hash|revision|requestId|promptHash|uuid|hex|Id)\w*\)?\.slice\(\s*0\s*,\s*(6|7|8|10|12|16)\)|uuid4\(\)\.hex\[:|\.hex\[:\d+\]", code):
            return "NOT_APPLICABLE", "id abbreviation", "abbreviates an identifier for display; the full value is kept"
        if re.search(r"\.slice\(\s*0\s*,\s*(7|10|19)\)", code) and re.search(r"(date|Date|month|posted|toISOString|at\b|At\b|iso)", code):
            return "NOT_APPLICABLE", "date prefix", "takes the YYYY-MM / YYYY-MM-DD prefix of an ISO date string"
        if re.search(r"(err|error|Error|message|stderr|stdout|failure|detail|exc|reason|output|warning|status|statusText|body\.error|raw|response|log)\w*\)?\s*(\|\|\s*\w+\)?)?\s*(\.slice\(\s*0\s*,|\[\s*:)", code) or re.search(r"str\(exc\)\[:", code):
            return "accepted", "error excerpt", "error/diagnostic excerpt for display or a status field; the cut is not user content"
        if re.search(r"(safeName|slug|tag|safe_label|filename|fileName|basename)", code):
            return "accepted", "name length cap", "filename/slug length cap"
        if re.search(r"(title|name|summary|description|location|label|caption|query|subject)\w*['\"]?\]?\)?\s*(or \"[^\"]*\"\)?)?\s*(\.slice\(\s*0\s*,|\[\s*:)\s*\d+", code, re.I):
            return "accepted", "field length cap", "length cap on a short stored/display field (title, name, summary, location)"
        if re.search(r"(\.filter\([^)]*\)|\.map\([^)]*\)|\.sort\([^)]*\)|Object\.(keys|values|entries)\([^)]*\)|\.split\([^)]*\)|\[\.\.\.[^\]]*\]|new Set\([^)]*\)\]|\.receipts|\.inputs|Tokens|commands|history|Bits|\.flat\(\))\S{0,40}\.slice\(\s*0\s*,", code) and not re.search(r"\.join\([^)]*\)\s*\.slice", code):
            return "NOT_APPLICABLE", "list cap", "caps a list/array length, not text content"
        m2 = re.search(r"([A-Za-z_]\w*)\s*\.slice\(\s*0\s*,", code)
        if m2 and m2.group(1).endswith("s") and not m2.group(1).endswith(("ss", "us", "is")) and m2.group(1) not in ("details", "contents", "lyrics"):
            return "NOT_APPLICABLE", "list cap", "caps a list/array length, not text content"
        m = re.search(r"\.slice\(\s*0\s*,\s*([\w_]+)\s*\)|\[\s*:\s*([\w_]+)\s*\]", code)
        if m and re.search(r"(String\(|text|content|prompt|context|summary|request|snippet|sentence|clean|bounded|value|body|html|source|markdown|reply|answer|note|objective|role|str\(|\.join\()", code, re.I):
            n = m.group(1) or m.group(2)
            return "accepted", f"silent cap ({n} chars)", f"silent length cap of {n} characters on text bound for storage, display or model context; no truncation marker"
        if re.search(r"\.decode\([^)]*['\"]replace['\"]", code):
            return "accepted", "decode with replace", "undecodable bytes become U+FFFD; the parser downstream rejects malformed rows loudly"
        return None
    if census == "12.8":
        if s.get("auto") == "atomic":
            return "ok", "atomic", "temp file + rename/replace in the same function"
        if s.get("auto") == "append":
            return "NOT_APPLICABLE", "append-only", "appends to a log; never replaces earlier content"
        if f.startswith(("scripts/", "evaluation/")) or "/scripts/" in f:
            return "accepted", "dev/eval script output", "manual dev or evaluation script output; regenerated on the next run"
        return None
    if census == "12.6":
        if "date.today()" in code:
            return "accepted", "host zone (ET on the iMac)", "date.today() uses the host clock's zone; matches America/New_York on the iMac that runs it, would drift on a UTC host"
        if re.search(r"\bdate\.fromisoformat\(|_date\.fromisoformat\(", code):
            return "NOT_APPLICABLE", "date-only parse", "parses a calendar date; no time of day or zone"
        if re.search(r"toLocale(String|TimeString|DateString)\(", code) and "timeZone" not in code:
            return "ok", "browser local (ET)", "formats for display in the viewer's local zone (ET)"
        return None
    if census == "12.10":
        return "NOT_APPLICABLE", "not a statistic label", "statistic word appears in an identifier, docstring, prompt or message, not on a reported statistic"
    if census == "12.9":
        if s.get("auto") == "NOT_APPLICABLE":
            return "NOT_APPLICABLE", "never grown", s.get("note", "")
        if s.get("auto") == "bounded":
            return "ok", "bounded", s.get("note", "")
        return None
    return None


def classify(repo, s, regex_results=None):
    r = SHORT[repo]
    c = s["census"]
    key = (r, c, s["file"], s["line"])
    if key in OV:
        return OV[key]
    if c == "12.2":
        return classify_regex(r, s, regex_results)
    got = _rule(c, s)
    if got:
        return got
    return ("UNREVIEWED", "", "")


def classify_regex(r, s, results):
    f, l, pat = s["file"], s["line"], s.get("pattern", "")
    kinds = KINDS.get((r, f, l), "NA")
    if kinds is None:
        kinds = PROVIDER_KINDS.get(pat, "NA")
    if kinds == "NA":
        reason = next((v for k, v in REGEX_NA_REASON.items() if (k in f if ":" not in k else f"{f}:{l}" == k)), "not an error classifier")
        return ("NOT_APPLICABLE", "not an error classifier", reason)
    res = (results or {}).get(s["site_key"], {})
    matches = res.get("matches", [])
    if kinds == {"phrase"}:
        false = [w for w, k in matches]
        return ("ok" if not false else "accepted", "exact-phrase match", "matches one exact runtime message; no word-list hits" if not false else f"word-list hits: {false}")
    if kinds == {"anyfailure"}:
        return ("ok", "intentionally broad", "any 'fail'/'error' in a log means a failing log; broad by design")
    false = [w for w, k in matches if k not in kinds]
    if (r, f, l, pat) in REGEX_FIXED:
        return ("fixed", f"false matches before fix: {false}", "word boundaries added; see the after-fix row in error_regex_tests.csv")
    if not false:
        return ("ok", "no false matches", f"kinds {sorted(kinds)}; word list hits only its own kinds")
    return ("accepted", f"false matches: {false}", f"kinds {sorted(kinds)}; recorded, not changed (broad match is the intended fallback order)")

# 12.7 residual overrides
for l in [28, 63, 73, 128, 163, 175, 277, 292]:
    lx("MC", "local-tool-executor.js", l, "ok", "warned", "truncate() appends '[output truncated]' when it cuts")
lx("MC", "local-tool-executor.js", 165, "ok", "warned", "returns truncated: true with the matches")
lx("MC", "local-tool-executor.js", 284, "NOT_APPLICABLE", "list cap", "caps a file list")
lx("MC", "code-symbol-search.js", 8, "ok", "flag consumer", "rejects results that report truncated: true")
lx("MC", "retrieval-provenance.js", 6, "ok", "warned", "appends '[truncated; complete result stored ...]'")
lx("MC", "canonical-governance-bridge.js", 44, "ok", "lossless escape", "non-ASCII is escaped as \\uXXXX, not dropped")
lx("MC", "canonical-scorecard-evaluator.js", 17, "ok", "lossless escape", "non-ASCII is escaped as \\uXXXX, not dropped")
for f, ls in [("evaluation/agent-capability-20/output-acceptance.js", [174, 241, 243, 244]), ("png-workflow-metadata.js", [83]),
              ("scripts/validate-assets.js", [16]), ("scripts/validate-icon-set.js", [6]), ("scripts/validate-visual-regression.js", [15]),
              ("verification-engine.js", [50, 54])]:
    lx("MC", f, ls, "NOT_APPLICABLE", "binary signature", "reads magic bytes (PNG/RIFF/OggS/%PDF) as ASCII; not text content")
lx("MC", "png-workflow-metadata.js", [21, 26], "ok", "PNG tEXt keyword is latin-1 by spec", "PNG tEXt keywords are Latin-1; values decoded as UTF-8")
lx("MC", "long-report.js", [57, 62], "NOT_APPLICABLE", "drops last element", "slice(0, -1) splits names for APA formatting; nothing is lost")
lx("MC", "media-auto-lora.js", 479, "NOT_APPLICABLE", "prompt words", "the word 'truncated' is negative-prompt text")
lx("MC", "ollama-artifact-transport.js", 35, "NOT_APPLICABLE", "stream framing", "splits a stream buffer at a record boundary; the remainder is kept")
lx("MC", "document-generator.js", 12, "accepted", "name length cap", "filename slug length cap")
lx("MC", "main.js", 2007, "accepted", "name length cap", "MCP tool-name slug length cap (provider limit)")
lx("MC", "diagnostics-store.js", 8, "accepted", "silent cap (diagnostic fields)", "redacted diagnostic fields capped at 40-100 chars; diagnostics are summaries")
lx("MC", "job-contract.js", 41, "NOT_APPLICABLE", "list cap", "caps an evidence list")
lx("MC", "main.js", 1760, "NOT_APPLICABLE", "list cap", "at most two attached images")
lx("MC", "main.js", [1775, 1992], "accepted", "silent cap (2000 chars)", "silent cap on an image instruction/observation sent to the model")
lx("MC", "media-body-builder.js", 558, "accepted", "silent cap (180 chars)", "silent cap on a generated prompt fragment")
lx("MC", "public-research.js", 28, "accepted", "field length cap", "title length cap")
lx("MC", "renderer.js", 28, "accepted", "field length cap", "conversation title from the first message, capped at 100 chars")
lx("MC", "src/observability/incremental-index.js", 31, "accepted", "silent cap", "symbol-site summary capped for display")
lx("NOVA", "app/shared/chat-tools.mjs", [5, 7], "accepted", "silent cap (80/700 chars)", "recent-history digest for the prompt; each message cut to 80 chars, total to 700")
lx("NOVA", "app/shared/paths.mjs", 22, "NOT_APPLICABLE", "KEY=VALUE parse", "takes the key before '='; nothing is lost")
lx("HUD", "app/backend/app/services/automation_service.py", 584, "accepted", "silent cap (900 chars)", "watchdog alert message capped at 900 chars")
lx("TSP", "tsppredictor/provenance.py", 86, "NOT_APPLICABLE", "list cap", "first 20 problems on the badge; the full list stays in the verify result")
lx("TSP", "tsppredictor/studies.py", 407, "NOT_APPLICABLE", "array cap", "bootstrap index array trimmed to the horizon")

# 12.5 residual exception notes
def scs(repo, f, ls, verdict, reason, detail="exception note"):
    sc(repo, f, ls, verdict, detail, reason)
scs("MC", "main.js", [12, 2184], "accepted", "this catch is inside the startup log writer itself; its own failure has nowhere else to be logged")
scs("MC", "diagnostics-store.js", 8, "accepted", "inside the diagnostics writer; diagnostics must never break the app (see main.js:557 note)")
OPT = "missing or unreadable optional file/folder returns the empty default; first run has no file"
for f, ls in [("main.js", [268, 313, 2489, 2585, 2609]), ("artifact-registry.js", [14]), ("plugin-catalog.js", [8, 13]),
              ("nova-lora-bench.js", [105, 190]), ("voice-installation.js", [19]), ("media-scene-tags.js", [241]), ("png-workflow-metadata.js", [14]),
              ("diagnostics-store.js", [9]), ("rag-index.js", [42]), ("build-archive-matcher.js", [91])]:
    scs("MC", f, ls, "accepted", OPT)
scs("NOVA", "app/shared/voice-lock.mjs", 21, "accepted", OPT)
scs("MC", "main.js", [1354, 1356, 1362], "accepted", "tool-availability probe (which); empty result means not installed and the UI says so")
for f, ls in [("scripts/read-packaged-revision.js", [42, 60]), ("scripts/generate-release-manifest.js", [16]), ("scripts/inspect-mac-package.js", [30]),
              ("scripts/deepteam_runner.py", [416])]:
    scs("MC", f, ls, "accepted", "dev/packaging script probe; an empty value is reported as unknown in the script output")
URLP = "an unparseable URL is treated as not matching (fails closed)"
scs("MC", "evaluation/agent-capability-20/output-acceptance.js", 22, "accepted", URLP)
scs("MC", "public-research.js", 33, "accepted", URLP)
scs("MC", "web-evidence.js", 12, "accepted", "an unparseable URL just gets no domain bonus in the evidence score")
scs("NOVA", "app/shared/api.mjs", 24, "ok", URLP)
CB = "guard around an optional UI/status callback; a failing callback must not break the job it reports on"
scs("MC", "commander-nova.js", 48, "accepted", CB)
scs("MC", "nova-lora-bench.js", 348, "accepted", CB)
scs("MC", "renderer.js", [715, 762, 38, 46, 233, 505, 621], "accepted", "optional UI refresh/restore step; the main action already succeeded and the view keeps its previous state")
scs("MC", "renderer.js", [29, 541, 575, 806], "accepted", "optional UI fetch (status badge, preview, autosave before new chat); failure leaves the previous view")
scs("MC", "index-with-states.html", 452, "accepted", "window button outside Electron (browser preview) has no ipcRenderer")
scs("MC", "main.js", [225, 2395], "accepted", "scheduled workflow run records its own outcome in the schedule store (see main.js:247 note)")
scs("MC", "main.js", 2197, "accepted", "background monitor tick; the next tick retries in 15 s")
scs("MC", "main.js", 1486, "accepted", "ffmpeg conversion failure returns null; the caller treats null as no transcript")
scs("MC", "main.js", 1783, "accepted", "optional git-origin hint for the prompt; no repo means no hint")
scs("MC", "main.js", [2047, 2050], "accepted", "non-JSON MCP response; the caller's null check reports the error")
scs("MC", "main.js", 2593, "accepted", "cache read miss falls through to a fresh download with sha256 check")
scs("MC", "main.js", 506, "accepted", "ComfyUI not configured: client stays null and the UI shows it as disconnected")
scs("MC", "deepteam-bridge.js", 114, "accepted", "symlink probe; empty target means not a symlink")
scs("MC", "deepteam-bridge.js", 260, "accepted", "unparseable runner JSON line is ignored; raw output is kept in the buffer (see line 218 note)")
scs("MC", "comfyui-client.js", 161, "accepted", "error-body read while already building an error; the HTTP status is still reported")
scs("MC", "credential-store.js", 7, "ok", "persist() returns false to the caller, which reports the save failure")
sc("MC", "credential-store.js", 6, "fixed", "logged reason",
   "If the saved credentials file could not be read or decrypted (corrupt file, keychain change), every saved key silently vanished. Now logs a warning with the error code (never the values); keys that did load are kept as before.")
scs("MC", "nova-lora-bench.js", [162, 171, 256, 260], "accepted", "best-effort ComfyUI status probe in the LoRA bench; missing fields show as unknown")
scs("NOVA", "app/shared/dispatch.mjs", 67, "ok", "malformed percent-escape returns null and the route answers 404")
scs("NOVA", "app/shared/media-path.mjs", 13, "ok", "malformed escape returns null (404); removed with the double-decode fix")
scs("NOVA", "app/src/lib/api.ts", 53, "accepted", "unreadable consent record means no consent (fails closed)")
scs("HUD", "app/backend/app/core/security.py", 36, "ok", "invalid JWT returns None, which the caller turns into 401 (fails closed)")
scs("HUD", "app/backend/app/services/retirement_service.py", 55, "accepted", "assumption parse helper returns the documented default; callers label which assumptions were defaulted")
scs("TSP", "tsppredictor/models/ml.py", 94, "accepted", "scoring failure returns None and the trial is recorded with loss=None")
scs("TSP", "tsppredictor/models/ml.py", [184, 217], "accepted", "a candidate whose fit raises is kept in the trials log with loss=None and never selected")
scs("TSP", "tsppredictor/report/static/app.js", [765, 803, 808, 813, 814, 815, 842], "accepted",
    "optional report panel; load() already throws on HTTP errors and the panel stays hidden when its JSON is absent. app.js is under open PR #8.")

# 12.8 residual
NEWF = "writes a new uniquely named file (timestamp/uuid/digest name); there is no earlier content to corrupt"
dw("MC", "audio-production.js", 53, "accepted", "new file (digest name)", NEWF)
dw("MC", "comfyui-client.js", 329, "accepted", "new file", "downloaded output saved under ComfyUI's unique output name")
dw("MC", "commander-nova.js", 61, "accepted", "new file (ms name)", NEWF)
dw("MC", "main.js", [1481, 2600, 2742], "accepted", "new or cache file", "temp input / sha-checked model cache / uniquely named artifact; a partial file is re-fetched or never referenced")
dw("MC", "main.js", [1560, 1568, 1570], "NOT_APPLICABLE", "external tool output", "path handed to the codex CLI inside a private temp dir; read back once")
dw("MC", "nova-lora-bench.js", [378, 380], "accepted", "new file (ms name)", NEWF)
dw("MC", "productivity-artifacts.js", [44, 55, 60], "accepted", "new file (ms name)", NEWF)
dw("MC", "artifact-data-bundle.js", [193, 194], "accepted", "new bundle folder", "written into a fresh bundle directory created for this export")
dw("MC", "build-archive-matcher.js", 217, "ok", "copy only if absent", "copies only when the destination does not exist")
dw("MC", "project-store.js", 49, "ok", "COPYFILE_EXCL", "exclusive copy; never replaces an existing file")
dw("MC", "project-store.js", 28, "ok", "create only if absent", "writes the manifest only when it does not exist")
dw("MC", "local-tool-executor.js", 195, "ok", "wx temp + link", "writes a 'wx' temp file then hard-links it into place (fails if the target exists)")
dw("MC", "main.js", [2465, 2911], "NOT_APPLICABLE", "user-chosen export path", "the OS save dialog chose the path and confirmed any replacement")
dw("MC", "diagnostics-store.js", 10, "NOT_APPLICABLE", "user-chosen export path", "redacted diagnostics export to the path picked in the save dialog")
dw("MC", "main.js", 2488, "ok", "atomic", "runOllamaEvaluation writes temp + renameSync (ollama-evaluator.js:41)")
dw("MC", "ollama-evaluator.js", 23, "NOT_APPLICABLE", "parameter name", "outputFile parameter; the write itself is temp + rename")
dw("MC", "credential-store.js", 7, "fixed", "atomic (temp + rename)",
   "Saved credentials were rewritten in place; a crash mid-write left unparseable JSON and every saved key was lost on next start. Now writes a 0600 temp file and renames it over the old one.")
dw("MC", "main.js", [378, 385, 519, 2513], "accepted", "direct overwrite of a small state file (risk)",
   "privacy state / tool approvals / selected project are rewritten in place; a crash mid-write resets them to defaults on next start. main.js is under open PR #56, so not changed here; recommend the same temp + rename helper used in agent-task-ledger.js.")
dw("MC", "deepteam-bridge.js", 191, "accepted", "derived copy", "latest.json is a copy of the run's summary.json, which stays intact; deepteam-bridge.js is under open PR #56")
dw("MC", "long-report.js", 215, "accepted", "per-report manifest", "manifest written once beside a newly generated report")
dw("MC", "p0-evaluation.js", 50, "accepted", "regenerable report", "evaluation report regenerated on each run")
dw("MC", "src/functions/b3.js", [103, 115], "accepted", "direct overwrite of a small state file (risk)",
   "budget index/state rewritten in place; a crash mid-write loses the running totals. Recommend temp + rename.")
dw("MC", "training-data.js", [61, 63, 65], "accepted", "regenerable dataset export", "dataset files are regenerated from the input file on each run")
dw("NOVA", "addons/recap-mailer/index.mjs", 9, "accepted", "new file", "writes a recap file chosen by the caller (injected fs)")
dw("HUD", "app/backend/app/api/asset_register.py", [141, 188], "accepted", "new file (uuid name)", NEWF)
dw("HUD", "app/backend/app/services/backup_tools_service.py", 197, "ok", "copy only if absent", "skips targets that already exist")
dw("HUD", "app/backend/app/services/documents_backup_service.py", 105, "ok", "restore only if absent", "restores only files that do not already exist")
dw("HUD", "app/backend/app/services/backup_service.py", [306, 308], "accepted", "pre-restore safety copy", "safety copy to a new backup name; backup_service.py is under open PR #8")
dw("HUD", "app/backend/app/services/build_manifest_service.py", 199, "accepted", "history log trim", "rewrites the build history log trimmed to HISTORY_LIMIT lines; losing it loses history only")
dw("TSP", "tsppredictor/build.py", [88, 857, 864], "accepted", "regenerable build output", "static site output in dist/, regenerated by every build")
dw("TSP", "tsppredictor/provenance.py", [45, 89], "accepted", "regenerable build output", "provenance manifest/badge written into dist/ during the build")
dw("TSP", "tsppredictor/cli.py", [171, 172, 372], "accepted", "small CLI outputs", "alert/last-signal/calibration card; cli.py is under open PR #8")
dw("TSP", "tsppredictor/connectors/exports.py", [46, 59, 70, 71, 82], "accepted", "regenerable export", "export package regenerated on demand")
dw("TSP", "tsppredictor/connectors/alfred.py", 71, "accepted", "cache file", "download cache; a bad file is re-downloaded when it fails to parse")
dw("TSP", "tsppredictor/connectors/h15.py", 52, "accepted", "cache file", "download cache; a bad file is re-downloaded when it fails to parse")
dw("TSP", "tsppredictor/data/ingest_macro.py", [68, 69, 81, 82, 123, 142, 145, 147, 154, 158, 159, 165, 172, 173], "accepted", "manual ingest output",
   "manual macro-data ingest writes raw files and notes; re-running the ingest rewrites them")
dw("TSP", "tsppredictor/data/ingest_tsp.py", [179, 202, 203, 204, 205, 217, 227], "accepted", "staging files", "written into the refresh staging folder before validation")
dw("TSP", "tsppredictor/data/ingest_tsp.py", 241, "accepted", "direct copy onto live snapshot (risk)",
   "validated staging CSVs are copy2'd over the live snapshot files; a crash mid-copy leaves a truncated CSV (provenance verify would flag the sha mismatch). Recommend os.replace from a staging dir on the same volume.")
dw("TSP", "tsppredictor/data/ingest_tsp.py", [250, 251, 255], "accepted", "status files", "refresh status JSON; rewritten on the next refresh")
dw("TSP", "tsppredictor/journal.py", 179, "accepted", "export file", "journal export to the requested output path")
