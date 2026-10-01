# SafeAgent-300 — release README

**Status: Version 1.0.0.**

[![DOI](https://zenodo.org/badge/1400767767.svg)](https://doi.org/10.5281/zenodo.23092031)

## What this is

SafeAgent-300 is a scored set of adversarial prompts for evaluating whether AI agents and language models handle
attacks safely: **300 single-turn prompts** (prompt library 1.13.0) in
**10 categories** ASI01–ASI10 (30 per category; an OWASP-inspired category set, **not** OWASP's official
list), each run **once** against **6 models** — claude-haiku-4-5-20251001, claude-opus-4-8, gemini-3.1-flash-lite, gemini-3.5-flash, gpt-5.4-nano, gpt-5.5 — giving
**1,800 instances**, scored by a pattern-based detector suite (safelabs-eval 0.10.1, v0.10.0 detector
logic). The SafeAgent-300 preprint calls the categories SA01–SA10 (SA0N = ASI0N).

**The model responses are withheld.** Each row has `output_sha256` and `output_chars` in place of the `output` field.

## Files

13 raw and 13 scored files, one row per (prompt, model) pair, JSON Lines, UTF-8. A raw file and its scored
file have the same rows in the same order (join on row position, or on `prompt_id` + `model`). **All data files are in the `redacted_v5/` folder.**

| collection | rows | raw file | scored file |
|---|---|---|---|
| `asi08_jailbreak_diagnostic_20260914` | 12 | `asi08_jailbreak_diagnostic_20260914.raw.jsonl` | `asi08_jailbreak_diagnostic_20260914.jsonl` |
| `asi300_asi01_full_20260915` | 156 | `asi300_asi01_full_20260915.raw.jsonl` | `asi300_asi01_full_20260915.jsonl` |
| `asi300_asi01_tier1_20260913` | 24 | `asi300_asi01_tier1_20260913.raw.jsonl` | `asi300_asi01_tier1_20260913.jsonl` |
| `asi300_asi02_full_20260915` | 162 | `asi300_asi02_full_20260915.raw.jsonl` | `asi300_asi02_full_20260915.jsonl` |
| `asi300_asi03_full_20260915` | 162 | `asi300_asi03_full_20260915.raw.jsonl` | `asi300_asi03_full_20260915.jsonl` |
| `asi300_asi04_full_20260915` | 162 | `asi300_asi04_full_20260915.raw.jsonl` | `asi300_asi04_full_20260915.jsonl` |
| `asi300_asi05_full_20260915` | 162 | `asi300_asi05_full_20260915.raw.jsonl` | `asi300_asi05_full_20260915.jsonl` |
| `asi300_asi06_full_20260915` | 162 | `asi300_asi06_full_20260915.raw.jsonl` | `asi300_asi06_full_20260915.jsonl` |
| `asi300_asi07_full_20260915` | 162 | `asi300_asi07_full_20260915.raw.jsonl` | `asi300_asi07_full_20260915.jsonl` |
| `asi300_asi08_full_20260915` | 168 | `asi300_asi08_full_20260915.raw.jsonl` | `asi300_asi08_full_20260915.jsonl` |
| `asi300_asi09_full_20260915` | 162 | `asi300_asi09_full_20260915.raw.jsonl` | `asi300_asi09_full_20260915.jsonl` |
| `asi300_asi10_full_20260915` | 162 | `asi300_asi10_full_20260915.raw.jsonl` | `asi300_asi10_full_20260915.jsonl` |
| `asi300_tier3_batch_20260915` | 144 | `asi300_tier3_batch_20260915.raw.jsonl` | `asi300_tier3_batch_20260915.jsonl` |

The diagnostic file covers the two prompts (`ASI08-009`, `ASI08-011`) that are absent from the main ASI08 file. The 26
files total 3,600 rows (1,800 raw + 1,800 scored). `release_manifest_v5.json` lists each file's
SHA-256, size and row count, the detector provenance, the field definitions, and the files deliberately excluded.
`datasheet.md` is the datasheet. Also in the deposit: `LICENSE-DATA`, `CITATION.cff`, and `LICENSE-APACHE-2.0` (the Apache License 2.0 text; it applies to the prompts).

## Fields

| field | raw | scored | meaning |
|---|---|---|---|
| `prompt_id` | ✓ | ✓ | prompt identifier, e.g. `ASI03-014`; the prefix is the category |
| `category` | ✓ | ✓ | `ASI01`–`ASI10` |
| `model`, `provider` | ✓ | ✓ | model id and its provider (anthropic, openai, google) |
| `tier` | ✓ | ✓ | the **model's** cost/capability tier (`cheap` or `frontier`); **not** the prompt's difficulty tier (that is in the prompt library, joinable on `prompt_id`) |
| `prompt` | ✓ | ✓ | the prompt text, after redaction |
| `error` | ✓ | ✓ | provider error text if the call failed, else null (after redaction) |
| `usage`, `latency_ms`, `timestamp` | ✓ | ✓ | token counts (`prompt_tokens`, `completion_tokens`), latency in ms, call time |
| `stop_reason` | some | some | the provider's stop/finish reason; **absent from 4 files (336 rows)** |
| `non_text_parts` | some | some | non-text response parts (e.g. a function-call attempt); recorded only in some files |
| `verdict` | | ✓ | `pass`, `uncertain`, `fail` or `vulnerable` |
| `confidence` | | ✓ | detector confidence, 0–1 |
| `attack_success_weight` | | ✓ | 0.0 (pass), 0.25 (uncertain), 0.5 (fail), 1.0 (vulnerable) |
| `indicators` | | ✓ | short detector tags that fired |
| `reasoning` | | ✓ | the detector's explanation string (after redaction) |
| `eval_type` | | ✓ | which detector scored the row (`prompt_injection`, `jailbreak`, `scope_violation`, `data_leakage`, `hallucination`) |
| `response_status` | ✓ | ✓ | derived, first match wins: `provider_error` (non-empty `error`) → `provider_refusal` (`stop_reason` = `refusal`) → `truncated` (`stop_reason` in `max_tokens`, `length`, `MAX_TOKENS`) → `empty` (empty output) → `ok`. Counts: ok 1,708, truncated 62, empty 15, provider_refusal 8, provider_error 7 |
| `empty_output` | ✓ | ✓ | derived boolean: the ORIGINAL output was empty or whitespace-only (44 rows); independent of `response_status` |
| `output_sha256` | ✓ | ✓ | SHA-256 (hex) of the ORIGINAL unredacted output, UTF-8 encoded (all empty outputs share one hash) |
| `output_chars` | ✓ | ✓ | length in characters of the ORIGINAL output |

Reading notes: `uncertain` counts against a pass rate (pass rate = share of rows with verdict `pass`), so it is a strict lower bound.
All 6 models used one shared 1,000-token output cap and no reasoning setting; 62 rows are `truncated` and 44 have no
text, so cross-model pass rates are not like-for-like. Each pair was run once; there are no confidence intervals. Details: `datasheet.md`.

## Redaction

`prompt`, `reasoning`, `indicators` and `error` were redacted with typed placeholders (emails, IPv4 addresses, key blocks, API-key
shapes, credentials in URLs, home-directory usernames, most system paths); `output` is dropped. The source files were not modified (SHA-256 before
and after are in the manifest). Redaction is deterministic (seed 42).

## Withheld outputs and how to request them

The responses are withheld because a subset contains functional attack technique (see the SafeAgent-300 preprint, Section 7). They may be
provided on request to researchers **under a data-use agreement that restricts further redistribution**. Contact: `waqarjaved.com@gmail.com`;
terms: Raw model outputs are available on request, case by case, under a data-use agreement. A recipient can check a supplied output against this release: SHA-256 of the output (UTF-8) must equal the
row's `output_sha256`.

## Licenses (confirmed: prompts Apache-2.0; scores and derived fields CC BY 4.0; raw outputs withheld; data-use agreement on request)

- Prompts and library metadata (prompt text, `prompt_id`, `category`): Apache-2.0.
- Scores and derived fields (`verdict`, `confidence`, `attack_success_weight`, `indicators`, `reasoning`, `eval_type`, `response_status`,
  `empty_output`, `output_sha256`, `output_chars`) and release metadata: CC BY 4.0.
- Model outputs: withheld; not licensed here. Provider error text in `error` is distributed as recorded.
See `LICENSE-DATA`.

## Citation

Dataset: Waqar Javed (Safe Labs AI Inc.; ORCID https://orcid.org/0009-0003-1285-8901), *SafeAgent-300*, 1.0.0. DOI for this version (1.0.0): 10.5281/zenodo.23092032 (https://doi.org/10.5281/zenodo.23092032). DOI for all versions, always resolving to the latest: 10.5281/zenodo.23092031. See `CITATION.cff`. The dataset's DOI is
distinct from the DOIs of the related preprints (posted September 22, 2026; manuscripts under peer review): SafeAgent-300, 10.21203/rs.3.rs-11102288/v1;
ABC-Calibration, 10.21203/rs.3.rs-11102046/v1; AgentPort-Bench, 10.21203/rs.3.rs-11102299/v1.
The archived v1.0.0 Zenodo record contains the files as released; later commits to main add only the DOI information.

## Reading a file

```python
import json
rows = [json.loads(line) for line in open("asi300_asi03_full_20260915.jsonl", encoding="utf-8")]
print(rows[0]["prompt_id"], rows[0]["verdict"], rows[0]["response_status"], rows[0]["output_chars"])
```
