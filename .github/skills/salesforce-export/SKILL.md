---
name: salesforce-export
description: "Run a versioned Salesforce query set (src\\complaint_analyzer\\queries\\<query_set>\\vN.txt) with the sf CLI and write the fetched cases to an Excel workbook (cases.xlsx) with one row per case, joined child-relationship columns, and one detail sheet per child relationship. Use when asked to fetch/export Salesforce cases to Excel."
argument-hint: "query_set --out-dir data\\runs\\<folder> [--version vN] [--target-org alias]"
user-invocable: true
disable-model-invocation: false
---

# Salesforce Export

Turn a saved, versioned SOQL query into an Excel workbook that the analysis
harness (and people) can read. Queries are authored by the
`salesforce-query-author` skill; this skill only runs them.

## Inputs

- **Query set** (required): a folder under `src\complaint_analyzer\queries\`.
  List them with `.\.venv\Scripts\python.exe -m complaint_analyzer.queries --list`.
- **Output folder** (required): normally a session folder under `data\runs\`.
- **Version**: defaults to the latest `vN.txt` in the query set.
- **Target org**: defaults to the sf CLI default org. Before running, report
  which org will be used (`sf config get target-org --json`) so the user knows.

## Procedure

1. Confirm the `sf` CLI is on PATH (`sf --version`). If it is installed
   elsewhere (for example `%USERPROFILE%\.local\node\sf.cmd`), prepend that
   folder to `$env:PATH` in the same command that runs the export.
2. Run the export from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.salesforce export `
       --query-set <query_set> --out-dir <folder> [--version vN] [--target-org <alias>]
   ```

   Live queries can take a few minutes. Use `--from-json <raw.json>` to replay
   a saved `sf data query --json` response without contacting Salesforce.
3. Check the console line `exported N record(s) ...`. If it warns
   `done=false`, tell the user the result may be truncated.
4. Report the files written to the output folder:
   - `query.soql`: the exact query text that ran.
   - `raw.json`: the unmodified `sf data query --json` response.
   - `export.json`: query set, version, target org, row count, columns, and timestamp.
   - `cases.xlsx`: sheet `Cases` (one row per case; parent lookups flattened as
     `Account.Name`; each child relationship joined into a text column such as
     `Problem Codes` plus a `Problem Codes (count)` column), and one sheet per
     child relationship with the case number first.

## Rules

- Never edit query files here; use `salesforce-query-author` to change a query.
- Never put credentials in files. The sf CLI owns authentication.
- Do not run DML or anything other than the saved SELECT query.
