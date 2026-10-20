---
name: case-clustering
description: "Cluster summarized Nurse Call cases (from a cases_with_summaries.xlsx in data\\runs) into groups of similar meaning and intent, in batches (default 100), then merge the batch results into one final cluster / sub-cluster taxonomy with labels, rationale and cited case numbers. Use when asked to cluster, group, or find themes across case summaries."
argument-hint: "<run-id> [--limit 100] [--offset 0] [--batch-size 100]"
user-invocable: true
disable-model-invocation: false
---

# Case Clustering

Groups cases by meaning and intent using the `case_summary.*` columns of a run's
`cases_with_summaries.xlsx`. Python (`complaint_analyzer.workflows.case_cluster`) builds requests,
validates every response and applies the merge map; the `Cluster Worker` agent does the reasoning.
Prompts: `case_cluster` (per batch) and `case_cluster_merge` (final), both carrying the glossary in
`src\complaint_analyzer\prompts\case_cluster\glossary.md`. Never edit prompts or the glossary here; use
`prompt-author` (and `jama-nursecall-context` for glossary refreshes).

## Defaults

- Workbook: `data\runs\<run-id>\cases_with_summaries.xlsx` (first sheet, `Cases`)
- Limit: `100` cases (`--limit 0` = all summarized cases), offset `0`, batch size `100`
- Cluster run directory: `data\runs\<run-id>\clusters\<name>` (for example `pilot_100`)
- Maximum worker rounds: 2

Only rows with `case_summary.analysis_status = ok` and a summary are eligible, in file order.
Resolve paths from the repository root. Use `.\.venv\Scripts\python.exe`.

## Procedure

1. Read `C:\Users\sobczyd\.copilot\nursecall-AGENTS.md`.
2. Prepare (fails if the directory is already prepared; if it exists, resume at step 3):

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.workflows.case_cluster prepare `
     --workbook data\runs\<run-id>\cases_with_summaries.xlsx `
     --out-dir data\runs\<run-id>\clusters\<name> --limit <n> --offset <o> --batch-size <b>
   ```

   Report `case_count`, number of batches, prompt versions and whether `merge_required`.
3. Check status: `... case_cluster check --dir <dir>` (JSON; exit 1 = incomplete).
4. Invoke the `Cluster Worker` agent once per ID in `incomplete_request_ids`, in parallel where the agent
   tool allows. Give each: repository path, run directory, request ID. Never let the parent cluster the
   cases itself; if delegation is unavailable, stop with an explicit environment error.
5. Re-run `check`. Relaunch workers only for still-incomplete IDs; at most two rounds in total. After the
   second failed check, report every error and stop (valid responses are kept for a resume).
6. If `merge_required`, merge in tiers. Loop:
   1. Run `... case_cluster prepare-merge --dir <dir>`. It builds the next tier's requests and prints
      `tier`, `tiers`, `request_ids`, `final` and `complete`.
   2. Run one `Cluster Worker` per ID in `request_ids` (in parallel; same retry rule), then `check`.
   3. Repeat until `prepare-merge` reports `complete: true`.

   Up to `--merge-fanin` batches (default 5) need a single `merge` request. Larger runs (for example ~20
   batches for a month) are merged in groups of `merge_fanin` batches (`merge_01_NN`), then the group
   results are combined by meta-merge requests (`meta_TT_NN`, prompt `case_cluster_meta_merge`), adding tiers
   until one request remains. A request never sees more than `merge_fanin` inputs.
7. Finalize: `... case_cluster finalize --dir <dir>`. This writes in the run directory:
   - `final_taxonomy.json` (clusters, sub-clusters, descriptions, rationale, case numbers, source batch ids)
   - `case_assignments.jsonl` (each case with batch and final cluster/sub-cluster)
   - `clusters.xlsx` (sheets Clusters, Subclusters, Case Assignments, Merge Map)
8. Report: cluster and sub-cluster counts, the five largest clusters with sizes, and the paths. For a
   single batch no merge happens and batch labels are the final labels.

## Scaling

To cover all 800 cases, run `--limit 0 --batch-size 100` in one prepared directory (8 batches, then a tiered
merge: 2 group merges and one meta-merge at the default fan-in of 5). For ~2000 cases, expect ~20 batches
and three tiers at most. Add `--merge-fanin <n>` to `prepare` to tune how many inputs one merge request sees.
The final map is only as consistent as the merges; review the `Merge Map` sheet (its `Intermediate merges`
column shows the group-level label each batch sub-cluster passed through) for surprising merges.
The manifest records the prompt versions and the case selection for reproducibility.
