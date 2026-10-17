# nurse_call_last_7_days changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.queries nurse_call_last_7_days --changelog`. Do not edit by hand. -->

Last-7-day Salesforce Cases with the CareComm - Nurse Call complaint code, with the same case, account, asset, problem-code and complaint-qualification fields as cq_crm_codes_nurse_call_no_comments v2. Used by the daily Nurse Call review workflow.

- Created: 2026-10-16
- Last updated: 2026-10-16
- Versions: 1

## v1 — 2026-10-16

**Summary:** cq_crm_codes_nurse_call_no_comments v2 narrowed to Cases created in the last 7 days.

- File: `v1.txt`
- Author: Sobczynski
- Objects: `Case`, `Account`, `Asset`, `Problem_Codes__r`, `Complaint_Qualifications__r`

**Changes:**

- Initial version, copied from cq_crm_codes_nurse_call_no_comments v2.
- Filter changed from CreatedDate = LAST_N_DAYS:30 to CreatedDate = LAST_N_DAYS:7.
- Fields, subqueries, subquery filters and ordering are unchanged from the source query.

**Prompt:**

> Create a "last seven days" query that fetches the same fields and information as cq_crm_codes_nurse_call_no_comments v2, for a daily review of Nurse Call cases.

**Validation:** status `passed`, org `hillrom`, at 2026-10-16, 659 row(s)

_Ran with sf data query --file against the default target org; done=true, single page._
