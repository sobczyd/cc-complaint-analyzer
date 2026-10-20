# CLI reference

This covers the main `python -m complaint_analyzer` entry point: every flag,
harness-backed runs, exit codes, and what a run writes to disk. For the
`workflows.*` CLIs (`salesforce_export`, `report_merge`, `custom_fetch`), run
each with `--help`, or use the matching skill in
[`.github/skills/`](../.github/skills/) — see the
[README](../README.md#skills) for which skill does what.

## Running

```powershell
Copy-Item config\rca.example.yaml config\rca.yaml
# edit config\rca.yaml to point at your workbook
.\.venv\Scripts\python.exe -m complaint_analyzer --config config\rca.yaml
```

Once installed, the `complaint-analyzer` console script does the same thing.
This is API mode; `--backend api` is optional because it is the default.

| Option | Effect |
|---|---|
| `-c`, `--config` | Path to the YAML configuration. Default `config/rca.yaml`. |
| `--run-id` | Name for this run's output directory. Default is a UTC timestamp. |
| `--limit` | Override `dataset.limit`. `0` lifts the limit entirely. Negative values are rejected. |
| `--dry-run` | Select records and render prompts without calling the model or needing credentials. |
| `--no-echo` | Write `run.log` without mirroring it to stdout. |
| `--env-file` | Path to the `.env` holding credentials. Default `./.env`. |
| `--backend` | Completion source: `api` (default) or `harness`. |
| `--prepare` | Export requests for a new harness-backed run. |
| `--finalize` | Validate all responses and finish an existing harness-backed run. |
| `--check` | Validate a prepared harness exchange without writing final artifacts. |
| `--batch-size` | Records per persisted worker assignment. Default `10`. |
| `--publish-response` | Validate and atomically publish one worker candidate response. |
| `--assignment-id` | Assignment that owns a `--publish-response` candidate. |
| `--harness-model` | Stable model/provenance name for harness requests. Default `copilot-harness`. |
| `--version` | Print the version and exit. |

Start with `--dry-run` to confirm your filters select the rows you expect.

## Harness-backed runs

Harness mode uses this VS Code Copilot session instead of an LLM API key. It is an
auditable file exchange, not a programmatic Copilot API: preparation exports the exact
requests, the session writes response files, and finalization imports them.

### Workspace batch workflow

Use the workspace `/copilot-batch-run` skill for a single-invocation, resumable
Copilot workflow. It works for any registered prompt — the prompt comes from the
config's `analysis.name` and `analysis.version`. It defaults to 100 selected records
and creates one isolated worker assignment for each group of 10. For example:

```text
/copilot-batch-run rca-100-records
```

The skill prepares the exchange, delegates only incomplete persisted assignments to
the restricted `Batch Worker` agent, checks every response, retries only assignments
with missing or invalid responses, and finalizes one combined run. The config, total,
and batch size are configurable:

```text
/copilot-batch-run rca-sample --limit 20 --batch-size 5
/copilot-batch-run summaries-001 --config config\case_summary.yaml
```

This workflow requires a VS Code Copilot environment that permits agent delegation.
The Python application never authenticates to or invokes Copilot. If delegation is
unavailable, the skill stops explicitly instead of analyzing all records in the parent
context.

Assignments are deterministic and persisted in `exchange/assignments.json`. Workers
publish through the CLI, which enforces assignment ownership, validates the response
schema, and atomically creates the final response file. Valid responses survive an
interrupted or partially failed workflow.

Prepare a named run:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config config\rca.yaml `
  --backend harness `
  --prepare `
  --limit 100 `
  --batch-size 10 `
  --run-id rca-harness-001
```

No LLM environment variables are read in this mode. Ask the Copilot session to process
the requests in `data/runs/rca-harness-001/exchange/requests/` and write responses to
the adjacent `responses/` directory. Then finalize the same run:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config config\rca.yaml `
  --backend harness `
  --finalize `
  --limit 100 `
  --run-id rca-harness-001
```

Finalization is all-or-nothing. Before writing `results.jsonl` or the workbook, it
requires one schema-valid response for every prepared request. It also rebuilds the
current requests and checks their fingerprints, source rows, record IDs, model
identity, and persisted assignments. Changes to the workbook, selection, prompt,
generation settings, effective `--limit`, or
`--harness-model` therefore require a new prepared run.

Use the same `--limit` value for preparation, checking, and finalization. An explicit
`--limit 0` means unlimited. The effective value is saved in the exchange manifest and
the final run manifest.

Check progress without creating final artifacts:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer `
  --config config\rca.yaml `
  --backend harness `
  --check `
  --limit 100 `
  --run-id rca-harness-001 `
  --no-echo
```

The JSON result identifies missing or invalid records and the exact assignments that
need another worker. If finalization is interrupted before the completion manifest is
published, rerun the same finalization command. It retains the exchange and valid
responses, removes only known partial final artifacts, and rebuilds them.

Each response is a versioned JSON object:

```json
{
  "format_version": 1,
  "record_id": "01190077",
  "fingerprint": "<copied from the matching request>",
  "model": "copilot-harness",
  "content": {
    "symptom": "...",
    "restoration_action": "...",
    "documented_cause": null,
    "hypothesis": "...",
    "cause_status": "hypothesized",
    "evidence": [],
    "missing_evidence": ["..."],
    "needs_review": true
  }
}
```

Use the same `--harness-model` value for preparation and finalization. The value is
provenance and fingerprint metadata; it does not select a model inside the Copilot
session. API and harness requests consequently keep separate cache identities.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Every record was analyzed. |
| `1` | The run finished, but at least one record failed. |
| `2` | Configuration, credentials, or input data were unusable; nothing ran. |
| `130` | Interrupted. |

A selection that matches no rows is not an error: the run logs `selection.empty` and
exits `0`, writing only `run.log`. Use `--dry-run` first if you are unsure whether your
filters match anything.

`--run-id` is sanitized for use as a directory name — anything outside
`A-Za-z0-9._-` becomes `-` — so the directory may not match exactly what you passed.

## What a run writes

```text
data/runs/<run-id>/
  manifest.json      configuration, counts, token totals, cache statistics
  results.jsonl      one line per record, written as each completes
  run.log            the human-readable timeline
  analyzed.xlsx      the output workbook
  calls/
    <analysis>-<version>/
      <utc-timestamp>_<record-id>-a<attempt>/
        request.json     exactly what was sent, minus credentials
        response.json    exactly what came back
        metadata.json    timings, token usage, outcome
        process.log      that attempt's log
  exchange/              harness backend only
    manifest.json        prepared record set and fingerprints
    assignments.json     deterministic, non-overlapping worker assignments
    requests/
      <record-id>.json   exact request exported during preparation
    candidates/
      <assignment-id>/   temporary worker candidates, never final responses
    responses/
      <record-id>.json   response supplied by the harness
```

In `manifest.json`, `results.prompt_tokens`, `completion_tokens`, and `total_tokens`
count only what this run actually spent — a record answered from the cache contributes
nothing. The matching `reused_*` fields report the token counts recorded against the
replies that were reused, kept for provenance rather than cost.

Every attempt gets its own directory, so a record that succeeded on its third try leaves
all three behind. A failed attempt has no `response.json`; the other three files are
always written. A record answered from the cache makes no call, so it leaves no call
directory at all.

Harness responses do not invent token counts, so their prompt and completion token
fields are `null` and their manifest token totals are zero.

Worker assignments, Copilot interactions, and record-level call folders are different
counts. A 100-record run with batch size 10 has 10 persisted worker assignments and
100 record-level call folders after finalization. The harness does not measure Copilot
premium requests or internal model inference calls.

### `analyzed.xlsx`

Each analyzed row carries all of its original workbook columns, then the analysis result
columns, then:

| Column | Meaning |
|---|---|
| `analysis_status` | `ok`, `flagged` (validator raised concerns), or `failed`. |
| `analysis_issues` | What the validators objected to. |
| `analysis_error` | Why the record failed, when it did. |

Failed records still get a row, so the output always lines up with the selection.

Every cell is written as text. A value beginning with `=` — whether it came from your
workbook or from the model — is stored literally and never becomes a live Excel formula.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite uses a generated fixture workbook and a scripted fake transport, so it never
touches the network.
