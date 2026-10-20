from datetime import datetime

from complaint_analyzer.workflows.powerbi_export.mapping import (
    build_row,
    format_date,
    format_datetime,
    parse_description,
)

DESCRIPTION = """Contact Information:    Mike Kazeem, 317-832-3084
Location:    5 East
Request/Issue:     Lost Unit Server
Date/Time:  07-20-26, 11:45pm EDT
GRS10 IP Address:    Not provided
Customer troubleshooting:   Rebooted console
and it displayed a message
Additional information:   Power outage last Friday
Patient Impact Yes* / No: None reported
Internal Ticket Number: Customer did not provide one"""


def test_parse_description_labels_and_continuations():
    fields = parse_description(DESCRIPTION)
    assert fields["Contact Information"] == "Mike Kazeem, 317-832-3084"
    assert fields["Issue"] == "Lost Unit Server"
    assert fields["Customer Troubleshooting"] == "Rebooted console\nand it displayed a message"
    assert fields["Patient Impact"] == "None reported"
    assert fields["Ticket"] == "Customer did not provide one"


def test_date_formats():
    assert format_datetime("2026-07-21T00:46:00.000+0000") == "7/21/2026 12:46 AM"
    assert format_datetime("2026-07-28T13:31:00.000+0000") == "7/28/2026 1:31 PM"
    assert format_date("2026-07-28T13:31:00.000+0000") == "7/28/2026"


def test_build_row_follows_header_order_and_types():
    headers = ["case_id", "is_dea_required", "clock_hours_to_resolve", "PR ID", "Issue", "Reference Name", "Unmapped^"]
    row = build_row(
        headers,
        {"Id": "500", "Is_DEA_Required__c": "False", "HRCSVC_Clock_Hours_to_Resolve__c": "1.81", "Description": DESCRIPTION},
        None,
        {"TW_Complaint_Number__c": "7060141.0", "HRCSVC21_URL__c": "u"},
        kb_title=lambda url: "KB title" if url == "u" else "",
        export_date=datetime(2026, 1, 1),
    )
    assert row == ["500", False, 1.81, "7060141", "Lost Unit Server", "KB title", None]
