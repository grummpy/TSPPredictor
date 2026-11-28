#!/usr/bin/env python3
"""Ten-census scanner (Nov 27 2026 idea pack, section 12). Inventory pass: lists every tracked file and emits
candidate sites per census. Review verdicts come from verdicts.py and are applied by ledger.py.

Usage: scan10.py <repo_dir> <repo_name> <out_json>
"""
from __future__ import annotations
import hashlib, json, re, subprocess, sys
from pathlib import Path

CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
HTML_EXT = {".html", ".htm"}
SHELL_EXT = {".sh", ".command", ".bash", ".zsh", ".ps1", ".bat", ".cmd"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".icns", ".mp4", ".webm", ".mov", ".mkv",
              ".avi", ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".pdf", ".zip", ".gz", ".tgz", ".7z", ".xls",
              ".xlsx", ".docx", ".pptx", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".glb", ".gltf", ".fbx", ".obj",
              ".safetensors", ".ckpt", ".pt", ".bin", ".onnx", ".sqlite", ".db", ".pyc", ".exe", ".dll", ".so",
              ".dylib", ".jar", ".blend", ".psd", ".tif", ".tiff", ".heic", ".avif", ".pkl", ".npy", ".npz", ".parquet",
              ".sqlite3", ".svgz"}
CENSUSES = ["12.1", "12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "12.8", "12.9", "12.10"]
NAMES = {"12.1": "Double-Decode", "12.2": "Error Regex", "12.3": "Timestamp Filename", "12.4": "Lock Owner",
         "12.5": "Silent Catch", "12.6": "Naive Time", "12.7": "Lossy Text", "12.8": "Direct Overwrite",
         "12.9": "Unbounded Memory", "12.10": "Label Truth"}
SHELL_CENSUSES = {"12.3", "12.4", "12.8"}


def is_test_path(rel: str) -> bool:
    p = "/" + rel.lower()
    n = Path(p).name
    return ("/tests/" in p or "/test/" in p or "/__tests__/" in p or ".test." in n or ".spec." in n
            or n.startswith("test_") or n.endswith("_test.py") or n == "conftest.py")


def is_vendor(rel: str, size: int) -> bool:
    p = rel.lower()
    return ("/vendor/" in "/" + p or "third_party/" in p or p.endswith(".min.js") or p.endswith(".min.css")
            or p.endswith("three-scene.bundle.js") or "node_modules/" in p)


def file_class(rel: str, data: bytes) -> tuple[str, str | None]:
    """Returns (class, NOT_APPLICABLE reason or None for scanned files)."""
    ext = Path(rel).suffix.lower()
    if ext in BINARY_EXT or b"\0" in data[:8192]:
        return "binary", "binary media/archive; holds no executable code paths"
    if is_vendor(rel, len(data)):
        return "vendor", "third-party or generated bundle (minified/vendored); not authored in this repo"
    if "/dist/" in "/" + rel and ext in CODE_EXT | HTML_EXT | {".css"}:
        return "generated", "build output regenerated from app/frontend/src; the source files are censused instead"
    if ext in CODE_EXT:
        if is_test_path(rel):
            return "test", "test code; runs only under the test runner, not on any shipped runtime path"
        return "code", None
    if ext in HTML_EXT:
        if b"<script" in data and not re.search(rb"<script[^>]*\ssrc=", data.split(b"</script>")[0] if False else b""):
            return "html-script", None
        return "markup", "HTML markup with no inline script"
    if ext in SHELL_EXT:
        return "shell", None
    return "data/doc", "non-executable data, documentation or config"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def strip_line_comment(ln: str, lang: str) -> bool:
    s = ln.lstrip()
    return s.startswith("#") if lang == "py" else (s.startswith("//") or s.startswith("*") or s.startswith("/*"))


def block_after(lines: list[str], i: int, lang: str, max_lines=25) -> str:
    """Body of a catch/except starting at line i (0-based)."""
    if lang == "py":
        head = lines[i]
        ind = len(head) - len(head.lstrip())
        out = [head]
        for j in range(i + 1, min(len(lines), i + max_lines)):
            l = lines[j]
            if l.strip() and (len(l) - len(l.lstrip())) <= ind:
                break
            out.append(l)
        return "\n".join(out)
    text = "\n".join(lines[i:i + max_lines])
    k = text.find("{", text.find("catch"))
    if k == -1:
        return lines[i]
    depth = 0
    for idx in range(k, len(text)):
        c = text[idx]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[:idx + 1]
    return text


def enclosing_fn(lines: list[str], i: int, lang: str) -> str:
    rx = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)") if lang == "py" else re.compile(
        r"(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function|[A-Za-z_$][\w$]*\s*=>)|^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{)")
    for j in range(i, max(-1, i - 400), -1):
        m = rx.search(lines[j])
        if m:
            name = next((g for g in m.groups() if g), None)
            if name and name not in ("if", "for", "while", "switch", "catch", "return"):
                return name
    return "<module>"


def snippet(ln, m):
    if len(ln) <= 220:
        return ln.strip()[:200]
    return ln[max(0, m.start() - 100): m.end() + 100].strip()


def fn_window(lines: list[str], i: int, lang: str, back=40, fwd=40) -> str:
    return "\n".join(lines[max(0, i - back): i + fwd])


# ---------------------------------------------------------------- detectors
def d_decode(rel, lines, lang):
    rx = re.compile(r"decodeURIComponent\(|decodeURI\(|\bunquote(_plus)?\(|\bunquote_to_bytes\(|parse_qsl?\(")
    for i, ln in enumerate(lines):
        if strip_line_comment(ln, lang) or not rx.search(ln):
            continue
        win = fn_window(lines, i, lang, 30, 5)
        upstream = []
        if re.search(r"searchParams\.get|URLSearchParams|req\.query|request\.query_params|query_params|parse_qs", win):
            upstream.append("already-decoded query value")
        if re.search(r"\.pathname\b", win):
            upstream.append("raw pathname (percent-encoded)")
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "review", "note": "; ".join(upstream) or "decode site"}


ERR_CTX = re.compile(r"(err|error|exception|message|msg|status|reason|kind|classif|retry|retryable|transient|stderr|fail)", re.I)
ERR_WORDS = re.compile(r"(rate|limit|429|quota|timeout|timed|time.?out|auth|unauthori|forbidden|401|403|network|econn|enotfound|"
                       r"overload|fail|error|503|502|500|unavailable|not.?found|404|invalid|denied|refused|reset|abort|cancel|oom|memory|cuda|disk|space|busy|locked|exceed)", re.I)
JS_RE_LIT = re.compile(r"(?<![\w)\]$])/((?:\\/|\\.|\[[^\]]*\]|[^/\n\[\\])+)/([dgimsuvy]*)")
PY_RE_CALL = re.compile(r"re\.(?:compile|search|match|fullmatch|findall|finditer|sub)\(\s*(r?)(['\"])((?:\\.|(?!\2).)*)\2(?:\s*,\s*([^)]*))?")


def d_error_regex(rel, lines, lang):
    for i, ln in enumerate(lines):
        if strip_line_comment(ln, lang):
            continue
        pats = []
        if lang == "py":
            for m in PY_RE_CALL.finditer(ln):
                flags = "i" if (m.group(4) and ("IGNORECASE" in m.group(4) or "re.I" in m.group(4))) or "(?i)" in m.group(3) else ""
                src = m.group(3) if m.group(1) else m.group(3).encode().decode("unicode_escape", "ignore")
                pats.append((src.replace("(?i)", ""), flags))
        else:
            for m in JS_RE_LIT.finditer(ln):
                pats.append((m.group(1), m.group(2)))
            for m in re.finditer(r"new RegExp\(\s*(['\"`])((?:\\.|(?!\1).)*)\1(?:\s*,\s*['\"]([a-z]*)['\"])?", ln):
                pats.append((m.group(2).replace("\\\\", "\\"), m.group(3) or ""))
        for src, flags in pats:
            subj0 = re.search(r"\.test\(\s*(String\()?\s*(err|error|e|message|msg|reason|stderr|detail)\b|re\.(search|match)\([^)]*\b(str\((e|exc|err|error)\)|message|msg|stderr)\b", ln)
            if not (ERR_WORDS.search(src) or subj0):
                continue
            ctx = "\n".join(lines[max(0, i - 3): i + 3])
            subj = re.search(r"\.test\(\s*(String\()?\s*(err|error|e|message|msg|reason|stderr|detail|text)\b|(err|error|exc|e|message|msg)\b\)|\bstr\((e|exc|err|error)\)", ln)
            if not (ERR_CTX.search(ctx) or subj):
                continue
            yield {"line": i + 1, "code": ln.strip()[:200], "auto": "test", "pattern": src, "flags": flags, "note": ""}


TS_EXPR = re.compile(r"(Date\.now\(\)|new Date\(\)\.(toISOString|getTime|valueOf)\(\)|toISOString\(\)|datetime\.(now|utcnow)\(|time\.time\(\)|time\.strftime|\.strftime\(|date \+%|Get-Date|%date%|now\.isoformat|stamp|timestamp)", re.I)
FILE_CTX = re.compile(r"(path\.join|path\.resolve|join\(|Path\(|/ f['\"]|\.(json|jsonl|txt|md|png|jpg|mp4|wav|mp3|log|csv|zip|db|sqlite|html|pdf|docx|webm|bak|tmp)\b|writeFile|createWriteStream|open\(|mkdir|filename|file_name|fileName|outFile|out_path|outPath|dest|\.with_name|\.with_suffix|copyfile|copy2|rename|> \"?\$)", re.I)


def d_timestamp(rel, lines, lang):
    for i, ln in enumerate(lines):
        if lang != "sh" and strip_line_comment(ln, lang):
            continue
        if not TS_EXPR.search(ln) or re.match(r"\s*(from\s+\S+\s+import|import\s)", ln):
            continue
        if not FILE_CTX.search(ln):
            am = re.match(r"^\s*(?:const|let|var|\$)?\s*(\w+)\s*=\s*.*(strftime|Date\.now\(\)|toISOString\(\)|datetime\.now|time\.time\(|Get-Date|date \+%)", ln)
            if not am or re.search(r"(started|elapsed|start|t0|begin|deadline|now|ms|at)$", am.group(1), re.I):
                continue
            v = re.escape(am.group(1))
            later = lines[i + 1: i + 16]
            if not any(re.search(rf"(\{{{v}\}}|\$\{{{v}\}}|\+\s*{v}\b|\b{v}\s*\+|\${v}\b)", l2) and FILE_CTX.search(l2) for l2 in later):
                continue
        if re.search(r"(createdAt|created_at|updatedAt|updated_at|generated_at|generatedAt|ts:|\"ts\"|'ts'|at:|time:|timestamp:)\s*[:=]", ln) and not re.search(r"(path|join|file|name)\s*\(|`[^`]*\$\{[^}]*\}[^`]*\.\w+`", ln):
            continue
        win = fn_window(lines, i, "py" if lang == "py" else "js", 5, 25)
        safe = []
        if re.search(r"['\"]wx['\"]|O_EXCL|flag:\s*['\"]wx|mode=['\"]x|open\([^)]*['\"]x['\"]|exist_ok=False", win):
            safe.append("exclusive create")
        if re.search(r"randomUUID|uuid|randomBytes|crypto\.random|secrets\.|token_hex|Math\.random|mkdtemp|mkstemp|NamedTemporaryFile|tempfile|counter|\bseq\b|suffix\s*\+=|\+\+|while .*exists|existsSync\([^)]*\)\s*\)|nanoid|process\.pid|os\.getpid", win):
            safe.append("random/counter/pid suffix")
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "collision-safe" if safe else "review", "note": "; ".join(safe)}


LOCK_RX = re.compile(r"(\.lock\b|lockfile|LOCK_|_lock\b|lock_?path|lockPath|lockDir|lock_dir|flock|fcntl\.|O_EXCL|msvcrt\.locking|proper-lockfile|FileLock|filelock|portalocker|mkdir[^\n]*lock)", re.I)


def d_lock(rel, lines, lang):
    for i, ln in enumerate(lines):
        if lang != "sh" and strip_line_comment(ln, lang):
            continue
        if not LOCK_RX.search(ln):
            continue
        if not re.search(r"(mkdir|open|writeFile|flock|fcntl|O_EXCL|wx|lockSync|acquire|FileLock|locking|exists|touch|mkdirSync|openSync)", ln, re.I):
            continue
        if re.search(r"threading\.Lock|asyncio\.Lock|RLock|Mutex|navigator\.locks", ln):
            continue
        win = fn_window(lines, i, "py" if lang == "py" else "js", 30, 40)
        owner = bool(re.search(r"process\.pid|os\.getpid|\$\$|\bpid\b|hostname|owner", win))
        stamp = bool(re.search(r"Date\.now|time\.time|toISOString|datetime\.now|mtime|createdAt|created_at|started", win))
        recov = bool(re.search(r"stale|STALE|max_?age|maxAge|kill\(\s*\w+\s*,\s*0|process\.kill|os\.kill|psutil|unlink|rmSync|rmdir|ESRCH|timeout|ttl", win, re.I))
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "review", "owner": owner, "timestamp": stamp, "recovery": recov,
               "note": f"owner={'yes' if owner else 'no'} timestamp={'yes' if stamp else 'no'} recovery={'yes' if recov else 'no'}"}


EMPTY_RET_JS = re.compile(r"^\s*(return\s*(\[\]|\{\}|null|undefined|''|\"\"|``|false|0|new Map\(\)|new Set\(\)|-1)?\s*;?|;?)\s*$")
LOG_RX = re.compile(r"(console\.(log|warn|error|info|debug)|logger\.|logging\.|log\(|warn\(|print\(|warnings\.warn|emit\(|report|record|onError|setStatus|status\s*=|errors\.push|throw\b|raise\b|reason|notify|toast|\.error\b|stderr|sys\.exit|process\.exit)", re.I)


def d_silent_catch(rel, lines, lang):
    for i, ln in enumerate(lines if lang == "py" else []):
        if strip_line_comment(ln, lang):
            continue
        if lang == "py":
            if not re.match(r"^\s*except\b.*:\s*(#.*)?$", ln) and not re.match(r"^\s*except\b.*:\s*(pass|return\b.*|continue|None)\s*$", ln):
                continue
            body = block_after(lines, i, "py", 12)
            inner = [l.strip() for l in body.splitlines()[1:] if l.strip() and not l.strip().startswith("#")]
            tail = ln.split(":", 1)[1].strip() if re.match(r"^\s*except\b.*:\s*\S", ln) else None
            if tail and not tail.startswith("#"):
                inner = [tail] + inner
            if not inner:
                continue
            stmts = inner
            silent = all(re.fullmatch(r"(pass|continue|return|return (None|\[\]|\{\}|''|\"\"|False|0|\(\)|set\(\)|-1|default|fallback|\w+)|\w+ = (None|\[\]|\{\}|''|\"\"|False|0))", s) for s in stmts) and len(stmts) <= 2
            if not silent:
                continue
            if LOG_RX.search(body.split("\n", 1)[1] if "\n" in body else ""):
                continue
            yield {"line": i + 1, "code": " | ".join([ln.strip()] + stmts)[:200], "auto": "silent", "exc": ln.strip(),
                   "try_ctx": "\n".join(lines[max(0, i - 8): i]), "note": ""}
    if lang != "py":
        text = "\n".join(lines)
        starts = [0]
        for ln in lines:
            starts.append(starts[-1] + len(ln) + 1)
        import bisect
        def lno(pos):
            return bisect.bisect_right(starts, pos)
        for m in re.finditer(r"\bcatch\s*(\([^)]*\))?\s*\{", text):
            i = lno(m.start()) - 1
            if strip_line_comment(lines[i], lang):
                continue
            k = m.end() - 1
            depth, j = 0, k
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            inner = text[k + 1: j]
            stmts = [x.strip() for x in re.split(r"[;\n]", re.sub(r"//[^\n]*|/\*.*?\*/", "", inner, flags=re.S)) if x.strip()]
            if len(stmts) <= 1 and all(EMPTY_RET_JS.match(x) or re.fullmatch(r"\w+\s*=\s*(null|undefined|\[\]|\{\}|''|false|0)", x) or x in ("continue", "break") for x in stmts):
                comment = re.findall(r"//([^\n]*)|/\*(.*?)\*/", inner, flags=re.S)
                note = " ".join((c[0] or c[1]).strip() for c in comment).strip()
                yield {"line": i + 1, "code": text[max(m.start() - 120, starts[i]): j + 1].replace("\n", " ")[-200:], "auto": "silent", "kind": "catch",
                       "body": inner.strip()[:200], "comment": note[:200], "try_ctx": text[max(0, m.start() - 400): m.start()][-400:], "note": ""}
        for m in re.finditer(r"\.catch\(\s*(?:\(\s*\w*\s*\)|\w+)\s*=>\s*(\{\s*\}|\[\]|\{\}|null|undefined|''|\"\"|false|0|\(\{\}\)|\(\[\]\)|\{\s*return\s*(?:\[\]|null|\{\}|false|undefined|''|0)?;?\s*\})\s*\)", text):
            i = lno(m.start()) - 1
            if strip_line_comment(lines[i], lang):
                continue
            yield {"line": i + 1, "code": text[max(m.start() - 140, starts[i]): m.end()].replace("\n", " ")[-200:], "auto": "silent", "kind": ".catch",
                   "body": m.group(0)[:200], "comment": "", "try_ctx": text[max(0, m.start() - 400): m.start()][-400:], "note": ""}


def d_naive_time(rel, lines, lang):
    if lang == "py":
        rx = re.compile(r"(\.replace\(\s*tzinfo\s*=|tz_localize\(|datetime\.utcnow\(|datetime\.now\(\s*\)|\bdate\.today\(\)|datetime\.today\(|fromtimestamp\(\s*[^,()]*(\([^()]*\))?\s*\)|utcfromtimestamp\(|\.astimezone\(\s*\)|datetime\.combine\(|ZoneInfo\(|pytz\.timezone|time\.localtime|fromisoformat\()")
    else:
        rx = re.compile(r"(toISOString\(\)\s*\.(slice|substring|substr|split)\(\s*(0\s*,\s*10|['\"]T['\"])|new Date\(\s*['\"]\d{4}-\d\d-\d\d['\"]\s*\)|new Date\(\s*[\w.]*(date|Date|day|Day)\w*\s*\)|new Date\(\s*`\$\{[^`]*\}T|new Date\(\s*\w+\s*,\s*\w+\s*-\s*1|getTimezoneOffset|timeZone\s*:|\.setHours\(|\.getHours\(\)|\.getDate\(\)|toLocaleDateString\(|toLocaleString\(|toLocaleTimeString\()")
    for i, ln in enumerate(lines):
        if strip_line_comment(ln, lang):
            continue
        for m in rx.finditer(ln):
            yield {"line": i + 1, "code": snippet(ln, m), "auto": "review", "note": ""}


def d_lossy(rel, lines, lang):
    if lang == "py":
        rx = re.compile(r"(errors\s*=\s*['\"](replace|ignore|backslashreplace|surrogateescape)['\"]|\.(en|de)code\([^)]*['\"](replace|ignore)['\"]|latin-?1|['\"]ascii['\"]|\[\s*:\s*-?\d{2,}\s*\]|\[\s*:\s*[A-Z_]{3,}\s*\]|textwrap\.shorten|\.truncate\(|\[:\s*max_\w+\]|\[:\s*limit\]|\[:\s*\w*(len|max|limit|cap)\w*\])", re.I)
    else:
        rx = re.compile(r"(\.(slice|substring|substr)\(\s*0\s*,\s*([A-Z_][A-Z_0-9]*|\d{2,}|\w*(max|limit|cap|len)\w*)\s*\)|truncate|TextDecoder\([^)]*fatal\s*:\s*false|['\"]latin1['\"]|['\"]ascii['\"]|['\"]binary['\"]|\.normalize\(['\"]NFKD|replace\(/\[\^\\x00-\\x7[fF]\]|\.slice\(0,\s*-?\d+\))", re.I)
    for i, ln0 in enumerate(lines):
      if strip_line_comment(ln0, lang):
        continue
      for mm in rx.finditer(ln0):
        ln = snippet(ln0, mm)
        if lang != "py" and re.search(r"\.(slice|substring|substr)\(0,\s*\d+\)", ln) and re.search(r"(sha|hash|hex|digest|id\b|Id\b|uuid|toISOString|date|Date|token|key\b)", ln) and not re.search(r"(text|message|prompt|content|caption|desc|title|body|summary|lyric|transcript|script|name)", ln, re.I):
            continue
        if lang == "py" and re.search(r"\[\s*:\s*\d+\s*\]", ln) and re.search(r"(sha|hash|hexdigest|digest|isoformat|uuid|\bid\b|_id\b|key\b|date)", ln) and not re.search(r"(text|message|prompt|content|caption|desc|title|body|summary|note|name)", ln, re.I):
            continue
        tail = ln0[mm.end(): mm.end() + 60] + "\n" + (lines[i + 1] if i + 1 < len(lines) and len(lines[i + 1]) < 300 else "")
        warned = bool(re.search(r"(…|\\u2026|\.\.\.['\"`]|truncated|ellipsis|console\.warn|logger\.warn|warnings\.warn)", tail, re.I))
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "warned" if warned else "review", "note": "marker/warning nearby" if warned else ""}


def d_overwrite(rel, lines, lang):
    if lang == "py":
        rx = re.compile(r"(\.write_text\(|\.write_bytes\(|open\([^)]*['\"](w|wb|w\+|wt)['\"]|\.to_csv\(|\.to_json\(|\.to_parquet\(|\.to_excel\(|json\.dump\(|\.save\(|shutil\.copy(file|2)?\()")
    elif lang == "sh":
        rx = re.compile(r"(?<![>&0-9])>\s*[\"']?[\w$./{}-]+|\bcp\s+|Set-Content|Out-File|tee\s")
    else:
        rx = re.compile(r"(writeFileSync\(|writeFile\(|fs\.promises\.writeFile|fsp\.writeFile|createWriteStream\(|copyFileSync\(|copyFile\(|outputFile\(|writeJson\(|Bun\.write)")
    for i, ln in enumerate(lines):
        if lang != "sh" and strip_line_comment(ln, lang):
            continue
        if lang == "sh" and ln.lstrip().startswith(("#", "REM", "::")):
            continue
        for mm in rx.finditer(ln):
          yield from _ow_one(lines, i, ln, mm, lang)


def _ow_one(lines, i, ln0, mm, lang):
        ln = snippet(ln0, mm)
        if True:
          pass
        if lang == "py" and ".save(" in ln and not re.search(r"(doc|document|wb|workbook|img|image|im\b|fig|pdf|prs|presentation|book)\w*\.save\(", ln, re.I):
            return
        if lang == "py" and "json.dump(" in ln and "dumps" in ln:
            return
        if lang == "sh" and re.search(r">\s*/dev/null|2>&1|>\s*&|>\s*\$null|>nul", ln) and not re.search(r">\s*[\"']?[\w$./{}-]+\.(json|txt|log|plist|md|csv|env)", ln):
            return
        if len(ln0) > 220:
            win = ln0[max(0, mm.start() - 400): mm.end() + 400]
        else:
            win = "\n".join(l for l in lines[max(0, i - 12): i + 12] if len(l) <= 400)
        if lang == "py":
            atomic = bool(re.search(r"(os\.replace\(|os\.rename\(|\w+\.replace\(\s*(self\.|path|dest|target|final|out|\w*path)|atomic|NamedTemporaryFile|mkstemp)", win))
        elif lang == "sh":
            atomic = bool(re.search(r"(\bmv\b|Move-Item|Rename-Item)", win))
        else:
            atomic = bool(re.search(r"(renameSync\(|fs\.rename\(|fsp\.rename\(|promises\.rename\(|\brename\(|atomic)", win))
        append = bool(re.search(r"(['\"]a['\"]|['\"]ab['\"]|flag:\s*['\"]a|appendFile|>>)", ln))
        auto = "atomic" if atomic else ("append" if append else "review")
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": auto, "note": ""}


def d_unbounded(rel, lines, lang):
    if lang == "py":
        rx = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*(:\s*[^=]+)?=\s*(\{\}|\[\]|dict\(\)|list\(\)|set\(\)|defaultdict\(|OrderedDict\(|deque\(\s*\)|collections\.)|@(functools\.)?(lru_cache\(\s*maxsize\s*=\s*None|cache\b)|^\s+self\.(?P<attr>_?\w*(cache|memo|seen|history|log|queue|buffer|store|registry|jobs|pending|results|events)\w*)\s*(:\s*[^=]+)?=\s*(\{\}|\[\]|dict\(\)|set\(\)|defaultdict\(|OrderedDict\()", re.I)
    else:
        rx = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(new (Map|Set|WeakMap)\(\s*\)|\[\]|\{\}|Object\.create\(null\))|^\s+this\.(?P<attr>_?\w*(cache|memo|seen|history|log|queue|buffer|store|registry|jobs|pending|results|events|map|clips|entries)\w*)\s*=\s*(new (Map|Set)\(\s*\)|\[\]|\{\})", re.I)
    text = "\n".join(lines)
    for i, ln in enumerate(lines):
        if strip_line_comment(ln, lang):
            continue
        m = rx.search(ln)
        closure = False
        if not m and lang != "py":
            m2 = re.match(r"^\s+(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(new (Map|Set)\(\s*\)|\[\]|\{\})\s*;?\s*$", ln)
            if m2:
                nm2 = re.escape(m2.group("name"))
                after = "\n".join(lines[i + 1: i + 160])
                fn = enclosing_fn(lines, i, lang)
                r = re.search(r"\breturn\s*\{", after)
                if r and re.search(rf"\b{nm2}\s*\.(set|add|push)\(", after[r.start():]) or re.match(r"(create|make|build|new)[A-Z]|.*(Factory|Store|Cache|Registry|Queue|Controller|Manager|Tracker)$", fn):
                    m, closure = m2, True
        if not m:
            continue
        name = m.groupdict().get("name") or m.groupdict().get("attr") or "lru_cache"
        if lang == "py" and name and name.isupper() and re.search(r"=\s*(\{\}|\[\])\s*$", ln) is None:
            pass
        if "WeakMap" in ln:
            yield {"line": i + 1, "code": ln.strip()[:200], "auto": "bounded", "name": name, "note": "WeakMap: entries are collected with their keys"}
            continue
        nm = re.escape(name)
        grows = re.search(rf"\b(this\.|self\.)?{nm}\s*(\.set\(|\.add\(|\.push\(|\.append\(|\.update\(|\.extend\(|\.setdefault\(|\[[^\]]+\]\s*=(?!=))", text)
        if not grows:
            yield {"line": i + 1, "code": ln.strip()[:200], "auto": "NOT_APPLICABLE", "name": name, "note": "never grown after initialization (constant table or reassigned whole)"}
            continue
        shrink = re.search(rf"\b(this\.|self\.)?{nm}\s*(\.delete\(|\.clear\(|\.shift\(|\.splice\(|\.pop\(|\.popitem\(|\.length\s*=|\s*=\s*(\[\]|\{{\}}|new Map|new Set|\w+\.slice|\w+\.filter|\[\.\.\.)|\.size\s*>|\.length\s*>|\[\s*-\d+\s*:\s*\]|\.discard\(|\.remove\()|del\s+(self\.)?{nm}\[|len\((self\.)?{nm}\)\s*>", text)
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "bounded?" if shrink else "review", "name": name,
               "note": "has delete/clear/trim path" if shrink else "grows with no visible cap"}


STAT_WORDS = re.compile(r"(decile|percentile|quantile|quartile|median|\bmean\b|average|\bavg\b|std\b|stdev|sigma|z-?score|z-fold|\bfold\b|annuali[sz]ed|cagr|sharpe|sortino|drawdown|volatility|\bvol\b|p\d{2}\b|\bp95\b|\bp99\b|worst|best|hit.?rate|win.?rate|accuracy|correlation|r2|r\^2|rmse|mae\b|apr\b|apy\b|yield|growth rate|per year|/yr|% ?per|monthly|weekly|daily avg|rolling)", re.I)
STR_LIT = re.compile(r"(['\"])((?:\\.|(?!\1).){3,120})\1")


def d_label(rel, lines, lang):
    for i, ln in enumerate(lines):
        if strip_line_comment(ln, lang):
            continue
        labels = [m.group(2) for m in STR_LIT.finditer(ln) if STAT_WORDS.search(m.group(2))]
        keys = re.findall(r"\b(\w*(decile|percentile|quantile|median|mean|avg|std|zscore|z_fold|fold|annual|cagr|sharpe|drawdown|vol|worst|best|hit_rate|win_rate)\w*)\s*[=:]", ln, re.I)
        if not labels and not keys:
            continue
        code = "\n".join(lines[max(0, i - 2): i + 3])
        if not re.search(r"(quantile|percentile|np\.|statistics\.|\.mean\(|\.std\(|median|sum\(|/\s*len\(|math\.|log\(|sqrt|\*\*|Math\.|reduce\(|\.rolling|pct_change|cumprod|\* ?100|/ ?100|min\(|max\()", code):
            continue
        if re.search(r"(sharpen|meaning|means\b|by any means|percentile-mode|font|color|style|className)", ln, re.I) and not keys:
            continue
        yield {"line": i + 1, "code": ln.strip()[:200], "auto": "review", "labels": labels[:3], "note": ""}


DETECTORS = {"12.1": d_decode, "12.2": d_error_regex, "12.3": d_timestamp, "12.4": d_lock, "12.5": d_silent_catch,
             "12.6": d_naive_time, "12.7": d_lossy, "12.8": d_overwrite, "12.9": d_unbounded, "12.10": d_label}


def html_script_lines(text: str) -> list[str]:
    """Keep only inline <script> bodies; other lines become blank so line numbers stay true."""
    out, inside = [], False
    for ln in text.splitlines():
        low = ln.lower()
        if "<script" in low and "src=" not in low:
            inside = True
            out.append("")
            if "</script>" in low:
                inside = False
            continue
        if "</script>" in low:
            inside = False
            out.append("")
            continue
        out.append(ln if inside else "")
    return out


def main():
    repo, name, outp = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    files = [f for f in subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout.decode().split("\0") if f]
    files.sort()
    inventory, sites = [], []
    for idx, rel in enumerate(files, 1):
        p = repo / rel
        data = p.read_bytes() if p.is_file() and not p.is_symlink() else b""
        cls, na = file_class(rel, data)
        art = {"artifact_id": f"{name[:3].upper()}-A{idx:04d}", "path": rel, "bytes": len(data), "sha256": sha(data), "class": cls,
               "censuses": {}}
        if cls in ("code", "html-script", "shell"):
            text = data.decode("utf-8", "replace")
            ext = Path(rel).suffix.lower()
            lang = "py" if ext == ".py" else ("sh" if cls == "shell" else "js")
            lines = html_script_lines(text) if cls == "html-script" else text.splitlines()
            for c in CENSUSES:
                if lang == "sh" and c not in SHELL_CENSUSES:
                    art["censuses"][c] = {"status": "NOT_APPLICABLE", "reason": "shell/batch launcher: this census targets JS/Python constructs only"}
                    continue
                found = list(DETECTORS[c](rel, lines, lang))
                ids = []
                for k, s in enumerate(found):
                    raw = lines_for = None
                    line_no = None
                    # locate line number by searching code text from the detector order
                    sid_key = f"{c}|{rel}|{s['line']}|{s.get('pattern', '')}|{k}"
                    s.update({"census": c, "file": rel, "lang": lang, "artifact_id": art["artifact_id"],
                              "site_key": hashlib.sha1(sid_key.encode()).hexdigest()[:12]})
                    sites.append(s)
                    ids.append(s["site_key"])
                art["censuses"][c] = {"status": "scanned", "sites": ids}
        else:
            for c in CENSUSES:
                art["censuses"][c] = {"status": "NOT_APPLICABLE", "reason": na}
        inventory.append(art)
    outp.write_text(json.dumps({"repo": name, "revision": rev, "inventory": inventory, "sites": sites}, indent=1))
    from collections import Counter
    print(name, rev[:7], "files", len(inventory), "sites", len(sites), dict(Counter(s["census"] for s in sites)))


if __name__ == "__main__":
    main()
