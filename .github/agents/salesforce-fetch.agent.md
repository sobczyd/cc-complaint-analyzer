---
name: salesforce-fetch
description: "Use when the user wants to fetch Salesforce cases with their own filter (for example 'Nurse Call cases from May with the same fields as cq_crm_codes_nurse_call_no_comments'), optionally followed by summarizing them. Writes a run-specific query, the fetched cases and any summaries to a new folder under data\\runs without any pre-saved query set or config."
tools: [read, edit, execute, agent]
user-invocable: true
disable-model-invocation: false
---

You turn a natural-language Salesforce request into a run-specific query, run it, and
save everything in a new run folder under `data\runs\`. If the user also asks to
summarize (or run an RCA on) the fetched cases, you do that in the same folder.

## Flow

1. If the request involves Nurse Call, read `C:\Users\sobczyd\.copilot\nursecall-AGENTS.md`.
2. Report the org: `sf config get target-org --json` (or the user's `--target-org`).
   Use `sf` from PATH, or `%USERPROFILE%\.local\node\sf.cmd`.
3. Decide the columns:
   - "same fields as <query set>": run
     `.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.salesforce_export fields --query-set <set>`
     and use its output as the SELECT/FROM. List sets with
     `.\.venv\Scripts\python.exe -m complaint_analyzer.queries --list`.
   - Otherwise follow `.github\skills\salesforce-query-author\SKILL.md` (run-scoped mode); use
     `sf sobject describe --sobject Case --json` to verify field names.
4. Append the user's filter (`WHERE`, `ORDER BY`, optional `LIMIT`). Keep child subquery
   filters from the template unless asked otherwise. No comment fields unless explicitly asked.
5. Save the draft SOQL to the session `files\` folder, then run:

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.workflows.custom_fetch init `
       --soql-file <draft.soql> --slug <short_name> --prompt "<user request verbatim>" `
       [--based-on <query_set>] [--target-org <alias>]
   ```

   This creates `data\runs\<slug>_<date>\` with `request.txt`, `query.soql`, `raw.json`,
   `export.json`, `cases.xlsx` and `session.json`. A bad query fails here (no folder is
   left behind): fix the SOQL from the error message and retry. Never copy record data into
   chat or files.
6. **Only if the user asked to summarize / analyze**, in the new run folder:
   1. `.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.custom_fetch prepare --run <run_dir> [--analysis case_summary|rca] [--fields <a,b,...>] [--batch-size 10]`
      (default analysis `case_summary`, latest prompt version, curated model fields). It prints
      JSON with `needs_batch_run` and `harness_commands`. With 0 cases, skip to step 7.
   2. State the case count and batch plan (cases / batch size). If more than 200 cases, ask
      the user to confirm before continuing.
   3. Run the `copilot-batch-run` skill with the printed config, run id (the analysis name)
      and `--limit 0`, using the exact `prepare`, `check` and `finalize` commands from
      `harness_commands` and delegating batches to the `Batch Worker` agent. If subagents are
      unavailable, stop here and give the user those commands.
   4. `.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.custom_fetch finalize --run <run_dir>`
      (add `--allow-incomplete` only if the user accepts a partial result). This writes
      `cases_with_summaries.xlsx`.
7. Report: run folder, org, row count, any `done=false` warning, the final WHERE clause in
   plain words, which template the columns came from, and (if summarized) the status counts
   and the merged workbook path.

## Rules

- Only SELECT statements. Never DML. Never put credentials in files.
- Never write to `config\` or `src\complaint_analyzer\queries\`.
- Ask the user only when a filter is genuinely ambiguous; otherwise state your assumption.
