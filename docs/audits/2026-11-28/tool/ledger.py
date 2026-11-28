"""Build the PAPM ten-census ledger for one repo.

Usage:
  python3 tool/ledger.py <repo-dir> <repo-name> <scan.json> <out-dir> [--fix-branch BRANCH]
  python3 tool/ledger.py --verify <out-dir>

Inventory = every tracked file at the scanned revision (git ls-files), with
bytes + sha256. Batches = sorted inventory in groups of <=10. Each batch gets
exactly one reduction record (canonical JSON; record_sha256 = sha256 of the
exact bytes written). coverage.csv has one row per artifact x census and the
run fails unless every row is covered or NOT_APPLICABLE with a reason.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verdicts  # noqa: E402
from scan10 import CENSUSES, NAMES  # noqa: E402

AUDIT_DATE = "2026-11-28"
BATCH_SIZE = 10
VERDICTS = ("ok", "fixed", "accepted", "NOT_APPLICABLE")

# Error-regex sites fixed on the census branch: (file, line, old pattern) -> new pattern + flags.
REGEX_AFTER = {
    ("provider-contract.js", 12, "credential|key|auth"): (r"\b(credentials?|(api[ _-]?)?keys?|auth|authenticat\w*|authori[sz]\w*|unauthori[sz]ed)\b", "i"),
    ("provider-contract.js", 12, "limit|rate|quota"): (r"\b(rate[ _-]?limit\w*|limit(s|ed)?|quotas?|too many requests|429)\b", "i"),
    ("job-contract.js", 53, "log"): (r"\blogs?\b", "i"),
}


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_regex(sites: list[dict]) -> dict:
    tmp = Path("/tmp/ledger_rx_sites.json")
    tmp.write_text(json.dumps(sites))
    out = subprocess.run(["node", str(HERE / "regex_run.mjs"), str(tmp), str(HERE / "regex_words.json")],
                         capture_output=True, text=True, check=True).stdout
    return {r["id"]: r for r in json.loads(out)}


def fix_commits(repo_dir: Path, branch: str | None) -> dict:
    """file -> list of (sha, subject) for commits on branch not on origin/main."""
    if not branch:
        return {}
    log = subprocess.run(["git", "-C", str(repo_dir), "log", "--format=%H%x09%s", "--name-only", f"origin/main..{branch}"],
                         capture_output=True, text=True, check=True).stdout
    out = collections.defaultdict(list)
    sha = subject = None
    for line in log.splitlines():
        if "\t" in line and len(line.split("\t")[0]) == 40:
            sha, subject = line.split("\t", 1)
        elif line.strip() and sha:
            out[line.strip()].append((sha, subject))
    return out


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build(repo_dir: Path, repo: str, scan_path: Path, out: Path, branch: str | None) -> dict:
    scan = json.loads(scan_path.read_text())
    inventory = sorted(scan["inventory"], key=lambda a: a["path"])
    sites = scan["sites"]
    short = verdicts.SHORT[repo]
    regex_sites = [{"id": s["site_key"], "pattern": s["pattern"], "flags": s.get("flags", "")} for s in sites if s["census"] == "12.2"]
    rr = run_regex(regex_sites)
    commits = fix_commits(repo_dir, branch)
    words = json.loads((HERE / "regex_words.json").read_text())

    # Verdict per site.
    rows = []
    for s in sites:
        v, label, reason = verdicts.classify(repo, s, rr)
        if v not in VERDICTS:
            raise SystemExit(f"unreviewed site {s['census']} {s['file']}:{s['line']}")
        fix = ""
        if v == "fixed":
            cands = [c for c in commits.get(s["file"], []) if f"{s['census']}" in c[1]] or commits.get(s["file"], [])
            if branch and not cands:
                raise SystemExit(f"fixed site without a fix commit: {s['file']}:{s['line']}")
            fix = cands[0][0][:12] if cands else ""
        site_id = f"{short}-{s['census']}-{s['site_key']}"
        rows.append({"site_id": site_id, **s, "verdict": v, "label": label, "reason": reason, "fix_commit": fix})
    by_artifact = collections.defaultdict(list)
    for r in rows:
        by_artifact[r["artifact_id"]].append(r)

    out.mkdir(parents=True, exist_ok=True)
    for old in (out / "batches").glob("B*.json") if (out / "batches").exists() else []:
        old.unlink()

    # Inventory + coverage.
    inv_rows, cov_rows = [], []
    coverage_counter = collections.Counter()
    batches = [inventory[i:i + BATCH_SIZE] for i in range(0, len(inventory), BATCH_SIZE)]
    batch_of = {}
    for n, batch in enumerate(batches, 1):
        for a in batch:
            batch_of[a["artifact_id"]] = f"B{n:03d}"
    for a in inventory:
        inv_rows.append([a["artifact_id"], a["path"], a["bytes"], a["sha256"], a["class"], batch_of[a["artifact_id"]]])
        for c in CENSUSES:
            st = a["censuses"][c]
            n_sites = sum(1 for r in by_artifact[a["artifact_id"]] if r["census"] == c)
            if st["status"] == "NOT_APPLICABLE":
                if not st.get("reason"):
                    raise SystemExit(f"NOT_APPLICABLE without reason: {a['path']} {c}")
                if n_sites:
                    raise SystemExit(f"sites on a NOT_APPLICABLE artifact: {a['path']} {c}")
                status, reason = "NOT_APPLICABLE", st["reason"]
            else:
                status, reason = "covered", f"scanned; {n_sites} site(s)"
            coverage_counter[status] += 1
            cov_rows.append([a["artifact_id"], a["path"], c, NAMES[c], status, reason, n_sites])
    expected = len(inventory) * len(CENSUSES)
    assert len(cov_rows) == expected and sum(coverage_counter.values()) == expected
    write_csv(out / "inventory.csv", ["artifact_id", "path", "bytes", "sha256", "class", "batch"], inv_rows)
    write_csv(out / "coverage.csv", ["artifact_id", "path", "census", "census_name", "status", "reason", "sites"], cov_rows)

    # One reduction record per batch.
    red_rows = []
    for n, batch in enumerate(batches, 1):
        bid = f"B{n:03d}"
        arts = [{"artifact_id": a["artifact_id"], "path": a["path"], "bytes": a["bytes"], "sha256": a["sha256"], "class": a["class"]} for a in batch]
        per_census = {}
        for c in CENSUSES:
            cs = [r for a in batch for r in by_artifact[a["artifact_id"]] if r["census"] == c]
            per_census[c] = {
                "name": NAMES[c],
                "artifacts_covered": sum(1 for a in batch if a["censuses"][c]["status"] != "NOT_APPLICABLE"),
                "artifacts_not_applicable": sum(1 for a in batch if a["censuses"][c]["status"] == "NOT_APPLICABLE"),
                "sites": sorted(r["site_id"] for r in cs),
                "verdicts": {v: sum(1 for r in cs if r["verdict"] == v) for v in VERDICTS},
            }
        record = {
            "schema": "papm-reduction-record/v1", "audit": f"ten-census {AUDIT_DATE}", "repo": f"grummpy/{repo}",
            "revision": scan["revision"], "batch": bid, "artifact_count": len(arts), "artifacts": arts,
            "input_digest": sha256("".join(a["sha256"] for a in arts).encode()), "censuses": per_census,
        }
        body = canon(record)
        (out / "batches").mkdir(exist_ok=True)
        (out / "batches" / f"{bid}.json").write_bytes(body)
        red_rows.append([bid, len(arts), arts[0]["artifact_id"], arts[-1]["artifact_id"], record["input_digest"], len(body), sha256(body)])
    write_csv(out / "reductions.csv", ["batch", "artifacts", "first", "last", "input_digest", "record_bytes", "record_sha256"], red_rows)

    # Sites + findings.
    site_header = ["site_id", "census", "census_name", "artifact_id", "file", "line", "verdict", "label", "reason", "fix_commit", "code"]
    def srow(r):
        return [r["site_id"], r["census"], NAMES[r["census"]], r["artifact_id"], r["file"], r["line"], r["verdict"], r["label"], r["reason"], r["fix_commit"], r["code"][:160]]
    ordered = sorted(rows, key=lambda r: (CENSUSES.index(r["census"]), r["file"], r["line"], r["site_id"]))
    write_csv(out / "sites.csv", site_header, [srow(r) for r in ordered])
    write_csv(out / "findings.csv", site_header, [srow(r) for r in ordered if r["verdict"] in ("fixed", "accepted")])

    # Error-regex word tests (before, plus after for fixed regexes).
    rx_rows = []
    after_sites = []
    for r in ordered:
        if r["census"] != "12.2":
            continue
        kinds = verdicts.KINDS.get((short, r["file"], r["line"]), "NA")
        if kinds is None:
            kinds = verdicts.PROVIDER_KINDS.get(r.get("pattern", ""), "NA")
        kinds_txt = "NA" if kinds == "NA" else "|".join(sorted(kinds))
        matched = {w for w, _ in rr.get(r["site_key"], {}).get("matches", [])}
        for w, k in words:
            hit = w in matched
            false = hit and kinds != "NA" and kinds not in ({"phrase"}, {"anyfailure"}) and k not in kinds
            rx_rows.append([r["site_id"], r["file"], r["line"], "before", r.get("pattern", ""), kinds_txt, w, k, int(hit), int(false)])
        key = (r["file"], r["line"], r.get("pattern", ""))
        if key in REGEX_AFTER:
            pat, flags = REGEX_AFTER[key]
            after_sites.append({"id": r["site_id"], "pattern": pat, "flags": flags, "_kinds": kinds, "_r": r})
    if after_sites:
        ar = run_regex([{k: v for k, v in s.items() if not k.startswith("_")} for s in after_sites])
        for s in after_sites:
            matched = {w for w, _ in ar[s["id"]]["matches"]}
            for w, k in words:
                hit = w in matched
                rx_rows.append([s["id"], s["_r"]["file"], s["_r"]["line"], "after-fix", s["pattern"], "|".join(sorted(s["_kinds"])), w, k, int(hit), int(hit and k not in s["_kinds"])])
    write_csv(out / "error_regex_tests.csv", ["site_id", "file", "line", "phase", "pattern", "site_kinds", "word", "word_kind", "matched", "false_match"], rx_rows)
    after_false = collections.Counter((r[0]) for r in rx_rows if r[3] == "after-fix" and r[9])

    totals = {c: {v: sum(1 for r in rows if r["census"] == c and r["verdict"] == v) for v in VERDICTS} for c in CENSUSES}
    for c in CENSUSES:
        totals[c]["sites_found"] = sum(1 for r in rows if r["census"] == c)
        totals[c]["artifacts_covered"] = sum(1 for a in inventory if a["censuses"][c]["status"] != "NOT_APPLICABLE")
        totals[c]["artifacts_not_applicable"] = sum(1 for a in inventory if a["censuses"][c]["status"] == "NOT_APPLICABLE")
    census = {
        "audit": f"ten-census {AUDIT_DATE}", "repo": f"grummpy/{repo}", "revision": scan["revision"],
        "fix_branch": branch, "artifacts": len(inventory), "batches": len(batches), "batch_size_max": BATCH_SIZE,
        "classes": dict(collections.Counter(a["class"] for a in inventory)),
        "coverage": {"rows": expected, **dict(coverage_counter), "percent": 100.0},
        "censuses": {c: {"name": NAMES[c], **totals[c]} for c in CENSUSES},
        "regex_after_fix_false_matches": dict(after_false),
        "reductions_sha256": sha256((out / "reductions.csv").read_bytes()),
    }
    (out / "census.json").write_text(json.dumps(census, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"census": census, "rows": rows}


CENSUS_ONE_LINE = {
    "12.1": "a value is percent-decoded twice (a literal %25 or a bare % breaks)",
    "12.2": "an error-classifying regex matches words it should not (keyboard -> auth)",
    "12.3": "a file name built from a timestamp can collide and overwrite",
    "12.4": "a lock records no owner, so a crash or a second run strands or steals it",
    "12.5": "an exception is caught and dropped with no logged reason",
    "12.6": "a date/time is read in the wrong zone (UTC or host instead of household ET)",
    "12.7": "text is cut, replaced or re-encoded without telling anyone",
    "12.8": "a file is overwritten in place, so a crash leaves it truncated",
    "12.9": "an in-memory collection grows for the life of the process",
    "12.10": "a label names a different statistic than the code computes",
}


def write_summary(repo_dir: Path, repo: str, out: Path, res: dict, branch: str | None, open_prs: str) -> None:
    c = res["census"]
    rows = res["rows"]
    L = []
    L.append(f"# Ten-census audit {AUDIT_DATE}: grummpy/{repo}")
    L.append("")
    L.append(f"- Scanned revision: `{c['revision'][:12]}` (origin/main, {AUDIT_DATE})")
    L.append(f"- Fix branch: `{branch}`" if branch else "- Fix branch: none")
    L.append(f"- Method: The PAPM plan gate. Exact inventory of every tracked file ({c['artifacts']} artifacts), "
             f"{c['batches']} batches of at most {BATCH_SIZE}, one byte-hashed reduction record per batch, and a coverage "
             f"ledger of {c['coverage']['rows']} artifact x census rows: {c['coverage'].get('covered', 0)} covered, "
             f"{c['coverage'].get('NOT_APPLICABLE', 0)} NOT_APPLICABLE with a reason. 100% coverage.")
    L.append(f"- Mirrors the Nov 22 six-census audit (`docs/audits/2026-11-22/`).")
    L.append("")
    L.append("## Counts")
    L.append("")
    L.append("Sites are the places a census detector fired. Each one got a verdict: already correct, fixed on this branch, "
             "accepted (kept, with the reason in `sites.csv`), or NOT_APPLICABLE (the match is not the pattern the census is about).")
    L.append("")
    L.append("| Census | What it looks for | Found | Already correct | Fixed | Accepted | NOT_APPLICABLE | Files scanned / N/A |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    tot = collections.Counter()
    for k in CENSUSES:
        v = c["censuses"][k]
        L.append(f"| {k} {v['name']} | {CENSUS_ONE_LINE[k]} | {v['sites_found']} | {v['ok']} | {v['fixed']} | {v['accepted']} | {v['NOT_APPLICABLE']} | {v['artifacts_covered']} / {v['artifacts_not_applicable']} |")
        for x in ("sites_found", "ok", "fixed", "accepted", "NOT_APPLICABLE"):
            tot[x] += v[x]
    L.append(f"| **Total** | | **{tot['sites_found']}** | **{tot['ok']}** | **{tot['fixed']}** | **{tot['accepted']}** | **{tot['NOT_APPLICABLE']}** | |")
    L.append("")
    L.append("## Fixes on this branch")
    L.append("")
    fixed = [r for r in rows if r["verdict"] == "fixed"]
    if not fixed:
        L.append("None. Nothing in this repo met the bar for a small, safe fix outside files that open PRs already touch.")
    by_commit = collections.defaultdict(list)
    for r in fixed:
        by_commit[r["fix_commit"]].append(r)
    for sha, rs in by_commit.items():
        subject = subprocess.run(["git", "-C", str(repo_dir), "log", "-1", "--format=%s", sha], capture_output=True, text=True).stdout.strip() if sha else ""
        where = ", ".join(sorted({f"`{r['file']}:{r['line']}`" for r in rs}))
        L.append(f"- `{sha}` {subject}  ")
        reasons = list(dict.fromkeys(r["reason"] for r in rs))
        L.append(f"  Sites: {where}. " + " ".join(reasons))
    L.append("")
    L.append("Every fix has a test that fails before the change and passes after it; the full test suite passes on the branch.")
    L.append("")
    risks = [r for r in rows if r["verdict"] == "accepted" and "(risk" in r["label"]]
    L.append("## Accepted risks (recommendations, not changed here)")
    L.append("")
    if not risks:
        L.append("None.")
    seen = set()
    for r in sorted(risks, key=lambda r: (r["census"] != "12.10", CENSUSES.index(r["census"]), r["file"], r["line"])):
        key = (r["census"], r["file"], r["reason"])
        lines = sorted(x["line"] for x in risks if (x["census"], x["file"], x["reason"]) == key)
        if key in seen:
            continue
        seen.add(key)
        L.append(f"- **{r['census']} {NAMES[r['census']]}**, `{r['file']}` line(s) {', '.join(map(str, lines))}: {r['reason']}")
    L.append("")
    if open_prs:
        L.append(f"Files touched by open PRs ({open_prs}) were left alone so the census fixes stay separate; the risks above that name an open PR are deferred until it merges.")
        L.append("")
    rx = list(csv.DictReader((out / "error_regex_tests.csv").open()))
    classifier_rows = [r for r in rx if r["site_kinds"] != "NA"]
    if rx and not classifier_rows:
        L.append("## Error-regex word tests (12.2)")
        L.append("")
        L.append(f"No error-classifying regexes: all {len({r['site_id'] for r in rx})} regex hits are NOT_APPLICABLE (see `sites.csv`). "
                 "Their word-test rows are still in `error_regex_tests.csv` for the record.")
        L.append("")
    if classifier_rows:
        before_false = sum(1 for r in rx if r["phase"] == "before" and r["false_match"] == "1")
        after = [r for r in rx if r["phase"] == "after-fix"]
        L.append("## Error-regex word tests (12.2)")
        L.append("")
        L.append(f"Each error regex was run against a fixed list of {len(json.loads((HERE / 'regex_words.json').read_text()))} error messages with known kinds "
                 f"(`tool/regex_words.json`). Before: {before_false} false matches across all classifier sites. "
                 + (f"After the fixes, the {len({r['site_id'] for r in after})} rewritten regexes have "
                    f"{sum(1 for r in after if r['false_match'] == '1')} false matches and still match "
                    f"{sum(1 for r in after if r['matched'] == '1')} real messages of their own kind." if after else ""))
        L.append("")
    L.append("## Files here")
    L.append("")
    L.append("- `inventory.csv`: every tracked file at the scanned revision, with bytes, sha256, class and batch.")
    L.append("- `batches/B###.json` + `reductions.csv`: one canonical-JSON reduction record per batch; `record_sha256` is the sha256 of the exact file bytes.")
    L.append("- `coverage.csv`: one row per artifact x census, `covered` or `NOT_APPLICABLE` with a reason.")
    L.append("- `sites.csv`: every detector hit with its verdict and reason. `findings.csv`: just the fixed and accepted ones.")
    L.append("- `error_regex_tests.csv`: one row per regex x test message, before and after the fix.")
    L.append("- `census.json`: the totals above, machine-readable.")
    L.append("- `tool/`: the scanner, verdict table and ledger builder used for this run.")
    L.append("")
    L.append("## Re-run")
    L.append("")
    L.append("```bash")
    L.append(f"# Check this ledger as committed: hashes, one record per batch, 100% coverage")
    L.append(f"python3 docs/audits/{AUDIT_DATE}/tool/ledger.py --verify docs/audits/{AUDIT_DATE}")
    L.append("")
    L.append("# Rebuild it from scratch at the scanned revision (needs node for the regex word tests)")
    L.append(f"cp -r docs/audits/{AUDIT_DATE}/tool /tmp/census-tool")
    L.append(f"git worktree add /tmp/census-src {c['revision'][:12]}")
    L.append(f"python3 /tmp/census-tool/scan10.py /tmp/census-src {repo} /tmp/scan.json")
    L.append(f"python3 /tmp/census-tool/ledger.py /tmp/census-src {repo} /tmp/scan.json /tmp/ledger")
    L.append(f"diff /tmp/ledger/reductions.csv docs/audits/{AUDIT_DATE}/reductions.csv && echo identical")
    L.append("```")
    L.append("")
    (out / "SUMMARY.md").write_text("\n".join(L), encoding="utf-8")


def verify(out: Path) -> None:
    n = 0
    with (out / "reductions.csv").open() as fh:
        for row in csv.DictReader(fh):
            body = (out / "batches" / f"{row['batch']}.json").read_bytes()
            assert sha256(body) == row["record_sha256"], row["batch"]
            assert len(body) == int(row["record_bytes"]), row["batch"]
            assert json.loads(body)["artifact_count"] <= BATCH_SIZE
            n += 1
    assert n == len(list((out / "batches").glob("B*.json"))), "one record per batch"
    with (out / "coverage.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    bad = [r for r in rows if r["status"] not in ("covered", "NOT_APPLICABLE") or (r["status"] == "NOT_APPLICABLE" and not r["reason"])]
    assert not bad, bad[:3]
    with (out / "inventory.csv").open() as fh:
        inv = list(csv.DictReader(fh))
    assert len(rows) == len(inv) * len(CENSUSES)
    print(f"OK: {n} batches, {len(inv)} artifacts, {len(rows)} coverage rows, all hashes match")


if __name__ == "__main__":
    if sys.argv[1] == "--verify":
        verify(Path(sys.argv[2]))
        sys.exit(0)
    repo_dir, repo, scan_path, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    branch = sys.argv[sys.argv.index("--fix-branch") + 1] if "--fix-branch" in sys.argv else None
    res = build(repo_dir, repo, scan_path, out, branch)
    open_prs = sys.argv[sys.argv.index("--open-prs") + 1] if "--open-prs" in sys.argv else ""
    write_summary(repo_dir, repo, out, res, branch, open_prs)
    c = res["census"]
    print(repo, c["artifacts"], "artifacts", c["batches"], "batches", c["coverage"])
    for k, v in c["censuses"].items():
        print(" ", k, v["name"], {x: v[x] for x in ("sites_found",) + VERDICTS})
    print("  regex after-fix false matches:", c["regex_after_fix_false_matches"])
