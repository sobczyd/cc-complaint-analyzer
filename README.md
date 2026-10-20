# cc-complaint-analyzer

Classify Nurse Call complaints and link them to the Jira defects and root cause analyses
(RCAs) that would likely have addressed them — all from a **VS Code Copilot session**.
You type a request; Copilot skills fetch cases from Salesforce, summarize and cluster them
with isolated worker agents, and write everything to one run folder under `data\runs\`.
No separate LLM API key is needed: the reasoning is done by Copilot.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

You need Python 3.12+, the Salesforce `sf` CLI logged in to your org, and the
`salesforce-local`, `jira-local`/Atlassian and (optionally) `jama-local` MCP servers
available in VS Code. Open this folder in VS Code, start a Copilot chat in agent mode,
and type a `/skill` command.

## Workflow

```mermaid
flowchart TD
    A["/classify-complaints<br/>'past week for Nurse Call'"] --> B[Fetch cases<br/>salesforce-fetch agent]
    B --> C[Summarize cases<br/>copilot-batch-run + Batch Worker]
    C --> D[Cluster summaries<br/>case-clustering + Cluster Worker]
    D --> E[Merge clusters into workbook<br/>excel-report-merge]
    E --> F[(Run folder<br/>data/runs/...)]
    F --> G["/defect-mapping<br/>(optional)"]
    J[jira-rca-corpus<br/>Jira + KB corpora] --> G
    G --> H[Defect Mapping Worker<br/>per sub-cluster]
    H --> I[mappings.xlsx<br/>defects and RCAs per complaint]
    K[jama-nursecall-context<br/>glossary refresh] -.-> D
```

`/classify-complaints` asks short questions (period, query, batch sizes, glossary) with a
sensible default for each; say "use defaults" to skip them. It can also offer to run
defect mapping at the end.

## Example prompts

| Prompt | Skills / agents used | Result |
|---|---|---|
| `/classify-complaints past week for Nurse Call` | `classify-complaints` → `salesforce-fetch`, `copilot-batch-run` (Batch Worker), `case-clustering` (Cluster Worker), `excel-report-merge` | New run folder with cases, summaries, clusters and `workflow.md` |
| `/classify-complaints Nurse Call complaints in October, use defaults` | same, no questions | Same, with default batch sizes (10 summaries, 100 clustering) |
| `/classify-complaints data\runs\<run-id>` | `classify-complaints` (reuses existing summaries/cases) | Continues from whatever the folder already has |
| `/defect-mapping data\runs\<run-id>\clusters\<name>` | `defect-mapping` → Defect Mapping Worker | `defects\<name>\mappings.xlsx`, `mappings.jsonl`, `summary.json` |
| `/defect-mapping data\runs\<run-id>\clusters\<name> --min-batch 10 --max-batch 20` | `defect-mapping` | Same, with custom batch bounds |
| `/jira-rca-corpus refresh` | `jira-rca-corpus` | Fresh Jira defect/RCA and KB corpora in `data\jira` and `data\kb` |
| `/jama-nursecall-context update the glossary` | `jama-nursecall-context`, `prompt-author` | Updated clustering glossary (new prompt version) |

### Key outputs in a run folder

| File | Contents |
|---|---|
| `cases_with_summaries.xlsx` | Fetched cases plus generated summaries |
| `clusters\<name>\clusters.xlsx` | Cluster / sub-cluster taxonomy with labels, rationale and cited case numbers |
| `cases_with_clusters.xlsx` | Cases with final cluster and sub-cluster columns |
| `defects\<name>\mappings.xlsx` | Complaint → defect/RCA matches (direct Jira links included) |
| `workflow.md` | Mermaid diagram of what this run did |

`/defect-mapping` needs a finished clustering run and the Jira/KB corpora; it runs
`jira-rca-corpus` first if they are missing. Complaints already linked in Jira by CRM case
number are mapped directly; "none" is the expected answer for hardware, configuration and
no-fault-found complaints.

## All skills

Skills live in [`.github/skills/`](./.github/skills/).

| Skill | Purpose |
|---|---|
| [`classify-complaints`](./.github/skills/classify-complaints/SKILL.md) | End-to-end fetch → summarize → cluster into one run folder |
| [`defect-mapping`](./.github/skills/defect-mapping/SKILL.md) | Map clustered complaints to Jira defects and RCAs |
| [`jira-rca-corpus`](./.github/skills/jira-rca-corpus/SKILL.md) | Build/refresh Jira defect, RCA and KB corpora |
| [`case-clustering`](./.github/skills/case-clustering/SKILL.md) | Cluster case summaries in batches and merge the taxonomies (tiered group + meta-merge for large runs) |
| [`copilot-batch-run`](./.github/skills/copilot-batch-run/SKILL.md) | Run any registered prompt across isolated Copilot workers |
| [`salesforce-export`](./.github/skills/salesforce-export/SKILL.md) | Export a versioned Salesforce query to Excel |
| [`excel-report-merge`](./.github/skills/excel-report-merge/SKILL.md) | Merge results and clusters back into a cases workbook |
| [`jama-nursecall-context`](./.github/skills/jama-nursecall-context/SKILL.md) | Maintain the clustering glossary from Jama |
| [`prompt-author`](./.github/skills/prompt-author/SKILL.md) | Create or revise a versioned analysis prompt |
| [`salesforce-query-author`](./.github/skills/salesforce-query-author/SKILL.md) | Create or revise a versioned SOQL query |

Prompts (`src\complaint_analyzer\prompts\`) and queries (`src\complaint_analyzer\queries\`)
are immutable versioned `vN.txt` files; use `prompt-author` and `salesforce-query-author`
rather than editing them by hand.

## Repository layout

```text
.github/skills/, .github/agents/   Copilot skills and worker agents
src/complaint_analyzer/            Python helpers that prepare, validate and finalize runs
  workflows/                       classify_complaints, case_cluster, defect_mapping, ...
  prompts/, queries/               versioned prompts and SOQL query sets
data/runs/                         one folder per run (gitignored except examples)
docs/                              architecture, configuration, CLI reference, extending
```

More detail: [docs/architecture.md](./docs/architecture.md),
[docs/cli-reference.md](./docs/cli-reference.md),
[docs/configuration.md](./docs/configuration.md),
[docs/extending.md](./docs/extending.md).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
