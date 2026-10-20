---
name: powerbi-export
description: "Convert a run's cases.xlsx (Salesforce export) into powerbi.xlsx, a one-row-per-case workbook with the exact 118 column headers of data\\input\\salesforce.xlsx so it can feed the existing Power BI model. Parses the case Description into Contact/Location/Issue/etc. and looks up the KB article title. Use when asked to create a Power BI export / salesforce.xlsx-shaped file from cases.xlsx."
argument-hint: "--cases data\\runs\\<run>\\cases.xlsx [--out powerbi.xlsx] [--kb-dir data\\kb\\<name>]"
user-invocable: true
disable-model-invocation: false
---

# Power BI Export

Reshape `cases.xlsx` (sheets `Cases`, `Problem Codes`, `Complaint Qualifications`) into the
`Sheet1` layout of `data\input\salesforce.xlsx`: same 118 headers in the same order, one row
per case, columns without a source left blank.

## Prerequisites

- `cases.xlsx` should come from query `cq_crm_codes_nurse_call_no_comments` **v4 or later**, which
  adds `Description` and `LastModifiedDate`. Without them the `description`, parsed description
  columns (Contact Information, Location, Issue, Date/Time, GRS10 IP Address, Customer
  Troubleshooting, Additional Information, Patient Impact, Ticket) and `Update Timestamp`
  are blank. Re-run the `salesforce-export` skill with the latest version if needed.
- Optional KB corpus (`jira-rca-corpus` skill, `data\kb\<name>\articles.jsonl`) to fill
  `Reference Name` with the Care Comm KB article title found via the CQ URL.

## Procedure

```powershell
.\.venv\Scripts\python.exe -m complaint_analyzer.workflows.powerbi_export `
    --cases data\runs\<run>\cases.xlsx --kb-dir data\kb\<name>
```

Writes `powerbi.xlsx` next to `cases.xlsx` (override with `--out`; `--template` changes the header
source). Report the console line (case count, columns, KB titles) and any warning about dropped
extra problem codes / CQs (first problem code and latest CQ per case are used).

## Mapping notes

The mapping lives in `src\complaint_analyzer\workflows\powerbi_export\mapping.py`.

- Dates become `M/D/YYYY h:mm AM` (UTC as exported); `Update Timestamp` is `M/D/YYYY`.
- `PR ID` is the CQ TW complaint number; `Source Identifier*` is the case number.
- Paired CQ columns follow the legacy file: `RA_*` fields feed `test_inspection_troubleshooting`,
  `test_results_2`, `issue_cause`, `log_evidence_2`, `ra_actions_to_resolve`; `HRCSVC_*` fields feed
  `test_inspection_troubleshooting_2`, `test_results`, `issue_cause_2`, `log_evidence`, `actions_to_resolve_2`.
- `TRUE`/`FALSE` flags are written as booleans; `export_date` is the export time.
- Product-family / lot columns (`...^`) have no source in cases.xlsx and stay blank.
