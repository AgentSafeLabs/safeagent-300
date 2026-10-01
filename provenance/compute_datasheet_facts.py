#!/usr/bin/env python
# PORTABLE COPY of compute_datasheet_facts.py (no hard-coded machine paths; computations unchanged).
# What it does: recomputes every figure the SafeAgent-300 datasheet cites from the source result files and the
#   prompt library, and writes datasheet_v1_facts.json (counts only; no row text).
# Required inputs (environment variables; no defaults):
#   SAFELABS_EVAL_DIR     root of the safelabs-eval checkout (for the prompt library and detectors)
#   SAFELABS_RESULTS_DIR  directory holding the 26 include-list source files
# Optional: OUTPUT_DIR    where datasheet_v1_facts.json is written (default: the folder containing this script)
# The original raw results (safelabs-eval/results/*.raw.jsonl and the scored siblings) are NOT public.
# This script documents how the released files were built; outsiders cannot re-run it without them.
"""Recompute every figure the SafeAgent-300 datasheet (datasheet_v1.md) cites, from the
SOURCE files (read-only) and the prompt library. Writes datasheet_v1_facts.json next to
this script; prints counts only, never prompt/output/reasoning/error text.

Run: python compute_datasheet_facts.py   (environment variables: see the header comment)
Datasheet tags of the form [V: key.path] refer to keys in the JSON this script writes.
"""
from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

import os as _os


def _require_env(name, what):
    """Return the value of environment variable `name`, or stop with a clear message."""
    v = _os.environ.get(name)
    if not v:
        raise SystemExit(f"error: environment variable {name} is not set ({what}). "
                         f"See the header comment of this script; there is deliberately no default path.")
    return v

EVAL = Path(_require_env("SAFELABS_EVAL_DIR", "root of the safelabs-eval checkout"))
SRC = Path(_require_env("SAFELABS_RESULTS_DIR", "directory holding the 26 include-list source files"))
sys.path.insert(0, str(EVAL))
from safelabs.prompts.library import load_library  # noqa: E402

STEMS = (
    ["asi300_asi01_full_20260915", "asi300_asi01_tier1_20260913"]
    + [f"asi300_asi{n:02d}_full_20260915" for n in range(2, 11)]
    + ["asi300_tier3_batch_20260915", "asi08_jailbreak_diagnostic_20260914"]
)
TRUNC = {"max_tokens", "length", "MAX_TOKENS"}
MODELS_ORDER = ["claude-opus-4-8", "claude-haiku-4-5-20251001", "gpt-5.5", "gpt-5.4-nano",
                "gemini-3.5-flash", "gemini-3.1-flash-lite"]


def load(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def status(r):
    if r.get("error"):
        return "provider_error"
    if r.get("stop_reason") == "refusal":
        return "provider_refusal"
    if r.get("stop_reason") in TRUNC:
        return "truncated"
    if not (r.get("output") or "").strip():
        return "empty"
    return "ok"


facts: dict = {}

# ---------------- library ----------------
lib = load_library()
E = lib.entries
cat = lambda e: getattr(e.category, "value", e.category)
tier = lambda e: getattr(e.difficulty_tier, "value", e.difficulty_tier)
sev = lambda e: getattr(getattr(e, "severity", None), "value", getattr(e, "severity", None))
cells = collections.Counter((cat(e), tier(e)) for e in E)
facts["library"] = {
    "content_version": lib.version, "schema_version": lib.schema_version, "total": len(E),
    "per_category": dict(sorted(collections.Counter(cat(e) for e in E).items())),
    "per_category_tier_cells": {"n_cells": len(cells), "min": min(cells.values()), "max": max(cells.values())},
    "per_tier": dict(sorted(collections.Counter(tier(e) for e in E).items())),
    "provenance": dict(collections.Counter(str(getattr(e.provenance, "value", e.provenance)) for e in E)),
    "severity_field_present_on_entry": hasattr(E[0], "severity"),
}
tier_of = {e.id: tier(e) for e in E}

# ---------------- scored corpus ----------------
raw = {s: load(SRC / f"{s}.raw.jsonl") for s in STEMS}
sc = {s: load(SRC / f"{s}.jsonl") for s in STEMS}
facts["files"] = {
    "raw_files": len(raw), "scored_files": len(sc),
    "rows_raw_main_12": sum(len(raw[s]) for s in STEMS if not s.startswith("asi08_")),
    "rows_diagnostic": len(raw["asi08_jailbreak_diagnostic_20260914"]),
    "rows_total_raw": sum(len(v) for v in raw.values()), "rows_total_scored": sum(len(v) for v in sc.values()),
    "per_file_rows": {s: len(raw[s]) for s in STEMS},
}
rows = [(s, i, r, sc[s][i - 1]) for s in STEMS for i, r in enumerate(raw[s], 1)]
assert all((a["prompt_id"], a["model"]) == (b["prompt_id"], b["model"]) for _, _, a, b in rows)
facts["files"]["distinct_prompt_ids_total"] = len({r["prompt_id"] for _, _, r, _ in rows})
facts["files"]["distinct_models"] = sorted({r["model"] for _, _, r, _ in rows})
facts["files"]["unique_prompt_model_pairs"] = len({(r["prompt_id"], r["model"]) for _, _, r, _ in rows})
facts["files"]["prompt_ids_in_library"] = all(r["prompt_id"] in tier_of for _, _, r, _ in rows)
facts["files"]["missing_from_main_12_files"] = sorted(
    {e.id for e in E} - {r["prompt_id"] for s, _, r, _ in rows if not s.startswith("asi08_")})

per_model = {m: collections.Counter() for m in MODELS_ORDER}
for s, i, r, x in rows:
    per_model[r["model"]][x["verdict"]] += 1
facts["per_model_verdicts"] = {m: dict(per_model[m], total=sum(per_model[m].values())) for m in MODELS_ORDER}

# tier x verdict (Section 2.6 verification)
tv = collections.defaultdict(collections.Counter)
for s, i, r, x in rows:
    tv[tier_of[r["prompt_id"]]][x["verdict"]] += 1
facts["tier_verdicts"] = {t: dict(v, total=sum(v.values())) for t, v in sorted(tv.items())}

# per-category uncertain (Section 2.7 cross-check)
cu = collections.Counter(); cv = collections.defaultdict(collections.Counter)
for s, i, r, x in rows:
    cv[r["category"]][x["verdict"]] += 1
facts["category_verdicts"] = {c: dict(v) for c, v in sorted(cv.items())}

# response status and pass-rate variants
by_status = collections.defaultdict(collections.Counter)
nonresp = collections.defaultdict(collections.Counter)
pr = {m: collections.Counter() for m in MODELS_ORDER}
trunc_pass = collections.Counter(); trunc_pass_cat = collections.Counter()
for s, i, r, x in rows:
    m = r["model"]; st = status(r); empty = not (r.get("output") or "").strip()
    by_status[m][st] += 1
    if empty: nonresp[m]["empty_output_true"] += 1
    if empty and st == "truncated": nonresp[m]["truncated_and_empty"] += 1
    if empty and st == "empty": nonresp[m]["empty_only"] += 1
    pass_ = x["verdict"] == "pass"
    c = pr[m]; c["n"] += 1; c["pass"] += pass_
    excluded = st in ("provider_error", "provider_refusal") or empty
    if not excluded:
        c["k1"] += 1; c["k1p"] += pass_
        if st != "truncated": c["k2"] += 1; c["k2p"] += pass_
    if st == "truncated":
        c["truncated_rows"] += 1
        if pass_: trunc_pass[m] += 1; trunc_pass_cat[r["category"]] += 1
facts["response_status_by_model"] = {m: dict(by_status[m]) for m in MODELS_ORDER}
facts["response_status_total"] = dict(sum((by_status[m] for m in MODELS_ORDER), collections.Counter()))
facts["empty_output_by_model"] = {m: dict(nonresp[m]) for m in MODELS_ORDER}
facts["empty_output_total"] = sum(nonresp[m]["empty_output_true"] for m in MODELS_ORDER)
facts["pass_rate_variants"] = {
    m: {"as_is": [pr[m]["pass"], pr[m]["n"]], "excl_nonresponse": [pr[m]["k1p"], pr[m]["k1"]],
        "excl_nonresponse_and_truncated": [pr[m]["k2p"], pr[m]["k2"]]} for m in MODELS_ORDER}
facts["truncated_rows_scored_pass"] = {"total": sum(trunc_pass.values()), "by_model": dict(trunc_pass),
                                       "by_category": dict(trunc_pass_cat)}
facts["excluded_rows_scored_pass"] = sum(
    1 for s, i, r, x in rows if (status(r) in ("provider_error", "provider_refusal") or not (r.get("output") or "").strip())
    and x["verdict"] == "pass")
facts["nonresponse_verdicts"] = dict(collections.Counter(
    (x["verdict"], x["confidence"], x["attack_success_weight"]) .__repr__() for s, i, r, x in rows
    if status(r) in ("provider_error", "provider_refusal") or not (r.get("output") or "").strip()))
facts["stop_reason_counts_by_file"] = {
    s: dict(collections.Counter(str(r.get("stop_reason")) for r in raw[s])) if any("stop_reason" in r for r in raw[s]) else "field absent"
    for s in STEMS}

# provider errors (7)
errs = [(s, i, r) for s, i, r, x in rows if r.get("error")]
def _norm(e): return e if isinstance(e, str) else json.dumps(e)
facts["provider_errors"] = {
    "count": len(errs), "models": dict(collections.Counter(r["model"] for _, _, r in errs)),
    "rows": [{"file": s, "row": i, "prompt_id": r["prompt_id"], "model": r["model"]} for s, i, r in errs],
    "distinct_error_strings": len({hashlib.sha256(_norm(r["error"]).encode()).hexdigest() for _, _, r in errs}),
    "all_http_400": all(_norm(r["error"]).startswith("Error code: 400") for _, _, r in errs),
    "all_mention_cybersecurity_flag": all("cybersecurity" in _norm(r["error"]).lower() for _, _, r in errs),
    "all_scored_uncertain_0.5_0.25": all(
        (x["verdict"], x["confidence"], x["attack_success_weight"]) == ("uncertain", 0.5, 0.25)
        for s, i, r, x in rows if r.get("error")),
    "all_output_empty": all(not (r.get("output") or "").strip() for _, _, r in errs),
    "category_counts": dict(collections.Counter(r["category"] for _, _, r in errs)),
}

# ASI08 diagnostic
diag = raw["asi08_jailbreak_diagnostic_20260914"]
facts["asi08_diagnostic"] = {
    "rows": len(diag), "prompt_ids": sorted({r["prompt_id"] for r in diag}),
    "models": sorted({r["model"] for r in diag}),
    "verdicts": dict(collections.Counter(x["verdict"] for x in sc["asi08_jailbreak_diagnostic_20260914"])),
    "prompt_ids_absent_from_asi08_full": sorted(
        {r["prompt_id"] for r in diag} - {r["prompt_id"] for r in raw["asi300_asi08_full_20260915"]}),
    "asi08_full_rows": len(raw["asi300_asi08_full_20260915"]),
}
a8 = [x for s, i, r, x in rows if r["category"] == "ASI08"]
facts["asi08_all_scored"] = {"rows": len(a8), "verdicts": dict(collections.Counter(x["verdict"] for x in a8))}

# gemini function-call finding (Section 2.5a)
fc = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for s, i, r, x in rows:
    m = r["model"]
    ntp = r.get("non_text_parts") or []
    clean = "function_call" in (ntp if isinstance(ntp, list) else [str(ntp)])
    mal = r.get("stop_reason") == "MALFORMED_FUNCTION_CALL"
    fc[m][r["category"]]["rows"] += 1
    if clean: fc[m][r["category"]]["clean_function_call"] += 1
    if mal: fc[m][r["category"]]["malformed_function_call"] += 1
facts["function_call_signals"] = {
    m: {"rows": sum(c["rows"] for c in fc[m].values()),
        "clean": sum(c["clean_function_call"] for c in fc[m].values()),
        "malformed": sum(c["malformed_function_call"] for c in fc[m].values()),
        "by_category": {k: dict(v) for k, v in sorted(fc[m].items()) if v["clean_function_call"] or v["malformed_function_call"]}}
    for m in MODELS_ORDER}
g = "gemini-3.1-flash-lite"
facts["function_call_signals"][g]["category_denominators"] = {k: v["rows"] for k, v in sorted(fc[g].items())}
facts["function_call_signals"][g]["non_text_parts_fields_present_in_files"] = sorted(
    s for s in STEMS if any("non_text_parts" in r for r in raw[s]))

# gpt-5.5 truncated-empty usage
te = [r for s, i, r, x in rows if r["model"] == "gpt-5.5" and status(r) == "truncated" and not (r.get("output") or "").strip()]
facts["gpt55_truncated_empty"] = {
    "rows": len(te), "stop_reasons": dict(collections.Counter(r.get("stop_reason") for r in te)),
    "completion_tokens": sorted({(r.get("usage") or {}).get("completion_tokens") for r in te}),
    "usage_keys": sorted({k for r in te for k in (r.get("usage") or {})}),
}


# detector behaviour on empty / whitespace-only text (Section 2.4)
import asyncio, importlib, inspect, pkgutil
import safelabs.scoring.detectors as _d
from safelabs.scoring.base import BaseDetector
det = {}
for mi in pkgutil.iter_modules(_d.__path__):
    mod = importlib.import_module(f"safelabs.scoring.detectors.{mi.name}")
    for n, c in inspect.getmembers(mod, inspect.isclass):
        if issubclass(c, BaseDetector) and c is not BaseDetector and c.__module__ == mod.__name__:
            det[n] = {lab: [(lambda r: (r.verdict.value, r.confidence))(asyncio.run(c().detect("test prompt", t, {})))][0]
                      for lab, t in (("empty", ""), ("whitespace", "  \n"))}
facts["detectors_on_empty_text"] = det
import safelabs
facts["package_version_now"] = safelabs.__version__
facts["scored_file_mtime_vs_detector_files"] = {
    "scored_files_mtime": sorted({__import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime((SRC / f"{s}.jsonl").stat().st_mtime)) for s in STEMS}),
    "detector_files_mtime": {p.name: __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(p.stat().st_mtime))
                             for p in sorted((EVAL / "safelabs" / "scoring" / "detectors").glob("*.py"))},
}

(Path(_os.environ.get("OUTPUT_DIR") or Path(__file__).resolve().parent) / "datasheet_v1_facts.json").write_text(json.dumps(facts, indent=2) + "\n")
print("facts written; keys:", list(facts))
