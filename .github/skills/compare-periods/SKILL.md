---
name: compare-periods
description: "Compare the clustered complaints of two time points (for example September vs October 2026), either from two classify-complaints run folders or from one run folder split by date. Resolves the later period's cluster names onto the baseline period's taxonomy, then writes counts, shares, per-day rates and NEW / GONE / UPTICK / DECLINE flags with a full audit trail. Use after /classify-complaints (defect mapping is not required) when asked to compare months, find new or growing clusters, or see what changed between periods."
argument-hint: "<period A run or range> <period B run or range> [comparison type]"
user-invocable: true
disable-model-invocation: false
---

# Compare Periods

Compares two time points at cluster and sub-cluster level. Time point **A is the baseline**; a worker maps each
time point **B** sub-cluster onto an A sub-cluster (or flags it NEW), so both periods use the same labels. Python
(`complaint_analyzer.workflows.compare_periods`) loads the runs, builds the requests, validates the answers and
computes the metrics; the `Cluster Resolve Worker` agent does the reasoning. Prompt: `cluster_resolve` (carries the
Nurse Call glossary). Never edit the prompt here; use `prompt-author`.

Resolve paths from the repository root and use `.\.venv\Scripts\python.exe`. Read
`C:\Users\sobczyd\.copilot\nursecall-AGENTS.md` first.

## Prerequisites

Each period needs a finalized cluster directory (`data\runs\<run>\clusters\<name>\case_assignments.jsonl` and
`final_taxonomy.json`) and a case workbook with `CaseNumber` and the date field (`cases_with_clusters.xlsx`,
`cases_with_summaries.xlsx` or `cases.xlsx`) from `/classify-complaints`. If a period has not been classified yet, run
`/classify-complaints` first. Defect mapping is not needed.

## Asking vs. assuming

Ask with `ask_user` (one question at a time, with choices; the first choice is the default) before each item below.
If the user says "use defaults", take the default and state it.

1. **Time points**: two run folders, or one run folder split by dates (`--a-start/--a-end`, `--b-start/--b-end`,
   inclusive, on `CreatedDate`). Ask for a label for each (for example "Sep 2026"). A is the earlier, baseline point.
2. **Comparison type**: default `clusters` (cluster and sub-cluster comparison). It is the only type implemented;
   if the user wants another (by account, software version, complaint qualification), say it is not available yet,
   record the request in `--request`, and offer the cluster comparison.
3. **Cluster directory** per run: run `... compare_periods list-clusters --run <run>`; offer the `suggested` one
   (finalized, most cases) first. Warn if it covers fewer cases than the run's export (a pilot).
4. **Resolution batch size** (B sub-clusters per request): default 15. Not used when both periods share one clustering.
5. **Flag thresholds**: default flag UPTICK / DECLINE when the change in cases is more than `--min-change 10` and at
   least one period has `--min-cases 10` cases in that cluster; NEW and GONE are always flagged. Ask whether to keep
   these, and (when the period lengths differ) whether to compare raw counts (`--flag-basis count`, default) or
   per-day-adjusted counts (`--flag-basis per_day`).
6. **Output folder**: default `data\runs\compare_<A>_vs_<B>_<date>`.

## Procedure

1. Prepare (fails if the folder exists; if it exists, resume at step 2):

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.workflows.compare_periods prepare `
     --a-run data\runs\<run-a> [--a-clusters <name>] [--a-start YYYY-MM-DD --a-end YYYY-MM-DD] --a-label "<A>" `
     --b-run data\runs\<run-b> [--b-clusters <name>] [--b-start YYYY-MM-DD --b-end YYYY-MM-DD] --b-label "<B>" `
     [--out-dir <dir>] [--batch-size 15] [--min-change 10] [--min-cases 10] [--flag-basis count] `
     --request "<user request>"
   ```

   Omit `--b-run` to split one run by date. Report `case_counts`, `days`, `resolution_required`,
   `request_count` and every warning (different period lengths, different case filters in the two runs' queries,
   a cluster directory that covers only part of a run, overlapping periods). Ask whether to continue when a
   warning questions the comparison.
2. If `resolution_required` is false (one shared clustering), skip to step 5.
3. Check status: `... compare_periods check --dir <dir>` (JSON; exit 1 = incomplete).
4. Invoke the `Cluster Resolve Worker` agent once per ID in `incomplete_request_ids`, in parallel where the agent
   tool allows. Give each: repository path, comparison folder, request ID. Never let the parent do the mapping
   itself; if delegation is unavailable, stop with an explicit environment error. Re-run `check`; relaunch workers
   only for still-incomplete IDs, at most two rounds in total. After the second failed check, report every error
   and stop (valid responses are kept for a resume).
5. Finalize: `... compare_periods finalize --dir <dir>`. It writes:
   - `comparison.xlsx` (Summary, Clusters, Subclusters, Case Assignments, Mapping, Sources, Legend)
   - `summary.md` (periods, warnings, flagged clusters, new / gone / largest changes)
   - `comparison.json`, `resolved_assignments.jsonl` (each case with its original and resolved labels, both
     periods), `mapping.jsonl` (B sub-cluster to baseline, confidence, rationale), `sources.json` (runs, cluster
     directories, SHA-256 of the assignments, filters, date ranges, thresholds, prompt version)
   - `manifest.json`, `period_cases.jsonl`, `baseline_taxonomy.json`, `period_b_taxonomy.json`, `requests\`,
     `responses\` (the inputs, for audit)

   A group present in only one period shows 0 for the other.
6. Report: the folder, the two periods (runs, dates, days, case counts), the mapping outcome (matched, renamed, new,
   low-confidence), the flagged clusters (NEW, GONE, UPTICK, DECLINE with counts and share points), the largest
   sub-cluster changes, all warnings, and the key files. Mention low-confidence mappings for review in the
   `Mapping` sheet. Report counts and labels only; never paste case text.

## Rules

- Everything goes in the one comparison folder; do not modify the source runs, `config\` or prompts.
- Periods with different lengths are not comparable by raw count; always state the warning and point to share and
  cases per day.
- The mapping is judgment; the audit sheets (`Mapping`, `Case Assignments`) are how to review it. Never
  hand-edit `responses\` to change a mapping; fix it by rerunning the request.
- Delegate reasoning to worker agents; the parent only runs the commands and reports.
