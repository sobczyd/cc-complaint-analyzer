# case_summary changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts case_summary --changelog`. Do not edit by hand. -->

Concise structured summary of a single complaint / service case: what was reported, which product, actions taken, resolution and status, plus key points.

- Created: 2026-10-16
- Last updated: 2026-10-19
- Versions: 2

## v2 — 2026-10-19

**Summary:** Context-format prompt for cases rendered as column-name and value lines.

- File: `v2.txt`
- Based on: v1
- Author: Copilot (prompt-author)
- Result model: `CaseSummaryResult`

**Changes:**

- Describes the single Case Context block, its column-name and value lines, and multi-line values.
- Explains each of the nine context columns.
- Same JSON output and result model as v1.
- Adds key point guidance for repeat failures and a rule not to copy people's names.

**Prompt:**

> Summarize the cases from the October 2026 Nurse Call CQ fetch in batches of 20. Create a new prompt version that engineers the context format: use the fields CaseNumber, Subject, HRCSVC_Case_Resolution__c, HRCSVC_Product_Group__c, RA_Issue_Cause__c, RA_Actions_to_Resolve_Text__c, RA_Did_same_issue_occur__c, RA_Test_Inspection_Troubleshooting__c and RA_Test_Results__c for each case, and preface each field's contents with the Excel column name and a ":".

**Validation:** status `skipped`

_Not yet run against records._

## v1 — 2026-10-16

**Summary:** Initial case summary prompt with JSON-only output.

- File: `v1.txt`
- Author: copilot
- Result model: `CaseSummaryResult`

**Changes:**

- Initial version.

**Prompt:**

> Add a "case_summary" prompt alongside root cause analysis, tracked with versions, a manifest and a changelog like the query sets.

**Validation:** status `skipped`

_Not yet run against records._
