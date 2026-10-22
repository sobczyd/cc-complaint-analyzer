# cq_crm_codes_nurse_call_no_comments changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.queries cq_crm_codes_nurse_call_no_comments --changelog`. Do not edit by hand. -->

Last-30-day Salesforce Cases with the CareComm - Nurse Call complaint code, with their Nurse Call problem codes and complaint qualifications. Case comments are deliberately excluded.

- Created: 2026-10-15
- Last updated: 2026-10-21
- Versions: 5

## v5 — 2026-10-21

**Summary:** Adds the complaint qualification fields needed for Power BI parity and returns the Service Requested picklist label.

- File: `v5.txt`
- Based on: v4
- Author: Sobczynski
- Objects: `Case`, `Account`, `Asset`, `Problem_Codes__r`, `Complaint_Qualifications__r`, `WorkOrder`

**Changes:**

- Complaint_Qualifications__r: HRCSVC_Service_Requested_by_Baxter__c now selected as toLabel(...) so the picklist label is returned.
- Complaint_Qualifications__r: added RA_Actions_to_Resolve__c (RA picklist, feeds actions_to_resolve_2).
- Complaint_Qualifications__r: added HRCSVC_KB_Article__c (feeds Reference Name).
- Complaint_Qualifications__r: added HRCSVC_UDI__c (feeds udi).
- Complaint_Qualifications__r: added HRCSVC_Work_Order__r.WorkOrderNumber (feeds work_order).
- Complaint_Qualifications__r: added HRCSVC_Product_Feature_Component__c (Main - Sub Assembly).
- Filters, other fields, subquery filters and ordering are unchanged from v4.

**Prompt:**

> For the generated powerbi.xlsx, use the attached field comparison Excel file to revise the powerbi-export skill to match data\input\salesforce.xlsx, specifically for cases which are already closed. Investigate columns with a value of Not Matched, consulting the trackforce-insight repository. (Plan: add the complaint qualification fields that feed UDI, Work Order, Main - Sub Assembly, KB Article and the RA Actions to Resolve picklist, and return the Service Requested by Baxter picklist label.)

**Validation:** status `passed`, org `hillrom`, at 2026-10-21T23:52:00Z, 5 row(s)

_Ran with sf data query --file and LIMIT 5 on the default target org; done=true._

## v4 — 2026-10-19

**Summary:** Adds the Case LastModifiedDate field to v3.

- File: `v4.txt`
- Based on: v3
- Author: Sobczynski
- Objects: `Case`, `Account`, `Asset`, `Problem_Codes__r`, `Complaint_Qualifications__r`

**Changes:**

- Case: added LastModifiedDate (placed after ClosedDate).
- Filters, subquery fields, subquery filters and ordering are unchanged from v3.

**Prompt:**

> The Power BI export needs the Last Modified Date of each case. Version the query to v4 to include it.

**Validation:** status `skipped`

_Single standard Case field added; not run against the org yet._

## v3 — 2026-10-19

**Summary:** Adds the Case Description field to v2.

- File: `v3.txt`
- Based on: v2
- Author: Sobczynski
- Objects: `Case`, `Account`, `Asset`, `Problem_Codes__r`, `Complaint_Qualifications__r`

**Changes:**

- Case: added Description (placed after Subject).
- Filters, subquery fields, subquery filters and ordering are unchanged from v2.

**Prompt:**

> The field "Description" is missing from v2. Version the query to v3 to include this field.

**Validation:** status `passed`, org `hillrom`, at 2026-10-19T19:54:00Z, 5 row(s)

_Ran with sf data query --file and LIMIT 5 on the default target org; done=true. Validated with the sf CLI because the salesforce-local MCP tools were unavailable._

## v2 — 2026-10-15

**Summary:** Adds account, asset, software, resolution and detailed investigation fields to v1.

- File: `v2.txt`
- Based on: v1
- Author: Sobczynski
- Objects: `Case`, `Account`, `Asset`, `Problem_Codes__r`, `Complaint_Qualifications__r`

**Changes:**

- Case: added Account.BillingState, Account.BillingPostalCode, Account.JDE_External_ID__c.
- Case: added Serial_Number_s__c, HRCSVC_Asset_s_Model_Description__c, Asset.Name, Asset.SerialNumber, Asset.HRCFSL_UDI__c.
- Case: added HRCSVC_Software_Version__r.Name and HRCSVC_Main_Sub_Assembly__r.Name.
- Case: added DEA_Exists__c, Is_DEA_Required__c, Is_Remote_Assessment_Required__c, HRCSVC_Case_Resolution__c, Case_Resolution_ReadOnly__c.
- Problem_Codes__r: added Cause_Code_Name__c, Component_Name__c, ADC_Name__c, ADPC_Name__c, ARPC_Name__c, ARPC_Complaint__c, DVAD__c.
- Complaint_Qualifications__r: added URL, certification/upgrade dates, part serial, malfunction description, process step, injury/death, second device, communication, Baxter service request, occupation, device alert, and the RA_* / log-evidence / test-inspection / test-result fields.
- Filters, subquery filters and ordering are unchanged from v1.

**Prompt:**

> Extend v1 with account location and JDE ID, asset and software details, DEA and remote-assessment flags, case resolution, problem-code names, and the full set of complaint-qualification RA/investigation fields, still without case comments. (Reconstructed from the query and commit 23200ba.)

**Validation:** status `skipped`

_Backfilled when manifest tracking was introduced; no validation run was recorded._

## v1 — 2026-10-15

**Summary:** Core Nurse Call complaint Cases with problem codes and complaint qualifications.

- File: `v1.txt`
- Author: Sobczynski
- Objects: `Case`, `Problem_Codes__r`, `Complaint_Qualifications__r`

**Changes:**

- Initial version.
- Case identity, status, owner, account name, resolve-time hours and RMA number.
- Problem_Codes__r subquery (cause, component, as-determined and as-reported codes) filtered to the CareComm - Nurse Call product family.
- Complaint_Qualifications__r subquery (status, TW complaint number, issue cause, actions to resolve) filtered to the CareComm - Nurse Call product group.
- Filter on CreatedDate = LAST_N_DAYS:30 and complaint code CareComm - Nurse Call, newest first.

**Prompt:**

> Pull Cases from the last 30 days with the CareComm - Nurse Call complaint code, including their Nurse Call problem codes and complaint qualifications, without case comments. (Reconstructed from the query and commit 23200ba.)

**Validation:** status `skipped`

_Backfilled when manifest tracking was introduced; no validation run was recorded._
