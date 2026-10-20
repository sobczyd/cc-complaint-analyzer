# Extending the project

This document describes **where** planned future capabilities should live and
**what they would reuse** from the existing layers. No code or placeholder
folders for these exist yet — this is guidance for when that work starts, not
an inventory of what's already built. See [architecture.md](./architecture.md)
for the layers referenced below.

## General rule: new capabilities are workflows

Every one of the capabilities below is an end-to-end job, not a new shared
layer, so each belongs as a new subpackage under
[`src/complaint_analyzer/workflows/`](../src/complaint_analyzer/workflows/),
alongside `salesforce_export/`, `report_merge/`, and `custom_fetch/`. Each new
workflow should:

- own its CLI (`__main__.py`) and any orchestration logic,
- reuse `core.settings` / `core.run_paths` / `core.logs` for config loading,
  run directories, and logging instead of inventing its own conventions,
- reuse `workbook` for any Excel input/output, and `prompts` / `queries` if it
  needs versioned, auditable text content,
- avoid importing other workflows unless it explicitly composes them (the way
  `custom_fetch` composes `salesforce_export` and `report_merge`).

## Topic modeling

Proposed location: `workflows/topic_modeling/`.

A batch job that reads a workbook (via `workbook`), fits a topic model (for
example LDA or BERTopic) over a text column, and writes topic assignments and
top terms back out — most likely through `workbook.writer` into a new
`analyzed`-style workbook, or a dedicated report. Likely independent of
`llm_client` unless an LLM is used to *label* discovered topics, in which case
it would call `llm_client` the same way `core.runner` does today.

## Custom LangGraph workflows

Proposed location: `workflows/langgraph_flows/`.

Multi-step, potentially branching or looping analyses (as opposed to the
current one-shot-per-record model in `core.runner`) belong here rather than in
`core`, since `core.runner` is deliberately a simple, single-call-per-record
engine. A LangGraph-based workflow would still:

- load configuration through `core.settings` (extended with whatever graph
  parameters it needs),
- write to a run directory obtained from `core.run_paths`, so its outputs sit
  alongside other runs under `data/runs/` with the same auditability,
- call the model either through a LangGraph-native model wrapper around the
  same credentials (`core.settings.Credentials`), or by adapting
  `llm_client`'s `ChatClient` protocol so the existing cache/retry/rate-limit/
  recorder stack can wrap it. The latter is preferable if auditability (saved
  request/response pairs) matters for the graph's calls the way it does for
  `core.runner`.

## Clustering via custom search

Proposed location: `workflows/clustering/`.

Clustering complaint records (for example by embedding similarity) needs an
*embeddings* transport, which `llm_client` does not have today — it only
implements chat completions. When this is built:

- add a new transport alongside
  [`llm_client/openai_compat.py`](../src/complaint_analyzer/llm_client/openai_compat.py),
  for example `llm_client/embeddings.py`, following the same layered-client
  pattern (a small protocol, wrapped by whichever of cache/retry/rate-limit/
  recorder actually apply to embeddings calls),
- keep the clustering algorithm itself (the "custom search method") in
  `workflows/clustering/`, calling into `llm_client` only for the embedding
  calls and into `workbook` for reading input and writing cluster assignments.

## Why this shape

Keeping `core`, `llm_client`, `workbook`, `prompts`, and `queries` free of
workflow-specific logic means every future workflow — including the three
above — can reuse all of them without circular imports or one workflow
depending on another's internals. The only new things a future capability
should ever need to add to the shared layers are:

- a new transport in `llm_client` (like the proposed `embeddings.py`) if it
  needs a new way to call the external LLM API, and
- new config sections in `core.settings` if it needs new YAML config, kept
  under the same "unknown keys are rejected" strictness as `dataset` /
  `analysis` / `rate_limits` / `cache` / `output` today.
