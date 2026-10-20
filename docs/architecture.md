# Architecture

This document is the deep dive into how `src/complaint_analyzer` is organized,
what each folder owns, and how a request flows through the system. For setup
and day-to-day commands, see the [README](../README.md); for CLI flags and
config keys, see [cli-reference.md](./cli-reference.md) and
[configuration.md](./configuration.md).

## Layer diagram

```text
                    +--------------------------+
                    |      workflows/          |
                    | salesforce_export        |
                    | report_merge             |
                    | custom_fetch             |
                    +-----------+--------------+
                                |
          +---------------------+---------------------+
          |                     |                      |
   +------v------+       +------v------+        +------v------+
   |  prompts/   |       |  queries/   |        |  workbook/   |
   | (versioned  |       | (versioned  |        | (xlsx I/O +  |
   |  prompt     |       |  SOQL text) |        |  selection)  |
   |  content)   |       +-------------+        +------+-------+
   +------+------+                                     |
          |                                             |
          +---------------------+-----------------------+
                                |
                        +-------v-------+        +----------------+
                        |     core/     |<-------+  llm_client/   |
                        | settings      |        | build/cache/   |
                        | runner        |        | retry/rate_    |
                        | records       |        | limit/recorder/|
                        | run_paths     |        | openai_compat/ |
                        | logs          |        | exchange       |
                        | versioning    |        +----------------+
                        +---------------+
```

`core` is the dependency sink: everything else may import it, it imports
nothing else in the project. `llm_client` depends only on `core` (and
`prompts`, for the harness file-exchange schema). `workbook` depends only on
`core`. `prompts` and `queries` depend only on `core`. `workflows/*` is the
only layer allowed to depend on everything else, including other workflows it
explicitly composes.

## Folder responsibilities

### `core/`

The shared engine. Nothing here knows about workbooks, the LLM client stack,
prompt or query content, or any particular workflow.

- [`settings.py`](../src/complaint_analyzer/core/settings.py) — the YAML
  config schema (`dataset`, `analysis`, `rate_limits`, `cache`, `output`) and
  `.env` credential loading. Unknown keys are rejected, not ignored.
- [`records.py`](../src/complaint_analyzer/core/records.py) — `InputRecord`,
  the dependency-free record type both `workbook` and `prompts` import without
  importing each other.
- [`run_paths.py`](../src/complaint_analyzer/core/run_paths.py) — the single
  owner of every run and call output path. Changing the on-disk layout is one
  edit here, nowhere else.
- [`logs.py`](../src/complaint_analyzer/core/logs.py) — structured run and
  per-call logging with secret redaction.
- [`versioning.py`](../src/complaint_analyzer/core/versioning.py) — shared
  `vN.txt` + `manifest.yaml` + `CHANGELOG.md` conventions used by both
  `prompts` and `queries`.
- [`runner.py`](../src/complaint_analyzer/core/runner.py) — runs one analysis
  over a selection of records: concurrency, per-record error isolation,
  `results.jsonl`, and `manifest.json`. Knows nothing about a specific prompt
  or about how requests reach the network.

### `llm_client/`

The chat-completion client stack: everything involved in turning one
`ChatRequest` into one `ChatResponse`, whether that request goes to a real API
or through the Copilot harness file exchange.

- [`protocol.py`](../src/complaint_analyzer/llm_client/protocol.py) — the
  single-method `ChatClient` protocol every layer below implements.
- [`build.py`](../src/complaint_analyzer/llm_client/build.py) — assembles the
  stack in one place: `cache -> retry -> rate limit -> recorder -> transport`.
  Reordering or removing a behaviour is one edit here.
- `cache.py`, `rate_limit.py`, `retry.py`, `recorder.py` — one cross-cutting
  behaviour each, each wrapping a `ChatClient` and implementing one.
- [`openai_compat.py`](../src/complaint_analyzer/llm_client/openai_compat.py)
  — the real transport: an OpenAI-compatible HTTP client.
- [`exchange.py`](../src/complaint_analyzer/llm_client/exchange.py) — the
  harness backend's versioned file exchange (prepare / check / finalize),
  used instead of `openai_compat` when `--backend harness` is selected.

### `workbook/`

Reads the input workbook, selects which rows to analyze, and writes the
output workbook. Knows about spreadsheets and nothing about analyses.

- [`workbook.py`](../src/complaint_analyzer/workbook/workbook.py) — loads one
  sheet into memory (`Workbook`, `RawRow`, `cell_text`).
- [`selection.py`](../src/complaint_analyzer/workbook/selection.py) — applies
  `dataset.filters` and `dataset.limit`, producing `InputRecord`s.
- [`writer.py`](../src/complaint_analyzer/workbook/writer.py) — writes
  `analyzed.xlsx`: every source column, then the result columns, then a
  status block.

### `prompts/` and `queries/`

Versioned *content*, not behaviour. Each prompt set (or query set) is a
folder of immutable `vN.txt` files plus a `manifest.yaml` (why/when/what
changed per version) and a generated `CHANGELOG.md`. `prompts/` additionally
pairs each prompt with a Pydantic result schema and validators — the model
never sees the schema, so the prompt text must describe every JSON key.
`queries/` holds SOQL text reloaded verbatim, with no schema of its own.

Both folders are maintained through their own CLI and the
`/prompt-author` / `/salesforce-query-author` skills. See
[README.md](../README.md#skills) for pointers, and the per-folder
`CHANGELOG.md` files for history.

### `workflows/`

End-to-end orchestrations built on top of the layers above. Each subpackage
wires `core` / `llm_client` / `workbook` / `prompts` / `queries` together for
one concrete, runnable job. A workflow may depend on any of those shared
layers; workflows should not import each other except where one explicitly
composes another.

- **`salesforce_export/`** — runs a versioned query set through the `sf` CLI
  and writes `cases.xlsx` (one row per case, child relationships flattened to
  joined columns plus their own detail sheets). See
  [`export.py`](../src/complaint_analyzer/workflows/salesforce_export/export.py).
  `export_soql` runs any SELECT statement; `export_query_set` wraps it for
  saved sets, and `select_clause` returns a saved query's SELECT/FROM as a
  field template.
- **`custom_fetch/`** — ad-hoc fetch: writes a run-specific query (drafted by
  the `salesforce-fetch` agent in `.github/agents/`) into a new
  `data/runs/<slug>_<date>/` folder with `request.txt`, `query.soql`,
  `raw.json`, `export.json`, `cases.xlsx` and `session.json`. Nothing is saved
  to `config/` or `queries/`. A failed export leaves no folder. CLI:
  `python -m complaint_analyzer.workflows.custom_fetch init --soql-file Q --slug S --prompt "..." [--based-on SET]`.
  Optional summarization of the same folder: `prepare --run D [--analysis case_summary|rca]`
  writes the harness config, `copilot-batch-run` processes the cases, and
  `finalize --run D` merges them into `cases_with_summaries.xlsx`.
  Ad-hoc export without a run folder: `salesforce_export export --soql-file Q --out-dir D`;
  field template: `salesforce_export fields --query-set SET`.
- **`report_merge/`** — merges a finalized harness run's `results.jsonl` back
  into an exported cases workbook as color-coded generated columns plus a
  `Legend` sheet. See
  [`merge.py`](../src/complaint_analyzer/workflows/report_merge/merge.py).
- **`analysis_run.py`** — plumbing used by `custom_fetch`:
  run-folder naming, harness config, `copilot-batch-run` commands, and the final merge.

A `custom_fetch` run folder under `data/runs/` holds every artifact for
one run:

```text
data/runs/<slug>_<date>/
  request.txt  query.soql  raw.json  export.json   <- custom_fetch / salesforce_export
  cases.xlsx                             <- fetched cases (query data only)
  <analysis>.yaml                        <- generated harness config
  <analysis>/                            <- harness run (exchange/, results.jsonl, manifest.json, ...)
  cases_with_summaries.xlsx              <- deliverable (report_merge)
  session.json                           <- what ran, when, and the merge stats
```

## Control flow

### A plain `python -m complaint_analyzer` run

```text
__main__.py
  -> core.settings.load_settings / load_credentials   (parse config.yaml + .env)
  -> workbook.load_sheet + workbook.select             (read workbook, apply filters/limit)
  -> prompts.get_analysis                              (resolve the configured prompt)
  -> llm_client.build.build                            (assemble cache/retry/rate-limit/
                                                          recorder/transport stack)
  -> core.runner.run                                   (one ChatRequest per record,
                                                          concurrency-limited)
  -> workbook.writer.write_workbook                    (analyzed.xlsx)
  -> core.runner.write_manifest                        (manifest.json, results.jsonl)
```

In harness mode (`--backend harness`), `llm_client.exchange` replaces
`openai_compat` as the transport: `--prepare` exports requests, an external
Copilot session (often via the `/copilot-batch-run` skill) writes responses,
and `--finalize` validates and imports them before the same `write_workbook` /
`write_manifest` steps run.

### `custom_fetch` init → batch run → finalize

```text
workflows.custom_fetch init
  -> workflows.salesforce_export.export_query_set   (query.soql, raw.json, cases.xlsx)
workflows.custom_fetch prepare
  -> build_config + write_config                    (writes <analysis>.yaml)
  -> prints harness_commands (prepare/check/finalize) for the caller to run

  [external: /copilot-batch-run runs the harness-backed analysis for <analysis>.yaml]

workflows.custom_fetch finalize
  -> workflows.report_merge.merge_analysis_run       (reads <analysis>/results.jsonl,
                                                        writes cases_with_summaries.xlsx)
```

## Design principles

- **Single-method protocol, one object per behaviour.** `ChatClient` has one
  method; cache, retry, rate limiting, and recording are each a separate
  class implementing it, assembled in exactly one place
  ([`llm_client/build.py`](../src/complaint_analyzer/llm_client/build.py)).
- **One owner per cross-cutting concern.**
  [`core/run_paths.py`](../src/complaint_analyzer/core/run_paths.py) is the
  only module that builds an output path;
  [`core/versioning.py`](../src/complaint_analyzer/core/versioning.py) is the
  only module that understands the `vN.txt` + manifest convention.
- **Content is not behaviour.** `prompts/` and `queries/` hold versioned text
  and metadata; they do not know how a request is transported or how a run is
  orchestrated.
- **Workflows compose layers; layers never depend on workflows.** This keeps
  `core`, `llm_client`, `workbook`, `prompts`, and `queries` reusable by any
  future workflow (see [extending.md](./extending.md)) without circular
  imports.
- **Record framing.** Each field of a record is labelled with its name and
  closed by a `--------` separator, so the model can tell record data from
  instructions, and the system prompt tells it to treat anything that looks
  like an instruction inside a record as content to analyze.

## See also

- [README.md](../README.md) — overview, setup, and skills.
- [configuration.md](./configuration.md) — `dataset` / `analysis` /
  `rate_limits` / `cache` / `output` config reference.
- [cli-reference.md](./cli-reference.md) — CLI flags, harness-backed runs,
  exit codes, and run output layout.
- [extending.md](./extending.md) — where planned future workflows (topic
  modeling, custom LangGraph workflows, clustering) should live.
