# PORTABLE COPY of compute_historical_facts.py (no hard-coded machine paths; computations unchanged).
# What it does: merges historical-detector rescoring facts into datasheet_v1_facts.json under `historical_rescoring`,
#   from _snap_<commit>.json verdict tables, tier_map.json and the stored scored files. Counts only.
# Required inputs (environment variables; no defaults):
#   STAGING_DIR           directory holding _snap_<commit>.json, tier_map.json and datasheet_v1_facts.json
#   SAFELABS_RESULTS_DIR  directory holding the source result files
# Optional: OUTPUT_DIR    where the merged datasheet_v1_facts.json is written (default: STAGING_DIR, i.e. in place)
# The original raw results (safelabs-eval/results/*.raw.jsonl and the scored siblings) are NOT public.
# This script documents how the released files were built; outsiders cannot re-run it without them.
"""Merge historical-detector rescoring facts into datasheet_v1_facts.json under key
`historical_rescoring`. Inputs: _snap_<commit>.json (per-row verdicts produced by
rescore_snapshot.py under read-only `git archive` snapshots of older detector commits) and the
stored scored files. Counts only."""
import json, collections, random
from pathlib import Path
import os as _os


def _require_env(name, what):
    """Return the value of environment variable `name`, or stop with a clear message."""
    v = _os.environ.get(name)
    if not v:
        raise SystemExit(f"error: environment variable {name} is not set ({what}). "
                         f"See the header comment of this script; there is deliberately no default path.")
    return v

S = Path(_require_env("STAGING_DIR", "directory holding _snap_<commit>.json, tier_map.json and datasheet_v1_facts.json"))
R = Path(_require_env("SAFELABS_RESULTS_DIR", "directory holding the source result files"))
OUT_DIR = Path(_os.environ.get("OUTPUT_DIR") or S)
T = json.load(open(S / "tier_map.json"))
STEMS = (['asi300_asi01_full_20260915', 'asi300_asi01_tier1_20260913'] + [f'asi300_asi{n:02d}_full_20260915' for n in range(2, 11)]
         + ['asi300_tier3_batch_20260915', 'asi08_jailbreak_diagnostic_20260914'])
STATES = {"v0.5.0": "0df8e58", "v0.5.1": "3d39c2c", "v0.6.3": "764e30c", "v0.8.1": "15d7322", "v0.9.0": "baa5e06", "current(0.10.1)": "current"}
snap = {k: {(r["file"], r["row"]): r for r in json.load(open(S / f"_snap_{c}.json"))["rows"]} for k, c in STATES.items()}
stored = {}
raw = {}
for s in STEMS:
    for i, l in enumerate(open(R / f"{s}.jsonl"), 1):
        if l.strip(): stored[(s, i)] = json.loads(l)
    for i, l in enumerate(open(R / f"{s}.raw.jsonl"), 1):
        if l.strip(): raw[(s, i)] = json.loads(l)
V = ("pass", "uncertain", "fail", "vulnerable")
def per_model(rows):
    d = collections.defaultdict(collections.Counter)
    for r in rows.values(): d[r["model"]][r["verdict"]] += 1
    return {m: [d[m].get(k, 0) for k in V] for m in sorted(d)}
def per_tier(rows):
    d = collections.defaultdict(collections.Counter)
    for r in rows.values(): d[T[r["prompt_id"]]][r["verdict"]] += 1
    return {t: [d[t].get(k, 0) for k in V] for t in sorted(d)}
def transitions(a, b):
    c = collections.Counter(); cat = collections.Counter(); tier = collections.Counter()
    for k in a:
        if a[k]["verdict"] != b[k]["verdict"]:
            c[f'{a[k]["verdict"]}->{b[k]["verdict"]}'] += 1; cat[a[k]["category"]] += 1; tier[T[a[k]["prompt_id"]]] += 1
    return {"transitions": dict(c), "by_category": dict(sorted(cat.items())), "by_tier": dict(sorted(tier.items()))}
out = {"states": list(STATES), "per_model": {k: per_model(v) for k, v in snap.items()},
       "per_tier": {k: per_tier(v) for k, v in snap.items()}}
cur, s081, s063 = snap["current(0.10.1)"], snap["v0.8.1"], snap["v0.6.3"]
out["current_code_vs_stored_scored_files"] = {
    "rows": len(cur), "verdict_differs": sum(1 for k in cur if cur[k]["verdict"] != stored[k]["verdict"]),
    "confidence_differs": sum(1 for k in cur if abs(cur[k]["confidence"] - stored[k]["confidence"]) > 1e-9)}
idx = sorted(random.Random(42).sample(range(len(cur)), 100)); keys = list(cur)
out["current_code_vs_stored_sample100_seed42"] = {"n": 100, "verdict_differs": sum(1 for j in idx if cur[keys[j]]["verdict"] != stored[keys[j]]["verdict"]),
    "by_category_rows": dict(sorted(collections.Counter(cur[keys[j]]["category"] for j in idx).items()))}
out["draft_tables_reproduced"] = {
    "tier_v0.6.3": out["per_tier"]["v0.6.3"] == {"tier_1": [409, 177, 12, 2], "tier_2": [391, 203, 6, 0], "tier_3": [413, 185, 2, 0]},
    "tier_v0.8.1": out["per_tier"]["v0.8.1"] == {"tier_1": [409, 174, 15, 2], "tier_2": [391, 201, 8, 0], "tier_3": [413, 178, 9, 0]},
    "per_model_v0.6.3": out["per_model"]["v0.6.3"] == {"gpt-5.5": [217, 83, 0, 0], "claude-opus-4-8": [185, 114, 1, 0],
        "claude-haiku-4-5-20251001": [232, 64, 3, 1], "gpt-5.4-nano": [236, 60, 4, 0], "gemini-3.5-flash": [191, 103, 6, 0], "gemini-3.1-flash-lite": [152, 141, 6, 1]}}
out["transitions"] = {"v0.6.3->v0.8.1": transitions(s063, s081), "v0.8.1->v0.9.0": transitions(s081, snap["v0.9.0"]),
                      "v0.9.0->current": transitions(snap["v0.9.0"], cur), "v0.8.1->current": transitions(s081, cur)}
new_fv = sorted((s081[k]["prompt_id"], s081[k]["model"]) for k in s081
                if s081[k]["verdict"] in ("fail", "vulnerable") and s063[k]["verdict"] not in ("fail", "vulnerable"))
tiers = collections.Counter(T[p] for p, _ in new_fv)
out["v0.6.3_to_v0.8.1_new_fail_vuln_rows"] = {"count": len(new_fv), "by_category": dict(collections.Counter(p[:5] for p, _ in new_fv)),
    "by_tier": dict(tiers), "rows": [f"{p} x {m}" for p, m in new_fv]}
d16 = [k for k in s081 if s081[k]["verdict"] != cur[k]["verdict"]]
out["v0.8.1_to_current_changed_rows_by_tier"] = dict(collections.Counter(T[cur[k]["prompt_id"]] for k in d16))
def cnt(state, cat, ver="uncertain", nonempty=None):
    return sum(1 for k, r in snap[state].items() if r["category"] == cat and r["verdict"] == ver and (nonempty is None or bool((raw[k].get("output") or "").strip()) == nonempty))
out["uncertain_counts"] = {
    "ASI10_at_v0.5.0_all": cnt("v0.5.0", "ASI10"), "ASI10_at_v0.5.0_nonempty": cnt("v0.5.0", "ASI10", nonempty=True),
    "ASI06_at_v0.5.1_all": cnt("v0.5.1", "ASI06"), "ASI06_at_v0.5.1_nonempty": cnt("v0.5.1", "ASI06", nonempty=True),
    "ASI06_current": cnt("current(0.10.1)", "ASI06"), "ASI10_current": cnt("current(0.10.1)", "ASI10"),
    "other_category_pass_rows_at_v0.5.1": sum(1 for r in snap["v0.5.1"].values() if r["category"] != "ASI06" and r["verdict"] == "pass")}
fp = Path(S / "datasheet_v1_facts.json"); f = json.load(open(fp)); f["historical_rescoring"] = out
(OUT_DIR / fp.name).write_text(json.dumps(f, indent=2) + "\n")
print(json.dumps({k: out[k] for k in ("current_code_vs_stored_scored_files", "current_code_vs_stored_sample100_seed42", "draft_tables_reproduced", "transitions", "v0.8.1_to_current_changed_rows_by_tier", "uncertain_counts")}, indent=1)[:3000])
print(json.dumps(out["per_tier"]["current(0.10.1)"]), json.dumps(out["v0.6.3_to_v0.8.1_new_fail_vuln_rows"]["by_tier"]))
