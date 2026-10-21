---
name: classify-complaints
description: "End-to-end complaint classification: fetch Nurse Call cases from Salesforce (or reuse a run folder), summarize them with the latest case_summary prompt, cluster the summaries with the glossary-driven clustering workflow, and store everything in one run folder with a static Mermaid workflow diagram (workflow.md). Use when asked to classify, summarize and cluster complaints for a period, for example 'classify complaints over the past week for Nurse Call'."
argument-hint: "<request, e.g. 'past week for Nurse Call'> [folder]"
user-invocable: true
disable-model-invocation: false
---

# Classify Complaints

Chains `salesforce-fetch` (custom_fetch), `copilot-batch-run` (summaries) and `case-clustering` into one
run folder under `data\runs\`. Python prepares and validates; worker agents do the reasoning.
Resolve paths from the repository root and use `.\.venv\Scripts\python.exe`. Read
`C:\Users\sobczyd\.copilot\nursecall-AGENTS.md` first.

## Asking vs. assuming

Ask the user with `ask_user` (one question at a time, with choices; the first choice is the default) before
each assumption below. If the user declines or says "use defaults", take the default and state it. Record
each decision with:

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.classify_complaints state --run <run_dir> --set request="..." source=... query=... summary_batch_size=10 cluster_batch_size=100 glossary="as is"
```

## Procedure

1. **Parse the request**: product (default Nurse Call) and period (for example "past week" = last 7 days),
   and an optional folder.
2. **Data source**
   - Folder given: use it. If it has `cases_with_summaries.xlsx`, skip to step 4; if it has only
     `cases.xlsx` / `case_context.xlsx`, skip to step 3. Otherwise report the problem and fall back to a fetch
     after asking.
   - No folder: fetch. Ask to confirm the period and the query. Default query set:
     `cq_crm_codes_nurse_call_no_comments`, **latest version** (currently
     `src\complaint_analyzer\queries\cq_crm_codes_nurse_call_no_comments\v4.txt`; find the newest
     `vN.txt` rather than assuming). If the user did not name a query, ask with `ask_user` whether to use
     the latest version of the default set (first choice, recommended) or another query name/version
     (list with `.\.venv\Scripts\python.exe -m complaint_analyzer.queries --list`) before proceeding.
     Build a run-specific SOQL from that
     set (`python -m complaint_analyzer.workflows.salesforce_export fields --query-set <set> [--version vN]`;
     defaults to the latest), replacing its
     `CreatedDate = LAST_N_DAYS:30` filter with the requested range (for example `LAST_N_DAYS:7`) and keeping
     the complaint-code and child filters. Follow `.github\agents\salesforce-fetch.agent.md` steps 2-5
     (`custom_fetch init ... --based-on <query_set>`). Report org, row count and any `done=false` warning.
     With 0 cases, stop.
3. **Summarize**: ask the summary batch size (default 10). Use the latest `case_summary` version and the
   current fields; never create a prompt unless the user explicitly asks (then use `prompt-author`). Run
   `custom_fetch prepare --run <run_dir> --analysis case_summary --batch-size <n>`; if more than 200 cases,
   confirm first. Run `copilot-batch-run` with the printed `harness_commands` (Batch Worker agents), then
   `custom_fetch finalize --run <run_dir>` to write `cases_with_summaries.xlsx`.
4. **Cluster**: ask the clustering batch size (default 100) and whether to use the glossary as is or update
   it first. To update, use `jama-nursecall-context` / `prompt-author` (this bumps prompt versions), then
   continue. Run the `case-clustering` skill procedure with `--limit 0 --batch-size <b>` and
   `--out-dir <run_dir>\clusters\<name>` (name like `all_b<b>`), including the tiered merge when required
   (group merges, then meta-merge tiers, until `prepare-merge` reports `complete`; a month of ~2000 cases
   typically needs three tiers).
5. **Cases with clusters**: run the `excel-report-merge` skill's `merge-clusters` command with
   `--cases <run_dir>\cases_with_summaries.xlsx --cluster-dir <run_dir>\clusters\<name>` to write
   `<run_dir>\cases_with_clusters.xlsx`.
6. **Defect mapping** (optional): ask whether to map the complaints to existing Jira defects and RCAs.
   If yes, run the `jira-rca-corpus` skill when the corpora are missing or stale, then the
   `defect-mapping` skill against `<run_dir>\clusters\<name>\case_assignments.jsonl`.
   Also offer the `powerbi-export` skill to write `<run_dir>\powerbi.xlsx` (salesforce.xlsx layout) from `cases.xlsx`.
7. **Diagram**: record the final choices with `state`, then generate the static diagram (rerun any time):

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.workflows.classify_complaints diagram --run <run_dir>
   ```

   It writes `<run_dir>\workflow.md` (Mermaid flowchart plus step descriptions, filled from `session.json`,
   `classification.json` and the clusters manifest).
8. **Report**: run folder, case counts, summary status counts, cluster and sub-cluster counts, the five
   largest clusters, and key files (`cases_with_summaries.xlsx`, `clusters\...\clusters.xlsx`, `workflow.md`).

## Rules

- Only SELECT queries; never copy record data into chat or committed files.
- Delegate reasoning to worker agents; the parent never summarizes or clusters cases itself. If delegation
  is unavailable, stop and give the user the commands.
- Everything goes in the one run folder; do not write into `config\` or `src\complaint_analyzer\queries\`.
