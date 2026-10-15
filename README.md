# cc-complaint-analyzer

Row-by-row LLM analysis of service-record workbooks, with saved call history, logging,
selection, and rate limiting.

Each selected row is sent to the model on its own, the reply is validated against a
schema and a set of analysis-specific checks, and everything — the request, the reply,
the timings, and the decision — is written to disk so the result can be audited later.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

Requires Python 3.12 or newer.

### Credentials

Credentials live in the environment, never in the config file.

```powershell
Copy-Item .env.example .env
```

| Variable | Meaning |
|---|---|
| `LLM_BASE_URL` | API base URL as documented by your provider. Usually ends in `/v1`, not `/chat/completions`. |
| `LLM_API_KEY` | Your API key. Redacted from every log line and never written to a run artifact. |
| `LLM_MODEL` | The model name to request. |

`.env` is gitignored. Do not commit it.

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

### Harness-backed runs

Harness mode uses this VS Code Copilot session instead of an LLM API key. It is an
auditable file exchange, not a programmatic Copilot API: preparation exports the exact
requests, the session writes response files, and finalization imports them.

#### Workspace batch workflow

Use the workspace `/rca-harness-batch` skill for a single-invocation, resumable
Copilot workflow. It defaults to 100 selected records and creates one isolated worker
assignment for each group of 10. For example:

```text
/rca-harness-batch rca-100-records
```

The skill prepares the exchange, delegates only incomplete persisted assignments to
the restricted `RCA Harness Worker`, checks every response, retries only assignments
with missing or invalid responses, and finalizes one combined run. The total and batch
size are configurable:

```text
/rca-harness-batch rca-sample --limit 20 --batch-size 5
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

### Exit codes

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

## Configuration

See [config/rca.example.yaml](./config/rca.example.yaml) for a commented example.
Unknown keys are rejected rather than ignored.

### `dataset`

| Key | Meaning |
|---|---|
| `path` | Path to the `.xlsx` workbook. |
| `sheet` | Sheet name to read. Row 1 is the header. |
| `id_field` | Column identifying each record. Rows with a blank or duplicate value are skipped and reported. |
| `fields` | The only columns sent to the model. |
| `filters` | A list of conditions that must **all** match. |
| `limit` | Maximum records to analyze, applied after filtering, keeping workbook order. `null` means no limit. |

Cells are read as values, not formulas. A formula cell comes through as the result Excel
last cached in the file, which is what you want for a workbook exported from Excel; a
workbook generated by a script that never opened in Excel has no cached values, so such
cells read as blank.

#### Filter operators

| Operator | Takes a value | Matches when |
|---|---|---|
| `eq` / `ne` | yes | The cell equals / does not equal the value. |
| `in` | a non-empty list | The cell equals any entry in the list. |
| `contains` | yes | The value appears somewhere in the cell. |
| `is_blank` / `not_blank` | no | The cell is empty, or contains only whitespace / is not. |
| `gt` / `gte` / `lt` / `lte` | yes | Ordered comparison, numeric when both sides look numeric, otherwise textual. A blank cell never matches. |

`eq`, `ne`, `in`, and `contains` ignore letter case and surrounding whitespace. Interior
whitespace is significant: `Clo  sed` does not equal `Clo sed`.

### `analysis`

| Key | Default | Meaning |
|---|---|---|
| `name` | `rca` | Which analysis to run. |
| `version` | `v1` | Which prompt version of that analysis to use. |
| `concurrency` | `3` | Records analyzed at once. |
| `max_output_tokens` | `800` | Ceiling on reply length. |
| `temperature` | `0` | Sampling temperature. |

### `rate_limits`

| Key | Default | Meaning |
|---|---|---|
| `rpm` | `null` | Requests per minute. `null` means no locally configured limit. |
| `tpm` | `null` | Tokens per minute. `null` means no locally configured limit. If a single request's estimate exceeds `tpm`, it is still sent — blocking forever would be worse — and a warning says the ceiling could not be honoured for it. |
| `max_attempts` | `4` | Total attempts per record. Only transient failures are retried. A server-supplied `Retry-After` is honoured in full — it is never shortened by the backoff cap — and concurrent waiters are spread slightly so they do not all retry in lockstep. |

### `cache`

| Key | Default | Meaning |
|---|---|---|
| `mode` | `"off"` | `"off"` always calls the model. `"reuse"` answers from a previous run when an identical request was already made. |

Quote `"off"` so the file says what it means: YAML reads an unquoted `off` as the
boolean `false`. That spelling is accepted anyway and still means `"off"`.

A request matches the cache on its fingerprint: the model, the messages, and the
generation parameters. Record identity, attempt number, and timestamps are excluded, so
re-running an unchanged configuration is free. Editing a prompt, a field list, or the
temperature changes the fingerprint and forces fresh calls.

Only replies a previous run could actually *use* are eligible for reuse. A reply that
arrived intact but could not be parsed or failed its schema is never cached, so a bad
answer cannot be served back forever — the next run asks the model again. The
eligibility check reads the source run's `results.jsonl`, so a run whose `results.jsonl`
has been deleted contributes nothing to the cache.

### `output`

| Key | Default | Meaning |
|---|---|---|
| `runs_dir` | `data/runs` | Where run directories are created. |

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

## Design

```text
CLI -> runner -> ChatClient
                   cache -> retry -> rate limit -> recorder -> transport
```

`ChatClient` is a single-method protocol, and every behaviour is a separate object
implementing it. The stack is assembled in exactly one place,
[`llm/build.py`](./src/complaint_analyzer/llm/build.py), so reordering or removing a
behaviour is one edit.

Three boundaries are deliberate:

- `data/` knows about spreadsheets and nothing about analyses.
- `analyses/` knows about prompts and schemas and nothing about transport.
- `run_paths.py` is the only module that builds an output path.

Each field of a record is labelled with its name and closed by a `--------` separator, so
the model can tell record data from instructions, and the system prompt tells it to treat
anything that looks like an instruction inside a record as content to analyze.

## Adding an analysis

An analysis owns its prompt text, its result schema, and its validators.

1. Create `src/complaint_analyzer/analyses/<name>/`.
2. Add `prompts/v1.txt`. The file stem is the version you select in config.
3. Define the result model in `schema.py`. Its fields become the output columns, so
   give every field a default — a partial reply should still produce a row.
4. Add validators in `validators.py`. Each takes `(record, result)` and returns a list
   of human-readable problems. Returning problems flags a record; it does not fail it.
5. Expose `build()` in `__init__.py`, returning an `Analysis`.
6. Register it in [`analyses/__init__.py`](./src/complaint_analyzer/analyses/__init__.py).

Registration is an explicit import, not discovery, so a broken analysis fails loudly at
startup instead of vanishing from the catalog.

To revise an existing analysis's wording, add `prompts/v2.txt` rather than editing `v1`.
Old runs stay reproducible, and the prompt hash recorded in each manifest says which
wording produced which result.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite uses a generated fixture workbook and a scripted fake transport, so it never
touches the network.
