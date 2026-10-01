# Provenance scripts

These scripts document how the release files were built. **The original raw results (`safelabs-eval/results/*.raw.jsonl` and
the scored siblings) are not public**, so the scripts **cannot be re-run by outsiders**; they are included so that the method
can be read and audited.

- `redact_safeagent300_v5.py` — produces the files in `redacted_v5/` from the raw/scored results: drops `output`, adds
  `output_sha256` and `output_chars`, redacts `prompt`, `reasoning`, `indicators` and `error`. Deterministic (seed 42).
- `compute_datasheet_facts.py` — recomputes the figures cited in the datasheet (`datasheet_v1_facts.json`).
- `rescore_snapshot.py` and `compute_historical_facts.py` — re-score the rows with older detector commits and merge the
  historical comparison into the facts file.

Each script reads its inputs from environment variables (see its header comment); none has a default path.
