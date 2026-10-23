---
name: trackwise-integration
description: "Fill the Trackwise-only columns of the Power BI FactSource table and build the FactComplaint table from the raw Trackwise CSV exports in data\\trackwise, following the trackforce-insight reduction rules. Called by the powerbi-export skill (export and package commands) when preparing the Power BI files; use it directly to refresh or check the Trackwise data."
argument-hint: "[--trackwise-dir data\\trackwise] [--no-trackwise]"
user-invocable: true
disable-model-invocation: false
---

# Trackwise Integration

The dashboard's Trackwise columns (Project through `Component Code_Merged`) come from Trackwise, not Salesforce.
This skill joins three raw Trackwise exports to the Salesforce cases and produces:

- the Trackwise-only columns of `FactSource` / `powerbi.xlsx`
- `FactComplaint.xlsx` (package only): one row per Trackwise PR ID

Code: `src\complaint_analyzer\workflows\powerbi_export\trackwise.py`. It ports
`sobczyd/trackforce-insight` `scripts/dev/preprocess/preprocess_tw_export.py` and
`scripts/dev/export/{columns,dedupe,combine}.py`.

## Inputs (`data\trackwise`)

Tab-delimited text, UTF-16 or UTF-8 (detected from the BOM), all read as text so leading zeros survive.

| File | Content |
|---|---|
| `query_export_results.csv` | PR ID, Source Identifier, Project, dates, PR State, Source Status, Event Description, Evaluation Rationale |
| `Product Information.csv` | product family, part number, lot/serial, name, as-reported codes (`...^`) |
| `As Determined Codes.csv` | manufacturing location, as-determined product family, part number, lot, code, category, component, cause (`...^`) |

Refresh the files by exporting them from Trackwise again; the integration reads whatever is in the folder.
If a file is missing the commands stop with an error (use `--no-trackwise` to skip).

## Procedure

1. Confirm the three files exist in `data\trackwise` (or the folder passed with `--trackwise-dir`).
2. Run the `powerbi-export` commands (`export` or `package`). They load Trackwise once and report how many cases matched.
3. Report: cases with Trackwise data, cases without, cases with several PRs, FactComplaint row count (package manifest `coverage`).

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.powerbi_export package `
    --run data\runs\<run> --trackwise-dir data\trackwise
```

## Rules

- Only rows with `Project = Complaint` are kept. PR ID is the key; the last row per PR ID wins
  (product and codes exports have a few duplicates, flagged as `product_IsDuplicated` / `codes_IsDuplicated` = Yes/No).
- Case to PR match: Trackwise `Source Identifier` equals the case number (leading zeros ignored); with several PRs
  the last `Closed` one wins, else the last. If no source identifier matches, the case's own `PR ID` is used.
- Part number (`Product Code/Part #^`): the codes export first, else the product export.
- `As Determined Problem Codes_Merged`, `As Determined Cause Codes_Merged`, `Component Code_Merged`:
  the Trackwise value, else the Salesforce value (also when no PR matched).
- `kept_file` is the cases workbook file name. Dates are kept as the Trackwise text. `Customer` and
  `Customer / Technical Note` stay blank (no source).
- `PR ID` in FactSource is only filled when Salesforce had none.
- FactComplaint `Source Identifier Raw` is the matching case number, else the Trackwise Source Identifier, so it
  relates 1:* to `FactSource[Source Identifier Raw]`.

## Check

Run the parity check from `powerbi-export` against `data\input\salesforce.xlsx` for closed cases; the Trackwise
columns match when the Trackwise exports are as current as the dashboard file.
