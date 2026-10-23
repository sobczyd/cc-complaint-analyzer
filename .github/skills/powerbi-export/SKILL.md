---
name: powerbi-export
description: "Convert a run's cases.xlsx (Salesforce export) into powerbi.xlsx, a one-row-per-case workbook with the exact 118 column headers of data\\input\\salesforce.xlsx (plus 6 appended serial-number columns) so it can feed the existing Power BI model. Mirrors the trackforce-insight pipeline that builds the dashboard (description parsing, assessments, US Eastern dates), extracts serial numbers, and has a compare command that checks parity with the dashboard for closed cases. Use when asked to create a Power BI export / salesforce.xlsx-shaped file from cases.xlsx."
argument-hint: "--cases data\\runs\\<run>\\cases.xlsx [--out powerbi.xlsx] [--kb-dir data\\kb\\<name>] | compare --ours <powerbi.xlsx>"
user-invocable: true
disable-model-invocation: false
---

# Power BI Export

Reshape `cases.xlsx` (sheets `Cases`, `Problem Codes`, `Complaint Qualifications`) into the
`Sheet1` layout of `data\input\salesforce.xlsx`: same 118 headers in the same order, one row
per case, columns without a source left blank, then the serial-number columns appended.

The dashboard file is produced by the `sobczyd/trackforce-insight` pipeline
(`scripts/dev/preprocess/{reshape_joined_report,shape_cases,derived_fields,parse_case_description}.py`)
from a Salesforce report. This export reproduces that logic from the API query, so for **closed**
cases every Salesforce-sourced column matches the dashboard (see Parity check).

## Prerequisites

- `cases.xlsx` must come from query `cq_crm_codes_nurse_call_no_comments` **v5 or later**. v5 adds
  these CQ fields: KB article, UDI, work order, product feature component, RA actions picklist, and
  `toLabel()` for "service requested". v4 adds `Description` and `LastModifiedDate`. With an older
  file, `Reference Name`, `udi`, `work_order`, `main_sub_assembly`, `actions_to_resolve_2` and the
  parsed description columns fall back or stay blank. Re-run the `salesforce-export` skill with the
  latest version if needed.
- Optional KB corpus (`jira-rca-corpus` skill, `data\kb\<name>\articles.jsonl`). It is only a
  fallback for `Reference Name` when the CQ has no `HRCSVC_KB_Article__c`.

## Procedure

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.powerbi_export `
    --cases data\runs\<run>\cases.xlsx --kb-dir data\kb\<name>
```

This writes `powerbi.xlsx` next to `cases.xlsx` (`--out` overrides the path; `--template` changes
the header source). Report the console line: case count, columns, KB titles, and cases with serial
numbers / old-new serials / Trackwise matches. Also report any warning about dropped extra problem codes or CQs (the
first problem code and the latest CQ per case are used).

**Trackwise:** before running either command, follow the `trackwise-integration` skill. Both commands
call it automatically when `data\trackwise` exists (or `--trackwise-dir <dir>` is given); pass
`--no-trackwise` to skip.

### Data-model package (FactSource + dimensions)

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.powerbi_export package `
    --run data\runs\<run> [--comparison data\runs\compare_<...>] [--clusters <name>] [--defects <name>]
```

Writes `<run>\powerbi_export_package\` with one Excel file per Power BI table, plus `README.md`
(relationships, refresh steps) and `package_manifest.json` (sources, SHA-256, row counts, coverage):

- `FactSource.xlsx`: the powerbi-export output (key `Source Identifier Raw`).
- `DimID.xlsx`: `Source Identifier Raw`, `Source Identifier`, `PR ID`, `Trackwise_Status` (the matched PR's `PR State`).
- `FactComplaint.xlsx`: one row per Trackwise PR ID (see the `trackwise-integration` skill); relates 1:* to FactSource on `Source Identifier Raw`. Only written when Trackwise data is used.
- `DimCluster.xlsx`: key `Case Number`; `Resolved cluster`, `Resolved subcluster`, `Period`, `Mapping status`, `Mapping confidence`. Taken from `--comparison` (`comparison.xlsx` > Case Assignments, folder or file) if given, else from `clusters\<name>\case_assignments.jsonl` (newest, or `--clusters`).
- `DimDefect.xlsx`: 1 FactSource to many rows per `Case Number`; `issue_key`, `issue_type`, `confidence`, `rationale`, `version_justification`, `kb_support`. From `defects\<name>\mappings.xlsx` (newest, or `--defects`); `match_type = none` rows are dropped.
- `DimSummary.xlsx`: key `Source Identifier Raw` (1:1 with FactSource) plus every `case_summary.*` column. From `<run>\cases_with_summaries.xlsx` (Cases sheet); missing file gives a warning and an empty dimension.
- `DimSerial.xlsx`: key `Source Identifier Raw` (1:* with FactSource). `old_serial_numbers` and `new_serial_numbers` are exploded to one de-duplicated row per case, `sn_type` (`old`/`new`) and `serial_number`, with the case-level `pre_sn`, `post_sn`, `pre_sn_date_wwyy`, `post_sn_date_wwyy` and per-serial `sn_date_wwyy`, `sn_date_year`, `sn_age_in_years`, `sn_age_in_months`, `sn_age_category`.

Clusters and defects are optional: missing sources give a warning and an empty dimension. Rows for
cases outside the run (for example the other period in a comparison) are dropped and counted in the
manifest. Report the console counts and any warnings.

### Parity check (closed cases)

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.powerbi_export compare `
    --ours data\runs\<run>\powerbi.xlsx [--dashboard data\input\salesforce.xlsx] [--state Closed|any]
```

- Rows are joined on `Source Identifier Raw`. By default only cases that are `Closed` in both files
  are compared.
- The command writes `powerbi_compare.xlsx`. Its `Columns` sheet gives each column a status:
  - `Matched` / `Not Matched`
  - `Unsourced`: Customer, Customer / Technical Note (no source). Trackwise columns are compared like any other; they match only when the Trackwise exports are current.
  - `Timing`: `export_date`
  - `Derived`: `serial_numbers`, which the dashboard leaves blank
  - `Not in dashboard`: the appended serial columns

  The `Mismatches` sheet lists every cell that differs.
- Before comparing, the command normalizes values: line endings and `_x000D_`, whitespace, pandas
  NA placeholders, and int vs. text.
- The dashboard's Salesforce report cuts long text, usually at 255 characters. A dashboard value
  that is a prefix of ours, at least 250 characters long, counts as a match. The two assessment
  blocks are compared answer by answer in the same way. **The export never truncates.**
- The remaining `Not Matched` cells are usually timing: a case reopened after the dashboard export,
  or formula fields such as `upgrade_date` that change without a record edit. Check them with SOQL
  (`CaseHistory`, `LastModifiedDate`) before calling them bugs.

## Mapping notes

The mapping lives in `src\complaint_analyzer\workflows\powerbi_export\`. `mapping.py` holds
`DIRECT`/`FALLBACKS`, `description.py` the description parser, `derived.py` the assessments,
`serials.py` the serial extraction and `compare.py` the parity check.

- `case_id` is the 15-character Salesforce Id.
- Dates are converted from UTC to **US Eastern** (DST-aware, needs `tzdata`), like the Salesforce
  report. `date_time_*` use `M/D/YYYY h:mm AM`; `Update Timestamp` uses `M/D/YYYY`.
- `PR ID` (CQ TW complaint number) and `udi` are written as integers. `Source Identifier*` is the
  case number, written as text.
- Sources tried in order (first non-empty value wins):
  - `asset_asset_name`: problem-code asset, then case asset
  - `udi`: CQ `HRCSVC_UDI__c`, then case asset UDI
  - `work_order`: CQ work order, then problem-code work order
  - `main_sub_assembly`: CQ `HRCSVC_Product_Feature_Component__c`, then the case field
  - `Reference Name`: CQ `HRCSVC_KB_Article__c`, then the KB corpus title
- Paired CQ columns follow the dashboard:
  - `RA_*` fields feed `test_inspection_troubleshooting`, `test_results_2`, `issue_cause`,
    `log_evidence_2` and `ra_actions_to_resolve`.
  - `HRCSVC_*` fields feed `test_inspection_troubleshooting_2`, `test_results`, `issue_cause_2`,
    `log_evidence` and `actions_to_resolve`.
  - `actions_to_resolve_2` is the RA picklist `RA_Actions_to_Resolve__c` (for example "Resolved").
- `Remote Assessment` / `Device Evaluation Assessment` are `question:answer` blocks, ported
  exactly from trackforce `derived_fields._assessment`. That includes its quirks: both blocks use
  `test_results`, `issue_cause` and `log_evidence`, and the actions answer is
  `{actions_to_resolve}:{ra_actions_to_resolve}`.
- The parsed description columns (Contact Information ? Account Number, `source_description`) use
  the trackforce parser port. It handles label aliases, mid-line IP/serial/ticket labels and bare
  `INC?` tickets; text with no labels goes to `source_description`. Known quirks are kept for
  parity. For example, `Internal Ticket Number:` leaves "Internal" in the previous field.
- Cell values that pandas reads as NA (`N/A`, `NA`, `n/a`, `None`, `null`, `NaN`, `#N/A`?, exact
  match) are blanked, as in the dashboard pipeline.
- `TRUE`/`FALSE` flags are written as booleans; `export_date` is the export time.
- Product-family / lot columns (`...^`), `_Merged` columns and the other Trackwise columns come from
  the `trackwise-integration` skill (below). Without Trackwise data they stay blank (`_Merged`
  falls back to the Salesforce value).

## Serial numbers

- `serial_numbers` (template column) lists every distinct serial cited in the case `Description`
  (including its Additional Information / Serial Number sections), the case `Serial_Number_s__c`
  and the CQ part serial/revision. Values are upper-cased, joined with `, `, in order of first
  appearance.
- A serial is `\d{4,9}[A-Z0-9]{0,3}W(IS|M\d)`, for example `0819028WIS`, `062618PWM2`,
  `26261F1WM2`. This shape covers every serial in the dashboard descriptions. It skips account ids
  (`<JDE>CC`), dates (`050925DT`) and part numbers (`2168B`).
- The appended columns `pre_sn, pre_sn_date, post_sn, post_sn_date, pre_sn_date_wwyy,
  post_sn_date_wwyy` are adapted from the historical `extract_pre_post_serials_from_description`:
  - Extraction runs only when the text has an "old" word, "new", and a serial.
  - `pre_sn` is the first serial after "old" (also previous / original / existing) that does not
    cross "new". `post_sn` is the first serial after "new" that does not cross an "old" word.
  - `*_date` is the manufacturing WWYY. It is normally the first 4 digits. A zero-padded 7-digit
    serial with letters before the `W?` suffix (`0102501PWM2`) uses digits 2-5. An invalid week or
    a future year shifts the window by one digit (generalizes the historical `00`-week rule).
  - `*_date_wwyy` is the Monday of that ISO week, or blank when the week is invalid. It is written as a
    real date cell (`yyyy-mm-dd`).
  - Derived columns: `pre_sn_date_year`, `post_sn_date_year`, `current_year` (export date),
    `pre_sn_age_in_years`, `post_sn_age_in_years` (current_year minus the year),
    `pre_sn_age_in_months_since_1970`, `post_sn_age_in_months_since_1970`, `current_months_since_1970`
    (whole calendar months, Jan 1970 = 0), `pre_sn_age_in_months` (current minus pre), and
    `pre_sn_age_category`: <= 18 "within warranty", <= 60 "within service life", else "beyond expected life".
    `current_year` and `current_months_since_1970` are filled on every row.
  - `old_serial_numbers` / `new_serial_numbers`: comma-separated serials whose nearest preceding keyword
    on the same line is old (also previous / original / existing) or new, any case. Unlabeled serials are
    in neither list. They do not require both old and new to be present.
