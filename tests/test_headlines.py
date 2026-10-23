import pytest

from complaint_analyzer.workflows.powerbi_export.headlines import UNMAPPED, issue_group

CASES = [
    ("Network, power and infrastructure faults", "Network & Infrastructure"),
    ("Voice path, audio and VoIP faults", "Audio Issues"),
    ("Failed room device replaced", "Device Replacements"),
    ("No fault found or expected behavior", "No Issue Found"),
    ("Cabling, port and call switch faults", "Cabling"),
    ("Server services and restarts", "Service Restarts"),
    ("Configuration, ECT and provisioning changes", "Configuration"),
    ("Lost device alerts and reboot fixes", "Reboots"),
    ("Stuck and spurious calls", "Stuck Calls"),
    ("Insufficient information or closed", "Inconclusive"),
    ("RTLS locating failures", "RTLS"),
    ("Dome and room light faults", "Dome Lights"),
    ("Alerts not reaching wireless devices", "Alert Issues"),
    ("Status board and bed data issues", "Status Board & Bed Data"),
    ("Informational and security inquiries", "Informational"),
    ("Frozen screens and recovery mode", "Frozen Screen"),
    ("Replacement requests and onsite handling", "Device Replacements"),
    ("User access and client login", "User Access & Login"),
    ("Integration and messaging errors", "Integration & Messaging"),
    ("Database, capacity and upgrade issues", "Database"),
    ("Pillow speaker, bed and room peripherals", "Bed peripherals"),
    ("Software errors and version issues", "Software Errors"),
    ("Calls not alerting or reaching endpoints", "Alert Issues"),
    ("", ""),
    ("Something brand new", UNMAPPED),
]


@pytest.mark.parametrize("cluster,expected", CASES)
def test_issue_group(cluster, expected):
    assert issue_group(cluster) == expected
