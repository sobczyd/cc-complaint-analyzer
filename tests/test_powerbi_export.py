from datetime import date, datetime

from openpyxl import Workbook

from complaint_analyzer.workflows.powerbi_export.compare import compare, normalize, split_answers, values_match
from complaint_analyzer.workflows.powerbi_export.derived import (
    DEVICE_EVALUATION_ASSESSMENT,
    REMOTE_ASSESSMENT,
    assessments,
)
from complaint_analyzer.workflows.powerbi_export.description import parse_description
from complaint_analyzer.workflows.powerbi_export.mapping import build_row, format_date, format_datetime
from complaint_analyzer.workflows.powerbi_export.package import dim_serial_rows
from complaint_analyzer.workflows.powerbi_export.serials import (
    SERIAL_COLUMNS,
    age_category,
    classify_serials,
    find_serials,
    months_since_1970,
    pre_post_serials,
    serial_wwyy,
    week_monday,
)

DESCRIPTION = """Contact Information:    Mike Kazeem, 317-832-3084
Location:    5 East
Request/Issue:     Lost Unit Server
Date/Time:  07-20-26, 11:45pm EDT
GRS10 IP Address:    Not provided
Customer troubleshooting:   Rebooted console
and it displayed a message
Additional information:   Power outage last Friday
Patient Impact (Yes/No): None reported
Internal Ticket Number: Customer did not provide one"""


def test_parse_description_labels_and_continuations():
    fields = parse_description(DESCRIPTION)
    assert fields["Contact Information"] == "Mike Kazeem, 317-832-3084"
    assert fields["Issue"] == "Lost Unit Server"
    assert fields["Customer Troubleshooting"] == "Rebooted console\nand it displayed a message"
    # Trackforce quirk kept for parity: "Ticket Number:" is matched mid-line, so "Internal" stays behind.
    assert fields["Patient Impact"] == "None reported\nInternal"
    assert fields["Ticket"] == "Customer did not provide one"
    assert fields["source_description"] is None


def test_parse_description_trackforce_boundaries():
    """The ``--verify`` cases of trackforce-insight's parse_case_description.py."""
    cases = [
        ("Description: alarm on panel\nDate/Time: 1/1/2026", "alarm on panel", None),
        ("Description: line1\nline2\nFacility: Building A\nDate/Time: 1/1/2026", "line1\nline2", None),
        ("Description: swap unit\nLocation Scope: ICU\nDate/Time: 1/1/2026", "swap unit", None),
        ("Description: old device\nOld SN: ABC123\nDate/Time: 1/1/2026", "old device", None),
        ("Issue: battery dead\nDate/Time: 1/1/2026", None, "battery dead"),
        ("Problem/Request Description: xyz\nDate/Time: 1/1/2026", None, "xyz"),
        ("alarm on panel with no labels", "alarm on panel with no labels", None),
    ]
    for text, source_description, issue in cases:
        fields = parse_description(text)
        assert (fields["source_description"], fields["Issue"]) == (source_description, issue), text


def test_parse_description_midline_serials_and_bare_ticket():
    fields = parse_description("IP Address: 172.21.4.78 grs10 serial: 0032108FWIS\nOld SN: 1\nSee INC1234567")
    assert fields["GRS10 IP Address"] == "172.21.4.78"
    assert fields["Serial Number"] == "grs10 serial: 0032108FWIS\nOld SN: 1\nSee INC1234567"
    assert fields["Ticket"] == "INC1234567"


def test_date_formats_use_us_eastern_with_dst():
    assert format_datetime("2026-07-21T00:46:00.000+0000") == "7/20/2026 8:46 PM"
    assert format_datetime("2026-07-28T13:31:00.000+0000") == "7/28/2026 9:31 AM"
    assert format_datetime("2026-12-01T13:31:00.000+0000") == "12/1/2026 8:31 AM"
    assert format_date("2026-10-01T02:00:00.000+0000") == "9/30/2026"
    assert format_date("2026-07-28") == "7/28/2026"


def test_build_row_follows_header_order_and_types():
    headers = ["case_id", "is_dea_required", "clock_hours_to_resolve", "PR ID", "Issue", "Reference Name", "Unmapped^"]
    row = build_row(
        headers,
        {
            "Id": "500Ho00001Xo6ZNIAZ",
            "Is_DEA_Required__c": "False",
            "HRCSVC_Clock_Hours_to_Resolve__c": "1.81",
            "Description": DESCRIPTION,
        },
        None,
        {"TW_Complaint_Number__c": "7060141.0", "HRCSVC21_URL__c": "u"},
        kb_title=lambda url: "KB title" if url == "u" else "",
        export_date=datetime(2026, 1, 1),
    )
    assert row == ["500Ho00001Xo6ZN", False, 1.81, 7060141, "Lost Unit Server", "KB title", None]


def test_build_row_cq_first_sources_and_actions():
    headers = [
        "asset_asset_name",
        "udi",
        "work_order",
        "main_sub_assembly",
        "Reference Name",
        "actions_to_resolve",
        "actions_to_resolve_2",
        "Parent Asset",
    ]
    case = {"Asset.Name": "Case asset", "Asset.HRCFSL_UDI__c": "1", "HRCSVC_Main_Sub_Assembly__r.Name": "Case MSA"}
    code = {"Asset__r.Name": "PC asset", "Work_Order__r.WorkOrderNumber": "WO-PC", "Account.Name": "x"}
    cq = {
        "HRCSVC_UDI__c": "00887761979017",
        "HRCSVC_Work_Order__r.WorkOrderNumber": "WO-CQ",
        "HRCSVC_Product_Feature_Component__c": "RCB",
        "HRCSVC_KB_Article__c": "No KB Required",
        "HRCSVC21_URL__c": "u",
        "HRCSVC_Actions_to_Resolve__c": "Replaced RCB",
        "RA_Actions_to_Resolve__c": "Resolved",
    }
    row = build_row(headers, case, code, cq, kb_title=lambda url: "KB title")
    assert row == ["PC asset", 887761979017, "WO-CQ", "RCB", "No KB Required", "Replaced RCB", "Resolved", None]
    fallback = build_row(headers, case, {"Work_Order__r.WorkOrderNumber": "WO-PC"}, {"HRCSVC21_URL__c": "u"}, kb_title=lambda url: "KB title")
    assert fallback == ["Case asset", 1, "WO-PC", "Case MSA", "KB title", None, None, None]


def test_build_row_blanks_pandas_na_strings():
    headers = ["Patient Impact", "Ticket", "rma", "Location"]
    row = build_row(
        headers,
        {"Description": "Patient Impact: N/A\nInternal Ticket: None\nLocation: NA ward", "RMA_Number__c": "n/a"},
        None,
        None,
    )
    assert row == [None, None, None, "NA ward"]


def test_assessments_follow_trackforce_layout():
    blocks = assessments(
        {
            "test_inspection_troubleshooting": "RA steps",
            "test_inspection_troubleshooting_2": "DEA steps",
            "test_results": "Pass",
            "issue_cause": "Cable",
            "actions_to_resolve": "Replaced",
            "ra_actions_to_resolve": None,
            "did_same_issue_occur": "No",
            "was_device_serviced": "Yes",
            "log_evidence": None,
        }
    )
    assert blocks[REMOTE_ASSESSMENT] == (
        "What troubleshooting/Inspection was performed for the issue(s):RA steps\n"
        "What were the results of troubleshooting/Inspection?:Pass\n"
        "What is the cause/causes of the issue:Cable\n"
        "What are the actions needed to resolve the issue(s):Replaced:\n"
        "Did same issue occur within the last 30 days in the same location/unit?:No\n"
        "Did review of the customer device log reveal evidence of the customer reported problem(s)?:\n"
    )
    assert blocks[DEVICE_EVALUATION_ASSESSMENT].startswith(
        "What testing, inspection, and/or troubleshooting was performed for the issue(s):DEA steps\n"
    )
    assert "What are the actions needed to resolve the issue(s)::Replaced:\n" in blocks[DEVICE_EVALUATION_ASSESSMENT]
    assert "past 12 months for the same problem(s)?:Yes\n" in blocks[DEVICE_EVALUATION_ASSESSMENT]


def test_find_serials_skips_accounts_dates_and_part_numbers():
    text = "Account 633518CC on 050925DT, part 2168B. SN NEW - 26261F1WM2 / SN OLD - 062618PWM2; again 26261f1wm2"
    assert find_serials(text) == ["26261F1WM2", "062618PWM2"]


def test_pre_post_serials_from_description():
    values = pre_post_serials("SN NEW - 26261F1WM2 / SN OLD - 062618PWM2", current_yy=26)
    assert list(values) == list(SERIAL_COLUMNS)
    assert values["pre_sn"] == "062618PWM2" and values["pre_sn_date"] == "0626"
    assert values["post_sn"] == "26261F1WM2" and values["post_sn_date"] == "2626"
    assert values["pre_sn_date_wwyy"] == date(2026, 2, 2)
    assert values["post_sn_date_wwyy"] == date(2026, 6, 22)
    previous = pre_post_serials("Previous RCB SN: 3918291WIS\nNew RCB SN: 492417KWM2", current_yy=26)
    assert (previous["pre_sn"], previous["post_sn"]) == ("3918291WIS", "492417KWM2")
    empty = dict.fromkeys(SERIAL_COLUMNS) | {
        "new_serial_numbers": "402017LWIS",
        "current_year": date.today().year,
        "current_months_since_1970": months_since_1970(date.today()),
    }
    assert pre_post_serials("New SN: 402017LWIS", current_yy=26) == empty


def test_classify_serials_by_preceding_keyword():
    text = "402017LWIS first. OLD: 062618PWM2, 0819028WIS new 26261F1WM2 NEW- 492417KWM2 Previous 3918291WIS\nlater 111111AWIS"
    assert classify_serials("402017LWIS only") == ([], [])
    old, new = classify_serials(text)
    assert old == ["062618PWM2", "0819028WIS", "3918291WIS"]
    assert new == ["26261F1WM2", "492417KWM2"]
    assert classify_serials("402017LWIS then old 062618PWM2") == (["062618PWM2"], [])
    values = pre_post_serials(text, today=date(2026, 10, 23))
    assert values["old_serial_numbers"] == "062618PWM2, 0819028WIS, 3918291WIS"
    assert values["new_serial_numbers"] == "26261F1WM2, 492417KWM2"


def test_dim_serial_rows_explode_and_dedupe():
    fact = [
        {
            "Source Identifier Raw": "01", "old_serial_numbers": "062618PWM2, 0819028WIS",
            "new_serial_numbers": "26261F1WM2, 062618PWM2", "pre_sn": "062618PWM2", "post_sn": "26261F1WM2",
            "pre_sn_date_wwyy": datetime(2026, 2, 2),
        },
        {"Source Identifier Raw": "02", "old_serial_numbers": "062618PWM2, 062618PWM2", "new_serial_numbers": None},
    ]
    rows = dim_serial_rows(fact, today=date(2026, 10, 23))
    assert [(r["Source Identifier Raw"], r["sn_type"], r["serial_number"]) for r in rows] == [
        ("01", "old", "062618PWM2"), ("01", "old", "0819028WIS"), ("01", "new", "26261F1WM2"),
        ("01", "new", "062618PWM2"), ("02", "old", "062618PWM2"),
    ]
    assert rows[0]["pre_sn_date_wwyy"] == date(2026, 2, 2) and rows[0]["sn_age_in_months"] == 8
    assert rows[0]["sn_age_category"] == "within warranty"


def test_derived_age_columns():
    values = pre_post_serials("SN NEW - 26261F1WM2 / SN OLD - 062618PWM2", today=date(2026, 10, 23))
    assert values["pre_sn_date_year"] == 2026 and values["post_sn_date_year"] == 2026
    assert values["current_year"] == 2026 and values["pre_sn_age_in_years"] == 0
    assert values["pre_sn_age_in_months_since_1970"] == 56 * 12 + 1
    assert values["current_months_since_1970"] == 56 * 12 + 9
    assert values["pre_sn_age_in_months"] == 8 and values["pre_sn_age_category"] == "within warranty"
    old = pre_post_serials("old 011014PWM2 new 01241PWM2", today=date(2026, 10, 23))
    assert old["pre_sn_age_in_years"] == 16 and old["post_sn_age_in_years"] == 2
    assert old["pre_sn_age_category"] == "beyond expected life"
    assert [age_category(n) for n in (18, 19, 60, 61, None)] == [
        "within warranty", "within service life", "within service life", "beyond expected life", None,
    ]


def test_serial_wwyy_windows():
    assert serial_wwyy("0819028WIS", current_yy=26) == "0819"
    assert serial_wwyy("0102501PWM2", current_yy=26) == "1025"
    assert serial_wwyy("048174X8WIS", current_yy=26) == "4817"
    assert serial_wwyy("0022018UWIS", current_yy=26) == "0220"
    assert serial_wwyy("00121WIS", current_yy=26) == "0121"
    assert serial_wwyy("00150WIS", current_yy=26) == "0015"
    assert week_monday("5325") is None
    assert week_monday("0102") == date(2001, 12, 31)


def test_build_row_appends_serial_columns():
    headers = ["serial_numbers", *SERIAL_COLUMNS]
    row = build_row(
        headers,
        {"Description": "Old SN: 4020142WIS", "Serial_Number_s__c": "new 042516TWM2"},
        None,
        {"HRCSVC_Part_Serial_and_or_Revision__c": "4020142WIS"},
    )
    assert row[:8] == [
        "4020142WIS, 042516TWM2", "4020142WIS", "042516TWM2", "4020142WIS", "4020", "042516TWM2", "0425", date(2020, 9, 28),
    ]


def test_compare_normalization_and_truncation():
    assert normalize("a_x000D_\nb   c") == "a b c"
    assert normalize("N/A") == "" and normalize(7060141.0) == "7060141" and normalize("12.0") == "12"
    long = "x" * 300
    assert values_match(long, long[:255])
    assert not values_match(long, long[:100])
    questions = ("Q1", "Q2")
    assert split_answers("Q1:a\nQ2:b\n", questions) == ["a\n", "b\n"]


def test_compare_assessment_answers_with_truncated_fields():
    from complaint_analyzer.workflows.powerbi_export.derived import _RA_QUESTIONS

    full = assessments({"test_inspection_troubleshooting": "y" * 400})[REMOTE_ASSESSMENT]
    cut = assessments({"test_inspection_troubleshooting": "y" * 255})[REMOTE_ASSESSMENT]
    assert len(split_answers(full, _RA_QUESTIONS)) == 6
    assert values_match(full, cut, REMOTE_ASSESSMENT)
    assert not values_match(full, cut, "description")


def _book(path, headers, rows):
    book = Workbook()
    book.active.append(headers)
    for row in rows:
        book.active.append(row)
    book.save(path)


def test_compare_closed_cases(tmp_path):
    headers = ["Source Identifier Raw", "Source State", "case_id", "Customer", "serial_numbers"]
    _book(tmp_path / "ours.xlsx", headers, [["01", "Closed", "a", None, "1234AWIS"], ["02", "Open", "b", None, None]])
    _book(tmp_path / "dash.xlsx", headers, [["01", "Closed", "a", "X", None], ["02", "Open", "c", None, None]])
    result = compare(tmp_path / "ours.xlsx", tmp_path / "dash.xlsx")
    assert result["cases"] == 1 and result["overlap"] == 2
    status = {row["column"]: row["status"] for row in result["columns"]}
    assert status == {
        "Source Identifier Raw": "Matched",
        "Source State": "Matched",
        "case_id": "Matched",
        "Customer": "Unsourced",
        "serial_numbers": "Derived",
    }
    assert compare(tmp_path / "ours.xlsx", tmp_path / "dash.xlsx", state=None)["cases"] == 2
