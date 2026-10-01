#!/usr/bin/env python
# V5 VARIANT of the portable redact_safeagent300.py: the `output` field is WITHHELD. In every row `output` is dropped and
#   replaced by `output_sha256` (sha256 of the ORIGINAL unredacted output, UTF-8) and `output_chars` (its length in
#   characters). All other fields are kept (prompt, reasoning, indicators, error are redacted exactly as in v4), plus
#   response_status and empty_output computed from the original output. No other logic differs from v4.
# What it does: reads the 26 include-list result files (13 raw + 13 scored) READ-ONLY and writes redacted copies
#   to <STAGING_DIR>/redacted_<tag>/, plus redaction_report_<tag>.json, spot_check_index_<tag>.json and
#   source_sha256_<tag>.json into <STAGING_DIR>. Deterministic (seed 42), idempotent.
# Required inputs (environment variables; no defaults):
#   SAFELABS_RESULTS_DIR  directory holding the 26 include-list source files
#   STAGING_DIR           directory where the output folder and reports are written
# Usage: SAFELABS_RESULTS_DIR=... STAGING_DIR=... python redact_safeagent300.py --tag <tag>
# The original raw results (safelabs-eval/results/*.raw.jsonl and the scored siblings) are NOT public.
# This script documents how the released files were built; outsiders cannot re-run it without them.
"""Redact the SafeAgent-300 result files into a release-staging copy.

Run with a Python 3.11+ interpreter that can import safelabs-eval:
    python redact_safeagent300_v5.py --tag <tag>   (environment variables: see the header comment)

Reads the 26 include-list files (13 raw + 13 scored) from SAFELABS_RESULTS_DIR
READ-ONLY, writes redacted copies to STAGING_DIR/redacted_<tag>/, and writes
redaction_report_<tag>.json, spot_check_index_<tag>.json and source_sha256_<tag>.json
into STAGING_DIR. Never prints prompt/output/reasoning/indicators/error text --
only counts and file + row + field references.

Properties
  - Deterministic: fixed seed 42 for the spot-check sample; no other randomness.
  - Idempotent: re-running yields byte-identical output; redacting an already
    redacted file changes nothing (checked in-process, see `idempotence`).
  - Source files are never opened for writing; sha256 is recorded before and
    after and compared.

Redacted fields: prompt, output, reasoning, indicators (list of strings), error.
URLs inside `error` are left unchanged. All other fields are copied as-is; a
derived `response_status` and `empty_output` (bool: output empty or
whitespace-only, independent of response_status) fields are appended (never
overwrite a source field). Outputs go to redacted_<tag>/ (default tag v2, `--tag X`).

response_status precedence (first match wins; derived from the row's own fields):
  provider_error    -- `error` is non-empty
  provider_refusal  -- stop_reason == "refusal"
  truncated         -- stop_reason in {max_tokens, length, MAX_TOKENS}
  empty             -- output is empty / whitespace-only
  ok                -- otherwise
A truncated row whose output is also empty is labelled `truncated`; a refusal
row (always empty output) is labelled `provider_refusal`.
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
import re
import sys
from pathlib import Path

SEED = 42
import os as _os


def _require_env(name, what):
    """Return the value of environment variable `name`, or stop with a clear message."""
    v = _os.environ.get(name)
    if not v:
        raise SystemExit(f"error: environment variable {name} is not set ({what}). "
                         f"See the header comment of this script; there is deliberately no default path.")
    return v

SRC = Path(_require_env("SAFELABS_RESULTS_DIR", "directory holding the 26 include-list source files"))
STAGING = Path(_require_env("STAGING_DIR", "directory where redacted_<tag>/ and the reports are written"))
TAG = "v2"
if "--tag" in sys.argv:
    TAG = sys.argv[sys.argv.index("--tag") + 1]
OUT = STAGING / f"redacted_{TAG}"

STEMS = (
    ["asi300_asi01_full_20260915", "asi300_asi01_tier1_20260913"]
    + [f"asi300_asi{n:02d}_full_20260915" for n in range(2, 11)]
    + ["asi300_tier3_batch_20260915", "asi08_jailbreak_diagnostic_20260914"]
)
INCLUDE = [f"{s}.raw.jsonl" for s in STEMS] + [f"{s}.jsonl" for s in STEMS]
assert len(INCLUDE) == 26

REDACT_FIELDS = ("prompt", "output", "reasoning", "indicators", "error")
TRUNC_STOP = {"max_tokens", "length", "MAX_TOKENS"}

# ---- patterns: applied in this order; (name, compiled regex, placeholder) ----
_SYS_DIRS = (
    "etc|var|tmp|opt|usr|bin|sbin|root|proc|dev|srv|mnt|sys|lib|lib64|boot|"
    "private|Library|Applications|System|Volumes"
)
_PATH_TAIL = r"(?:/[^\s'\"`<>()\[\]{},;|]*)?"
PATTERNS = [
    ("private_key_block",
     re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S),
     "[REDACTED_PRIVATE_KEY_BLOCK]"),
    ("private_key_orphan_end",
     re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"),
     "[REDACTED_PRIVATE_KEY_BLOCK]"),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    ("github_token",
     re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
     "[REDACTED_GITHUB_TOKEN]"),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    ("jwt",
     re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
     "[REDACTED_JWT]"),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{16,}"), "Bearer [REDACTED_BEARER_TOKEN]"),
    ("api_key_other",
     re.compile(r"\b(?:sk-ant-[A-Za-z0-9_\-]{10,}|sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,}"
                r"|(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|hf_[A-Za-z0-9]{30,})"),
     "[REDACTED_API_KEY]"),
    ("url_credentials",  # scheme://user:pass@host -> scheme://[REDACTED_URL_CREDENTIALS]@host
     re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)([^\s:/@'\"<>]+:[^\s/'\"<>]+)@"),
     "[REDACTED_URL_CREDENTIALS]"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    ("home_path",  # segment after /home/ or /Users/ is redacted; rest of path kept
     re.compile(r"(?<![A-Za-z0-9:/.\-_])(/Users/|/home/)(?!\[REDACTED_USER\])([A-Za-z0-9._\-]+)"),
     "[REDACTED_USER]"),
    ("home_path",  # Windows: segment after C:\Users\
     re.compile(r"([A-Za-z]:\\Users\\)(?!\[REDACTED_USER\])([^\\\s'\"`<>]+)"),
     "[REDACTED_USER]"),
    ("root_home_segment",  # segment after /root/ (only when more path follows)
     re.compile(r"(?<![A-Za-z0-9:/.\-_])(/root/)(?!\[REDACTED_USER\])([^\s/'\"`<>()\[\]{},;|]+)"),
     "[REDACTED_USER]"),
    ("system_path",
     re.compile(r"(?<![A-Za-z0-9:/.\-_\[])/(?:" + _SYS_DIRS + r")(?![A-Za-z0-9_\-])(?!/\[REDACTED_USER\])" + _PATH_TAIL),
     "[REDACTED_SYSTEM_PATH]"),
    ("ipv4", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)"), "[REDACTED_IPV4]"),
]
# Path rule (v3): a system path is KEPT iff it starts with one of these segment
# prefixes and has at most ONE further segment; everything else is redacted.
KEEP_PREFIXES = [
    ["etc", "passwd"], ["etc", "shadow"], ["etc", "ssl"], ["etc", "nginx"],
    ["var", "log"], ["var", "lib"], ["dev", "null"], ["proc", "self", "environ"],
    ["usr", "bin"], ["bin", "bash"],
]
MAX_EXTRA_SEGMENTS = 1


def keep_match(segs: list[str]):
    """Return (prefix, extra_segments) if segs is a kept path, else None."""
    for P in KEEP_PREFIXES:
        if segs[:len(P)] == P and len(segs) - len(P) <= MAX_EXTRA_SEGMENTS:
            return P, len(segs) - len(P)
    return None


URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
TRAIL = ".:!?"

# patterns used only to scan NON-redacted fields for residual hits (report only)
SCAN_ONLY_FIELDS_EXCLUDE = set(REDACT_FIELDS)


def _apply_one(name: str, rx: re.Pattern, ph: str, text: str, counter: collections.Counter) -> str:
    def repl(m: re.Match) -> str:
        s = m.group(0)
        if name == "ipv4" and any(int(o) > 255 for o in s.split(".")):
            return s
        if name == "url_credentials":
            counter[name] += 1
            return m.group(1) + ph + "@"
        if name in ("home_path", "root_home_segment"):
            seg = m.group(2)
            core = seg.rstrip(TRAIL)
            if not core:
                return s
            counter[name] += 1
            return m.group(1) + ph + seg[len(core):]
        if name == "system_path":
            stripped = s.rstrip(TRAIL)
            tail = s[len(stripped):]
            segs = [x for x in stripped.split("/") if x]
            km = keep_match(segs)
            if km:
                P, extra = km
                counter["kept:/" + "/".join(P)] += 1
                counter[f"kept_extra:{extra}"] += 1
                return s
            counter[name] += 1
            return ph + tail
        counter[name] += 1
        return ph
    return rx.sub(repl, text)


def redact_text(text: str, counter: collections.Counter, keep_urls: bool = False) -> str:
    if not isinstance(text, str) or not text:
        return text
    if keep_urls:
        for name, rx, ph in PATTERNS:
            if name == "url_credentials":
                text = _apply_one(name, rx, ph, text, counter)
        out, pos = [], 0
        for m in URL_RE.finditer(text):
            out.append(redact_text(text[pos:m.start()], counter))
            out.append(m.group(0))
            pos = m.end()
        out.append(redact_text(text[pos:], counter))
        return "".join(out)
    for name, rx, ph in PATTERNS:
        text = _apply_one(name, rx, ph, text, counter)
    return text


def redact_value(v, counter, keep_urls=False):
    if isinstance(v, str):
        return redact_text(v, counter, keep_urls)
    if isinstance(v, list):
        return [redact_value(x, counter, keep_urls) for x in v]
    if isinstance(v, dict):
        return {k: redact_value(x, counter, keep_urls) for k, x in v.items()}
    return v


def response_status(row: dict) -> str:
    if row.get("error"):
        return "provider_error"
    sr = row.get("stop_reason")
    if sr == "refusal":
        return "provider_refusal"
    if sr in TRUNC_STOP:
        return "truncated"
    if not (row.get("output") or "").strip():
        return "empty"
    return "ok"


def redact_row(row: dict, per_field: dict) -> dict:
    """v5: drop `output`; add output_sha256 / output_chars computed from the ORIGINAL output."""
    status = response_status(row)  # from ORIGINAL fields, before redaction
    original_output = row.get("output") or ""
    new = {}
    for k, v in row.items():
        if k == "output":
            continue  # withheld
        if k in REDACT_FIELDS and v is not None:
            c = collections.Counter()
            new[k] = redact_value(v, c, keep_urls=(k == "error"))
            for p, n in c.items():
                per_field[k][p]["matches"] += n
                per_field[k][p]["rows"] += 1
        else:
            new[k] = v
    new["response_status"] = status
    new["empty_output"] = not original_output.strip()
    new["output_sha256"] = hashlib.sha256(original_output.encode("utf-8")).hexdigest()
    new["output_chars"] = len(original_output)
    return new


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(p: Path) -> list[dict]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main() -> None:
    missing = [f for f in INCLUDE if not (SRC / f).exists()]
    if missing:
        sys.exit(f"missing include files: {len(missing)}")
    before = {f: sha256(SRC / f) for f in INCLUDE}
    OUT.mkdir(parents=True, exist_ok=True)

    report = {"seed": SEED, "output_policy": "output field withheld; output_sha256 and output_chars added", "files": {}, "response_status_by_file": {}, "totals": {}}
    total_field = collections.defaultdict(lambda: collections.defaultdict(lambda: {"matches": 0, "rows": 0}))
    rows_by_file: dict[str, list[dict]] = {}
    idem_ok = True
    hit_rows: set[tuple[str, int]] = set()
    HIT_KINDS = {"private_key_block", "private_key_orphan_end", "aws_key", "github_token", "slack_token",
                 "jwt", "bearer_token", "api_key_other", "home_path", "root_home_segment"}

    for fname in INCLUDE:
        rows = load(SRC / fname)
        per_field = {f: collections.defaultdict(lambda: {"matches": 0, "rows": 0}) for f in REDACT_FIELDS}
        out_rows = []
        status_counts = collections.Counter()
        stem = fname.replace(".raw.jsonl", "").replace(".jsonl", "")
        for i, r in enumerate(rows, 1):
            # detect hit rows on the original (for the spot-check index)
            probe = {f: collections.Counter() for f in REDACT_FIELDS}
            for f in REDACT_FIELDS:
                if r.get(f) is not None:
                    redact_value(r[f], probe[f], keep_urls=(f == "error"))
            if any(k in HIT_KINDS for f in REDACT_FIELDS for k in probe[f]):
                hit_rows.add((stem, i))
            nr = redact_row(r, per_field)
            # idempotence: redacting the redacted row must change nothing
            again = {k: (redact_value(nr[k], collections.Counter(), keep_urls=(k == "error")) if k in REDACT_FIELDS and nr.get(k) is not None else nr[k]) for k in nr}
            if again != nr:
                idem_ok = False
            status_counts[nr["response_status"]] += 1
            out_rows.append(nr)
        with open(OUT / fname, "w", encoding="utf-8") as f:
            for nr in out_rows:
                f.write(json.dumps(nr) + "\n")
        rows_by_file[fname] = out_rows
        report["files"][fname] = {
            "rows_in": len(rows), "rows_out": len(out_rows),
            "redactions": {f: {p: dict(d) for p, d in per_field[f].items() if not p.startswith("kept")}
                           for f in REDACT_FIELDS if any(not p.startswith("kept") for p in per_field[f])},
            "kept_paths": {f: {p: dict(d) for p, d in per_field[f].items() if p.startswith("kept")}
                           for f in REDACT_FIELDS if any(p.startswith("kept") for p in per_field[f])},
        }
        report["response_status_by_file"][fname] = dict(status_counts)
        for f in REDACT_FIELDS:
            for p, d in per_field[f].items():
                total_field[f][p]["matches"] += d["matches"]
                total_field[f][p]["rows"] += d["rows"]

    report["totals"] = {f: {p: dict(d) for p, d in total_field[f].items() if not p.startswith("kept")}
                        for f in REDACT_FIELDS if any(not p.startswith("kept") for p in total_field[f])}
    report["kept_paths_totals"] = {f: {p: dict(d) for p, d in total_field[f].items() if p.startswith("kept")}
                                   for f in REDACT_FIELDS if any(p.startswith("kept") for p in total_field[f])}
    report["path_rule"] = {
        "keep_prefixes": ["/" + "/".join(P) for P in KEEP_PREFIXES],
        "max_extra_segments_after_prefix": MAX_EXTRA_SEGMENTS,
        "home_rule": "segment after /home/, /Users/, /root/ (when more path follows) and C:\\Users\\ replaced with [REDACTED_USER]; remainder of path kept",
        "everything_else": "whole path replaced with [REDACTED_SYSTEM_PATH]",
    }

    # ---- verification rescan of the OUTPUT (must be zero, except URLs in error) ----
    rescan = collections.defaultdict(collections.Counter)
    for fname, rows in rows_by_file.items():
        for r in rows:
            for f in REDACT_FIELDS:
                if r.get(f) is None:
                    continue
                c = collections.Counter()
                redact_value(r[f], c, keep_urls=(f == "error"))
                for p, n in c.items():
                    if not p.startswith("kept"):
                        rescan[f][p] += n
    report["verification_rescan_residual_hits"] = {f: dict(c) for f, c in rescan.items()} or "none"
    report["idempotence"] = {"redact_of_redacted_unchanged": idem_ok}

    # ---- residual scan of fields we did NOT redact (report only) ----
    resid = collections.defaultdict(collections.Counter)
    for fname, rows in rows_by_file.items():
        for r in rows:
            for k, v in r.items():
                if k in SCAN_ONLY_FIELDS_EXCLUDE or k in ("response_status", "empty_output", "output_sha256", "output_chars") or not isinstance(v, (str, list, dict)):
                    continue
                c = collections.Counter()
                redact_value(v, c)
                for p, n in c.items():
                    if not p.startswith("kept"):
                        resid[k][p] += n
    report["unredacted_field_hits"] = {k: dict(c) for k, c in resid.items()} or "none"

    # ---- independent path audit of the OUTPUT ----
    aud = collections.Counter()
    sys_rx = re.compile(r"(?<![A-Za-z0-9:/.\-_\[])/(?:" + _SYS_DIRS + r")(?![A-Za-z0-9_\-])(?!/\[REDACTED_USER\])" + _PATH_TAIL)
    home_rx = re.compile(r"(?<![A-Za-z0-9:/.\-_])(?:/Users/|/home/|/root/)([^\s/'\"`<>()\[\]{},;|]+)")
    win_rx = re.compile(r"[A-Za-z]:\\Users\\([^\\\s'\"`<>]+)")

    def audit_text(t: str) -> None:
        for m in sys_rx.finditer(t):
            segs = [x for x in m.group(0).rstrip(TRAIL).split("/") if x]
            pref = [P for P in KEEP_PREFIXES if segs[:len(P)] == P]
            if not pref:
                aud["offending_system_paths"] += 1
            elif len(segs) - len(pref[0]) > MAX_EXTRA_SEGMENTS:
                aud["kept_with_gt1_extra_segment"] += 1
            else:
                aud["kept_paths_present"] += 1
        for m in list(home_rx.finditer(t)) + list(win_rx.finditer(t)):
            if m.group(1).rstrip(TRAIL) and not m.group(1).startswith("[REDACTED_USER]"):
                aud["offending_home_segments"] += 1

    def audit_val(v, keep_urls=False):
        if isinstance(v, str):
            if keep_urls:
                for seg in URL_RE.split(v):
                    audit_text(seg)
            else:
                audit_text(v)
        elif isinstance(v, list):
            for x in v:
                audit_val(x, keep_urls)

    for rows in rows_by_file.values():
        for r in rows:
            for f in REDACT_FIELDS:
                if r.get(f) is not None:
                    audit_val(r[f], keep_urls=(f == "error"))
    report["path_audit"] = {k: aud.get(k, 0) for k in ("kept_paths_present", "kept_with_gt1_extra_segment",
                                                       "offending_system_paths", "offending_home_segments")}

    # ---- spot-check index ----
    rng = random.Random(SEED)
    scored = {s: rows_by_file[f"{s}.jsonl"] for s in STEMS}
    rawrows = {s: rows_by_file[f"{s}.raw.jsonl"] for s in STEMS}
    order_match = all(
        [(a["prompt_id"], a["model"]) for a in scored[s]] == [(a["prompt_id"], a["model"]) for a in rawrows[s]]
        for s in STEMS
    )
    universe = [(s, i + 1, r) for s in STEMS for i, r in enumerate(scored[s])]
    chosen: dict[tuple[str, int], list[str]] = {}

    def add(items, reason):
        for s, i, _ in items:
            chosen.setdefault((s, i), []).append(reason)

    def sample_new(pool, k):
        pool = [t for t in pool if (t[0], t[1]) not in chosen]
        return rng.sample(pool, min(k, len(pool)))

    add([(s, i, r) for s, i, r in universe if (s, i) in hit_rows], "secret_or_path_hit")
    asi08 = [t for t in universe if t[2].get("category") == "ASI08"]
    add([t for t in asi08 if t[2].get("verdict") in ("fail", "vulnerable")], "asi08_fail")
    add(sample_new([t for t in asi08 if t[2].get("verdict") == "uncertain"], 10), "asi08_uncertain")
    add(sample_new([t for t in universe if t[2]["response_status"] in ("provider_error", "empty", "provider_refusal")], 8),
        "non_response")
    add(sample_new([t for t in universe if t[2]["response_status"] == "truncated" and t[2].get("verdict") == "pass"], 5),
        "truncated_pass")
    # remainder: balance across (category, model)
    remaining = 50 - len(chosen)
    counts = collections.Counter((r.get("category"), r.get("model")) for s, i, r in universe if (s, i) in chosen)
    pool = [t for t in universe if (t[0], t[1]) not in chosen]
    rng.shuffle(pool)
    while remaining > 0 and pool:
        pool.sort(key=lambda t: counts[(t[2].get("category"), t[2].get("model"))])
        best = counts[(pool[0][2].get("category"), pool[0][2].get("model"))]
        cand = [t for t in pool if counts[(t[2].get("category"), t[2].get("model"))] == best]
        t = cand[0]
        pool.remove(t)
        chosen.setdefault((t[0], t[1]), []).append("random_balanced")
        counts[(t[2].get("category"), t[2].get("model"))] += 1
        remaining -= 1
    entries = [{"file": f"{s}.jsonl", "raw_file": f"{s}.raw.jsonl", "row": i, "reasons": sorted(set(rs))}
               for (s, i), rs in sorted(chosen.items())]
    idx = {"seed": SEED, "total": len(entries), "row_order_matches_raw_and_scored": order_match,
           "row_is_1_based_line_number": True,
           "reason_counts": dict(collections.Counter(r for e in entries for r in e["reasons"])),
           "entries": entries}
    (STAGING / f"spot_check_index_{TAG}.json").write_text(json.dumps(idx, indent=2) + "\n")

    after = {f: sha256(SRC / f) for f in INCLUDE}
    report["source_sha256_match_before_after"] = before == after
    (STAGING / f"source_sha256_{TAG}.json").write_text(json.dumps({"before": before, "after": after, "match": before == after}, indent=2) + "\n")
    (STAGING / f"redaction_report_{TAG}.json").write_text(json.dumps(report, indent=2) + "\n")

    print("files written:", len(INCLUDE), "| source sha256 unchanged:", before == after,
          "| idempotent:", idem_ok, "| spot-check rows:", len(entries), "| order match:", order_match)
    for f in REDACT_FIELDS:
        print(f, {p: d["matches"] for p, d in total_field[f].items()} or "no redactions")


if __name__ == "__main__":
    main()
