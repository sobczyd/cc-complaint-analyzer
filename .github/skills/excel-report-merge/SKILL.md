---
name: excel-report-merge
description: "Merge finalized harness analysis results (results.jsonl from a copilot-batch-run) back into a cases workbook as extra, color-coded columns with a Legend sheet, producing one Excel file of fetched cases plus generated analysis. Use when asked to add summaries/RCA results to the exported cases Excel."
argument-hint: "--cases cases.xlsx --run-dir <runs_dir>\\<run_id> --out merged.xlsx [--analysis case_summary]"
user-invocable: true
disable-model-invocation: false
---

# Excel Report Merge

Combine the Salesforce export (`cases.xlsx`) with a finalized harness run so
reviewers get a single workbook: the original query columns untouched, followed
by generated columns that are visibly different.

## Inputs

- `--cases`: workbook from the `salesforce-export` skill (sheet `Cases`).
- `--run-dir`: the finalized harness run folder containing `results.jsonl`
  (and `manifest.json`). Finalize with `copilot-batch-run` first.
- `--out`: the merged workbook path.
- `--analysis`: the prompt name (default `case_summary`); also the column prefix
  unless `--prefix` is given.
- `--id-field`: join key between cases and results (default `CaseNumber`).

## Procedure

1. Confirm `<run-dir>\manifest.json` exists. If it does not, the run is not
   finalized; finish `copilot-batch-run` first (or tell the user that rows
   without results will be marked `not_run`).
2. Run from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe -m complaint_analyzer.report merge `
       --cases <cases.xlsx> --run-dir <run_dir> --out <merged.xlsx> [--analysis case_summary]
   ```

3. Read the JSON it prints and report `rows`, `matched`, `status_counts`, and
   `unmatched_results`. Exit code 2 means a merge error (bad workbook, missing id
   column, clashing column names, or unreadable results).

## Output layout

- Sheet `Cases`: all query columns first (unchanged), then generated columns
  named `<analysis>.<field>` plus `<analysis>.analysis_status` and
  `<analysis>.analysis_error`. Generated headers and cells have a light-blue fill
  (`DDEBF7`) so they are obviously not Salesforce data. List values are joined
  with line breaks.
- Child-relationship sheets from the export are copied unchanged.
- Sheet `Legend`: explains the color coding, the source run, and each
  generated column.

## Rules

- Never alter query data columns; only append generated ones.
- Rows without a result get status `not_run`, never invented content.
