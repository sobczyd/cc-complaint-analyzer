"""Map an exported ``cases.xlsx`` onto the ``data\\input\\salesforce.xlsx`` (Power BI) column layout."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from .derived import assessments
from .description import parse_description
from .serials import find_serials, pre_post_serials, serial_text

__all__ = ["DIRECT", "FALLBACKS", "build_row", "format_date", "format_datetime", "parse_description"]

# Target header -> (sheet, source column). Sheets: Cases, PC (Problem Codes), CQ (Complaint Qualifications).
DIRECT: dict[str, tuple[str, str]] = {
    "Source Identifier Raw": ("Cases", "CaseNumber"),
    "Source Identifier": ("Cases", "CaseNumber"),
    "assets_model_description": ("Cases", "HRCSVC_Asset_s_Model_Description__c"),
    "As Determined Problem Codes": ("PC", "ADPC_Name__c"),
    "As Reported Problem Code": ("PC", "ARPC_Name__c"),
    "As Determined Cause Codes": ("PC", "Cause_Code_Name__c"),
    "Component Code": ("PC", "Component_Name__c"),
    "code_list_by_product_problem_resolution_code_name": ("Cases", "HRCSVC_Complaint_Code__r.Name"),
    "case_owner": ("Cases", "Owner.Name"),
    "case_owner_2": ("Cases", "Owner.Name"),
    "Source State": ("Cases", "Status"),
    "business_hours_to_resolve": ("Cases", "HRCSVC_Business_Hours_to_Resolve__c"),
    "clock_hours_to_resolve": ("Cases", "HRCSVC_Clock_Hours_to_Resolve__c"),
    "is_complain_qualification_exist": ("Cases", "HRCSVC_Is_Complain_Qualification_Exist__c"),
    "part_serial_and_or_revision": ("CQ", "HRCSVC_Part_Serial_and_or_Revision__c"),
    "software_version": ("Cases", "HRCSVC_Software_Version__r.Name"),
    "source_subject": ("Cases", "Subject"),
    "description": ("Cases", "Description"),
    "describe_malfunction_event": ("CQ", "HRCSVC_Describe_Malfunction_Event__c"),
    "When did the Event or Product/Problem Malfunction Occur?": ("CQ", "HRCSVC_Process_Step__c"),
    "Was there patient/user injury, medical intervention, symptom or adverse event reported?": (
        "CQ",
        "HRCSVC_Injury_or_Death__c",
    ),
    "Was a second device also reported to be involved?": ("CQ", "HRCSVC_Second_device_involved__c"),
    "Was this event already communicated to any other Baxter department or authority?": (
        "CQ",
        "HRCSVC_Was_the_event_communicated__c",
    ),
    "Was product requested for service/inspection by Baxter?": ("CQ", "HRCSVC_Service_Requested_by_Baxter__c"),
    "complaint_qualification_number": ("CQ", "Name"),
    "Were there any System Alerts or other visual/ audible error indicators present prior?": (
        "CQ",
        "HRCSVC_Device_Message_Alert__c",
    ),
    "explain_log_evidence": ("CQ", "RA_Explain_Log_Evidence__c"),
    "test_inspection_troubleshooting": ("CQ", "RA_Test_Inspection_Troubleshooting__c"),
    "test_inspection_troubleshooting_2": ("CQ", "HRCSVC_Test_Inspection_Troubleshooting__c"),
    "test_results": ("CQ", "HRCSVC_Test_Results__c"),
    "test_results_2": ("CQ", "RA_Test_Results__c"),
    "issue_cause": ("CQ", "RA_Issue_Cause__c"),
    "issue_cause_2": ("CQ", "HRCSVC_Issue_Cause__c"),
    "actions_to_resolve": ("CQ", "HRCSVC_Actions_to_Resolve__c"),
    "actions_to_resolve_2": ("CQ", "RA_Actions_to_Resolve__c"),
    "ra_actions_to_resolve": ("CQ", "RA_Actions_to_Resolve_Text__c"),
    "did_same_issue_occur": ("CQ", "RA_Did_same_issue_occur__c"),
    "log_evidence": ("CQ", "HRCSVC_Log_Evidence__c"),
    "log_evidence_2": ("CQ", "RA_Log_Evidence__c"),
    "log_evidence_text": ("CQ", "HRCSVC_Log_Evidence_Text__c"),
    "log_evidence_text_2": ("CQ", "RA_Log_Evidence_Text__c"),
    "url": ("CQ", "HRCSVC21_URL__c"),
    "certification_date": ("CQ", "HRCSVC_Certification_Date__c"),
    "upgrade_date": ("CQ", "HRCSVC_Upgrade_Date__c"),
    "device_serviced": ("CQ", "HRCSVC_Device_Serviced__c"),
    "was_device_serviced": ("CQ", "HRCSVC_Was_device_serviced__c"),
    "code_list_by_product": ("CQ", "HRCSVC_Product_Group__c"),
    "code_list_by_product_2": ("CQ", "HRCSVC_Product_Group__c"),
    "account_name": ("Cases", "Account.Name"),
    "is_remote_assessment_required": ("Cases", "Is_Remote_Assessment_Required__c"),
    "is_dea_required": ("Cases", "Is_DEA_Required__c"),
    "facility_state_province": ("Cases", "Account.BillingState"),
    "facility_zip_postal_code": ("Cases", "Account.BillingPostalCode"),
    "rma": ("Cases", "RMA_Number__c"),
    "account_id": ("Cases", "Account.JDE_External_ID__c"),
    "case_resolution": ("Cases", "HRCSVC_Case_Resolution__c"),
    "case_resolution_2": ("Cases", "Case_Resolution_ReadOnly__c"),
}

# Target header -> sources tried in order; the first non-empty value wins.
FALLBACKS: dict[str, tuple[tuple[str, str], ...]] = {
    "asset_asset_name": (("PC", "Asset__r.Name"), ("Cases", "Asset.Name")),
    "main_sub_assembly": (
        ("CQ", "HRCSVC_Product_Feature_Component__c"),
        ("Cases", "HRCSVC_Main_Sub_Assembly__r.Name"),
    ),
    "udi": (("CQ", "HRCSVC_UDI__c"), ("Cases", "Asset.HRCFSL_UDI__c")),
    "work_order": (("CQ", "HRCSVC_Work_Order__r.WorkOrderNumber"), ("PC", "Work_Order__r.WorkOrderNumber")),
}

BOOLEAN_COLUMNS = {"is_complain_qualification_exist", "is_remote_assessment_required", "is_dea_required"}
NUMBER_COLUMNS = {"business_hours_to_resolve", "clock_hours_to_resolve"}
INTEGER_COLUMNS = {"PR ID", "udi"}
DATE_ONLY_COLUMNS = {"certification_date", "upgrade_date"}

# The dashboard pipeline reads its workbook with pandas, which turns these exact cell values into blanks.
NA_STRINGS = frozenset(
    {
        "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND", "1.#QNAN",
        "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
    }
)  # fmt: skip

REPORT_TIMEZONE = ZoneInfo("America/New_York")


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_timestamp(text: str) -> datetime | None:
    """Salesforce ``2026-10-01T00:16:39.000+0000`` (UTC) -> aware datetime in the report timezone."""
    try:
        parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).astimezone(REPORT_TIMEZONE)


def format_datetime(value: Any) -> str:
    """``2026-10-01T00:16:39.000+0000`` -> ``9/30/2026 8:16 PM`` (US Eastern, like the Salesforce report)."""
    text = _clean(value)
    if not text:
        return ""
    parsed = _parse_timestamp(text)
    if parsed is None:
        return text
    hour = parsed.hour % 12 or 12
    return f"{parsed.month}/{parsed.day}/{parsed.year} {hour}:{parsed.minute:02d} {'AM' if parsed.hour < 12 else 'PM'}"


def format_date(value: Any) -> str:
    """Timestamps convert to the US Eastern date; plain ``YYYY-MM-DD`` dates are kept as they are."""
    text = _clean(value)
    if not text:
        return ""
    parsed: date | datetime | None = _parse_timestamp(text) if "T" in text else None
    if parsed is None:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return text
    return f"{parsed.month}/{parsed.day}/{parsed.year}"


def _integer(text: str) -> Any:
    try:
        return int(float(text)) if "." in text else int(text)
    except ValueError:
        return text


def _typed(header: str, value: Any) -> Any:
    text = _clean(value)
    if not text:
        return None
    if header in BOOLEAN_COLUMNS and text.lower() in ("true", "false"):
        return text.lower() == "true"
    if header in NUMBER_COLUMNS:
        try:
            return float(text)
        except ValueError:
            return text
    if header in INTEGER_COLUMNS:
        return _integer(text)
    if header in DATE_ONLY_COLUMNS:
        return format_date(text)
    return text


def _blank_na(value: Any) -> Any:
    return None if isinstance(value, str) and value in NA_STRINGS else value


def build_row(
    headers: list[str],
    case: Mapping[str, Any],
    problem_code: Mapping[str, Any] | None,
    qualification: Mapping[str, Any] | None,
    *,
    kb_title: Callable[[str], str] = lambda url: "",
    export_date: datetime | None = None,
) -> list[Any]:
    """One output row, ordered like ``headers``; columns without a source stay empty.

    ``headers`` may include the ``SERIAL_COLUMNS`` appended after the template columns.
    """
    qualification = qualification or {}
    sheets = {"Cases": case, "PC": problem_code or {}, "CQ": qualification}
    values: dict[str, Any] = {
        header: _typed(header, sheets[sheet].get(column)) for header, (sheet, column) in DIRECT.items()
    }
    for header, sources in FALLBACKS.items():
        values[header] = next(
            (typed for sheet, column in sources if (typed := _typed(header, sheets[sheet].get(column))) is not None),
            None,
        )
    values["case_id"] = _clean(case.get("Id"))[:15] or None
    values["date_time_opened"] = format_datetime(case.get("CreatedDate")) or None
    values["date_time_closed"] = format_datetime(case.get("ClosedDate")) or None
    values["Update Timestamp"] = format_date(case.get("LastModifiedDate")) or None
    values["PR ID"] = _typed("PR ID", qualification.get("TW_Complaint_Number__c"))
    jde, account = _clean(case.get("Account.JDE_External_ID__c")), _clean(case.get("Account.Name"))
    values["Parent Asset"] = f"{jde}-{account}" if jde or account else None
    subject, description = _clean(case.get("Subject")), _clean(case.get("Description"))
    if subject or description:
        values["Source System Description"] = f"Subject:{subject}\tDescription:{description}"
    values["Reference Name"] = (
        _clean(qualification.get("HRCSVC_KB_Article__c")) or kb_title(_clean(qualification.get("HRCSVC21_URL__c"))) or None
    )
    if export_date:
        values["export_date"] = export_date
    values.update(parse_description(description))
    values = {header: _blank_na(value) for header, value in values.items()}
    values.update(assessments(values))

    text = serial_text(
        [description, case.get("Serial_Number_s__c"), qualification.get("HRCSVC_Part_Serial_and_or_Revision__c")]
    )
    values["serial_numbers"] = ", ".join(find_serials(text)) or None
    values.update(pre_post_serials(text, today=export_date))
    return [values.get(header) for header in headers]