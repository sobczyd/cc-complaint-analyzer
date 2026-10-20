---
name: defect-mapping
description: "Map clustered Nurse Call complaints to the existing Jira defects (NC) and root cause analyses (RCA) that would likely have addressed them, sub-cluster by sub-cluster and optionally batched within a sub-cluster, using the case summaries, their KB article text and a software-version filter. Use after /classify-complaints or case-clustering, when asked to link complaints to defects or RCAs."
argument-hint: "<clusters-dir> [--min-batch 10] [--max-batch 20] [--candidates 40]"
user-invocable: true
disable-model-invocation: false
---

# Defect Mapping

Decides, for each complaint, whether an existing defect or RCA would likely have addressed it if
fixed. Python short-circuits complaints that Jira already links by CRM case number, filters candidates
by software version and lexical similarity, builds the requests and validates the answers; the
`Defect Mapping Worker` agent does the reasoning. Prompt: `defect_mapping` (glossary plus historical
issue-to-case examples). Never edit the prompt here; use `prompt-author`.

Resolve paths from the repository root and use `.\.venv\Scripts\python.exe`. Read
`C:\Users\sobczyd\.copilot\nursecall-AGENTS.md` first.

## Prerequisites

1. A finalized clustering run: `data\runs\<run-id>\clusters\<name>\case_assignments.jsonl` (from
   `/classify-complaints` or `case-clustering`).
2. A Jira corpus and a KB corpus from the `jira-rca-corpus` skill. If either is missing or stale, run
   that skill first; both are reused across mapping runs.

## Defaults

- Batch bounds inside a sub-cluster: `--min-batch 10`, `--max-batch 20`. A sub-cluster no larger than
  the maximum stays whole; larger ones split into balanced batches inside the bounds (23 -> 12 + 11).
- Candidates per batch: `--candidates 40`, drawn from the top `--per-case 10` for each complaint.
- Mapping run directory: `data\runs\<run-id>\defects\<name>`.
- Maximum worker rounds: 2.

## Procedure

1. Prepare (fails if the directory is already prepared; if it exists, resume at step 2):

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.workflows.defect_mapping prepare `
     --assignments data\runs\<run-id>\clusters\<name>\case_assignments.jsonl `
     --out-dir data\runs\<run-id>\defects\<name> `
     --workbook data\runs\<run-id>\cases_with_summaries.xlsx `
     --corpus data\jira\<defects> --corpus data\jira\<rcas> --kb-dir data\kb\<name> `
     [--min-batch 10 --max-batch 20 --candidates 40]
   ```

   Report `case_count`, `direct_link_count`, `mapped_case_count`, `subcluster_count`, `issue_count` and
   `request_count`. Direct links are written to `direct_links.jsonl` and are **not** sent to a worker.
2. Check status: `... defect_mapping check --dir <dir>` (JSON; exit 1 = incomplete).
3. Invoke the `Defect Mapping Worker` agent once per ID in `incomplete_request_ids`, in parallel where
   the agent tool allows. Give each: repository path, run directory, request ID. Never let the parent do
   the matching itself; if delegation is unavailable, stop with an explicit environment error.
4. Re-run `check`. Relaunch workers only for still-incomplete IDs; at most two rounds in total. After the
   second failed check, report every error and stop (valid responses are kept for a resume).
5. Finalize: `... defect_mapping finalize --dir <dir>`. This writes in the run directory:
   - `mappings.jsonl` (one row per complaint-to-issue match, including the direct links)
   - `mappings.xlsx` (sheets Mappings, Batches)
   - `summary.json` (direct links, matched and unmatched counts, the ten most cited issues)
6. Report: direct links, complaints matched to a defect, to an RCA and to nothing, the most cited
   issues, and the paths. Say explicitly that "none" is the expected answer for hardware, configuration
   and no-fault-found complaints.

## Rules

- Only complaints that Jira does not already link are sent to a worker; the short circuit is exact, not
  a judgement call.
- A match must cite a candidate from its own request, and any KB article it cites must have been
  supplied in that request. The CLI enforces both.
- Never paste complaint, comment or article text into chat.
