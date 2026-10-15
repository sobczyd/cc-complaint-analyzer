---
name: rca-harness-batch
description: "Prepare, fan out, resume, validate, and finalize RCA harness runs with isolated GitHub Copilot workers. Use for processing complaint records in configurable batches, including the default 100 records in groups of 10."
argument-hint: "run-id [--config config\\rca.yaml] [--limit 100] [--batch-size 10]"
user-invocable: true
disable-model-invocation: false
---

# RCA Harness Batch

Run an auditable harness analysis using isolated Copilot workers. The Python
application never calls Copilot; this skill owns worker delegation while the
application owns deterministic assignments, validation, and final artifacts.

## Defaults

- Config: `config\rca.yaml`
- Limit: `100`
- Batch size: `10`
- Harness model label: `copilot-harness`
- Maximum worker rounds: `2`

Require a run ID. Resolve all paths from the repository root.

## Procedure

### 1. Read domain instructions

Read `C:\Users\sobczyd\.copilot\nursecall-AGENTS.md`.

### 2. Prepare or resume

If the run directory does not exist, prepare it:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config <config> `
  --backend harness `
  --prepare `
  --limit <limit> `
  --batch-size <batch-size> `
  --run-id <run-id> `
  --harness-model <model>
```

If it exists:

- if final `manifest.json` exists, report that the run is complete and stop;
- otherwise resume the prepared exchange without recreating it.

Read `exchange\manifest.json` and `exchange\assignments.json`. Use the manifest's
`config_path`, `effective_limit`, and `model` for every later command. Never
guess or silently replace those values.

Verify:

- assignment and record counts agree;
- every record is assigned exactly once;
- request and response filenames are safe basenames;
- assignment memberships do not overlap.

### 3. Check current response status

Run:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config <prepared-config> `
  --backend harness `
  --check `
  --limit <prepared-limit> `
  --run-id <run-id> `
  --harness-model <prepared-model> `
  --no-echo
```

Use `--limit 0` when `effective_limit` is null. Parse the JSON output. If it is
ready, skip directly to finalization.

### 4. Delegate incomplete assignments

Invoke the `RCA Harness Worker` agent once for each ID in
`incomplete_assignment_ids`. Give each worker:

- repository, config, run ID, assignment ID, and model;
- the exact request-file allowlist copied from `assignments.json`;
- the worker instructions to process only that assignment.

Launch independent assignments in parallel when the agent tool permits it.
Never ask one worker to process multiple assignments, and never let the parent
analyze records as a fallback. If worker delegation is unavailable, stop with
an explicit environment error.

### 5. Validate and retry narrowly

After all workers return, run the status command again.

- If ready, continue.
- If invalid, launch workers only for the reported incomplete assignment IDs.
- Allow at most two worker rounds total.
- After the second failed status check, stop and report every status error and
  invalid record ID. Keep valid responses for a later resume.

### 6. Finalize once

Run:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config <prepared-config> `
  --backend harness `
  --finalize `
  --limit <prepared-limit> `
  --run-id <run-id> `
  --harness-model <prepared-model>
```

Use `--limit 0` when `effective_limit` is null. Do not finalize individual
assignments.

### 7. Verify and report

Verify the final manifest, `results.jsonl`, workbook, and call directory. Report:

- prepared records and assignments;
- workers launched per round;
- responses reused and newly published;
- invalid or retried records;
- successful, flagged, and failed results;
- record-level call-folder count;
- final artifact paths.

State explicitly that worker and call-folder counts do not measure Copilot
premium requests or internal model inferences.

## Safety and recovery

- Never delete the exchange, valid responses, or run log.
- Never overwrite a completed run.
- Resume uses persisted assignments and reruns only incomplete assignments.
- Finalization is all-or-nothing with respect to response schema validation.
- If finalization was interrupted before its completion manifest, rerunning it
  safely rebuilds only the known partial final artifacts.
