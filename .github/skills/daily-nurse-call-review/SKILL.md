---
name: daily-nurse-call-review
description: "Daily workflow: fetch Nurse Call complaint cases from the last 7 days from Salesforce (query set nurse_call_last_7_days), summarize every case with the case_summary prompt via copilot-batch-run, and save everything in one session folder under data\\runs\\ including an Excel of the cases with color-coded summary columns. Use when asked for the daily/last-seven-days Nurse Call review or case summaries."
argument-hint: "[--date YYYY-MM-DD] [--target-org alias] [--batch-size 10]"
user-invocable: true
disable-model-invocation: false
---

# Daily Nurse Call Review

One command creates the session; Copilot workers do the summaries; one command
merges the results. Everything for the run lives in one folder:

```text
data\runs\nurse_call_last_7_days_<YYYY-MM-DD>[_N]\
  query.soql  raw.json  export.json      <- salesforce-export
  cases.xlsx                             <- fetched cases (query data only)
  case_summary.yaml                      <- generated harness config
  case_summary\                          <- copilot-batch-run (exchange\, results.jsonl, manifest.json, ...)
  cases_with_summaries.xlsx              <- the deliverable (excel-report-merge)
  session.json                           <- what ran, when, and the merge stats
```

A second run on the same day gets a `_2`, `_3`, ... suffix; earlier sessions
are never overwritten.

## Procedure

Run every command from the repository root. The `sf` CLI must be on PATH (see
the `salesforce-export` skill).

1. **Report the org.** Run `sf config get target-org --json` and tell the user
   which org will be queried (unless they passed `--target-org`).

2. **Create the session and export the cases:**

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.daily nurse-call-7d init [--date YYYY-MM-DD] [--target-org <alias>] [--batch-size 10]
   ```

   The live Salesforce query can take a few minutes. The command prints JSON
   with `session_dir`, `rows`, `done`, `config`, `run_id`, `needs_batch_run`,
   and `harness_commands` (`prepare`, `check`, `finalize`). If `done` is
   `false`, warn that Salesforce may have truncated the result.

3. **If `needs_batch_run` is `false`** (zero cases), skip to step 5.

4. **Summarize with the `copilot-batch-run` skill**, using the session config
   and run id from step 2 and `--limit 0` (every fetched case):
   - config: the `config` path printed in step 2
   - run id: `case_summary`
   - limit: `0`
   - batch size: as printed (default 10)

   Use the exact `prepare`, `check`, and `finalize` commands from
   `harness_commands`, and follow every rule of `copilot-batch-run` (isolated
   workers, retry rounds, validation). Do not finalize partially unless the user
   agrees.

5. **Merge into the deliverable workbook:**

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.daily nurse-call-7d finalize --session <session_dir>
   ```

   It refuses to run when the harness run has no `manifest.json`. Only if the
   user accepts a partial result, add `--allow-incomplete` (rows without a
   result get status `not_run`).

6. **Report** to the user: the session folder, the org queried, the case count,
   the status counts from finalize, and a link to
   `cases_with_summaries.xlsx`. Mention that the light-blue columns
   (`case_summary.*`) are generated, not Salesforce data, and that the Legend
   sheet explains them.

## Rules

- Do not edit the query or prompt here; use `salesforce-query-author` or
  `prompt-author` and then rerun.
- Do not change `case_summary.yaml` by hand unless the user asks.
- Never delete earlier session folders.
