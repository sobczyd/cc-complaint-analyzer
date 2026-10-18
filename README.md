# cc-complaint-analyzer

Row-by-row LLM analysis of service-record workbooks, with saved call history, logging,
selection, and rate limiting. Each selected row is sent to the model on its own, the
reply is validated against a schema and a set of analysis-specific checks, and
everything — the request, the reply, the timings, and the decision — is written to
disk so the result can be audited later.

On top of that core engine, the repository also has workflows for pulling cases out of
Salesforce, merging analysis results back into a reviewer-friendly workbook, and running
a recurring "daily review" session that chains both together.

For a deep dive into how the code is organized and how a request flows through it, see
[docs/architecture.md](./docs/architecture.md). For full CLI flags and config keys, see
[docs/cli-reference.md](./docs/cli-reference.md) and
[docs/configuration.md](./docs/configuration.md). For where planned future work
(topic modeling, LangGraph workflows, clustering) should live, see
[docs/extending.md](./docs/extending.md).

## Repository structure at a glance

```text
src/complaint_analyzer/
  core/           shared engine: settings, run paths, logging, versioning, the runner
  llm_client/     chat-completion client stack (cache/retry/rate-limit/recorder/transport)
  workbook/       Excel input/output and row selection
  prompts/        versioned LLM analysis prompts + result schemas (rca, case_summary)
  queries/        versioned Salesforce SOQL query sets
  workflows/      end-to-end jobs built on the layers above
    salesforce_export/   export a query set to an Excel workbook
    report_merge/        merge harness results back into a workbook
    daily_review/        compose the two above into a recurring session
docs/             architecture, configuration, CLI reference, and extension points
config/           example and working YAML configs for the core analysis CLI
data/             input workbooks and run output (gitignored except examples)
```

See [docs/architecture.md](./docs/architecture.md) for what each folder is
responsible for, how the layers depend on each other, and control-flow
walkthroughs.

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

Once installed, the `complaint-analyzer` console script does the same thing. This is
API mode (`--backend api`, the default); start with `--dry-run` to confirm your filters
select the rows you expect.

Harness mode (`--backend harness`) uses this VS Code Copilot session instead of an LLM
API key — see the `/copilot-batch-run` skill below, or
[docs/cli-reference.md](./docs/cli-reference.md) for the full `--prepare` /
`--check` / `--finalize` walkthrough and every CLI flag.

## Skills

These live under [`.github/skills/`](./.github/skills/) and are invoked from a VS Code
Copilot session (for example `/copilot-batch-run ...`).

| Skill | What it does |
|---|---|
| [`salesforce-export`](./.github/skills/salesforce-export/SKILL.md) | Runs a versioned Salesforce query set with the `sf` CLI and writes the fetched cases to an Excel workbook (`cases.xlsx`), with child relationships flattened to joined columns and detail sheets. |
| [`excel-report-merge`](./.github/skills/excel-report-merge/SKILL.md) | Merges a finalized harness run's `results.jsonl` back into an exported cases workbook as color-coded generated columns, with a `Legend` sheet. |
| [`copilot-batch-run`](./.github/skills/copilot-batch-run/SKILL.md) | Prepares, fans out, resumes, validates, and finalizes a harness-backed run of any registered prompt across isolated Copilot workers, in configurable batches. |
| [`daily-nurse-call-review`](./.github/skills/daily-nurse-call-review/SKILL.md) | The daily workflow: fetches Nurse Call cases from the last 7 days, summarizes each with `copilot-batch-run`, and saves everything — including the merged, color-coded Excel — in one session folder under `data/runs/`. |
| [`prompt-author`](./.github/skills/prompt-author/SKILL.md) | Writes or revises an LLM analysis prompt from a natural-language description, saving it as the next versioned file with a manifest entry and a regenerated changelog. |
| [`salesforce-query-author`](./.github/skills/salesforce-query-author/SKILL.md) | Writes or revises a Salesforce SOQL query, validates it against the org, and saves it as the next versioned file with a manifest entry and a regenerated changelog. |

## Configuration

See [docs/configuration.md](./docs/configuration.md) for the full `dataset` /
`analysis` / `rate_limits` / `cache` / `output` reference and filter operators, and
[config/rca.example.yaml](./config/rca.example.yaml) for a commented example.

## Prompt and query sets

Prompts live under `src/complaint_analyzer/prompts/<name>/` and query sets under
`src/complaint_analyzer/queries/<name>/`, each as a folder of immutable `vN.txt` files
plus a `manifest.yaml` and a generated `CHANGELOG.md`. Use the matching CLI to inspect
them:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.prompts --list
.\.venv\Scripts\python.exe -m complaint_analyzer.queries --list
```

Author new prompts or queries with the `/prompt-author` and `/salesforce-query-author`
skills rather than editing these folders by hand. See
[docs/architecture.md](./docs/architecture.md#prompts-and-queries) for the folder
layout and manifest fields.

## What's next

Planned future work — topic modeling, custom LangGraph workflows, and clustering via
a custom search method against the external LLM API — has a documented home before any
code exists: see [docs/extending.md](./docs/extending.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite uses a generated fixture workbook and a scripted fake transport, so it never
touches the network.
