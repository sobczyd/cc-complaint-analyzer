"""Split a case ``Description`` into the dashboard's canonical sub-fields.

Port of ``scripts/dev/preprocess/parse_case_description.py`` from ``sobczyd/trackforce-insight``,
which builds the parsed description columns of ``data\\input\\salesforce.xlsx``.
"""

from __future__ import annotations

import re

CONTACT_INFORMATION = "Contact Information"
PHONE = "Phone"
LOCATION = "Location"
ROOM = "Room"
ISSUE = "Issue"
SOURCE_DESCRIPTION = "source_description"
DATE_TIME = "Date/Time"
IP_ADDRESS = "GRS10 IP Address"
CUSTOMER_TROUBLESHOOTING = "Customer Troubleshooting"
ADDITIONAL_INFORMATION = "Additional Information"
SERIAL_NUMBER = "Serial Number"
PATIENT_IMPACT = "Patient Impact"
TICKET = "Ticket"
ACCOUNT_NUMBER = "Account Number"

CANONICAL_FIELDS: tuple[str, ...] = (
    CONTACT_INFORMATION,
    PHONE,
    LOCATION,
    ROOM,
    ISSUE,
    SOURCE_DESCRIPTION,
    DATE_TIME,
    IP_ADDRESS,
    CUSTOMER_TROUBLESHOOTING,
    ADDITIONAL_INFORMATION,
    SERIAL_NUMBER,
    PATIENT_IMPACT,
    TICKET,
    ACCOUNT_NUMBER,
)

_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CONTACT_INFORMATION,
        ("Contact Information", "Contact Info", "Contact", "POC", "On-site Contact", "First Name", "Last Name"),
    ),
    (PHONE, ("Phone", "Phone (with area code)", "Cell")),
    (LOCATION, ("Location", "Location Scope", "Facility", "Department", "Floor", "Unit")),
    (ROOM, ("Room", "Rooms")),
    (
        ISSUE,
        (
            "Issue",
            "Request/Issue",
            "Issue/request",
            "Request",
            "Problem/Request Description",
            "User Experience",
            "Error",
        ),
    ),
    (SOURCE_DESCRIPTION, ("Description",)),
    (DATE_TIME, ("Date/Time", "Occurrence Date/Time", "Time/Date", "Date/Time/Frequency", "Date")),
    (
        IP_ADDRESS,
        (
            "GRS10 IP Address",
            "GRS10 IP",
            "IP Address",
            "Main GRS10 IP",
            "Room IP",
            "Wall unit IP address",
            "Nurse call unit IP address",
            "Device URI",
            "URI",
            "MAC",
        ),
    ),
    (
        CUSTOMER_TROUBLESHOOTING,
        ("Customer Troubleshooting", "Customer troubleshooting", "Troubleshooting", "Troubleshooting steps taken"),
    ),
    (ADDITIONAL_INFORMATION, ("Additional Information", "Background", "New Link")),
    (
        SERIAL_NUMBER,
        (
            "SN",
            "Old SN",
            "New SN",
            "Old Serial Number",
            "New Serial Number",
            "Serial Number",
            "SRS Old SN",
            "OLD SRS",
            "NEW SRS",
            "Model",
            "old grs5",
            "new grs7",
            "grs10 serial",
        ),
    ),
    (
        PATIENT_IMPACT,
        (
            "Patient Impact",
            "Patient Impact Yes / No",
            "Patient Impact(yes/no)",
            "Patient Impact (Yes/No)",
            "Patient Impact (yes/no)",
        ),
    ),
    (TICKET, ("INC", "INC #", "Internal Ticket", "Ticket number")),
    (ACCOUNT_NUMBER, ("Account", "Account Number", "Account/Organization Name")),
)

ALIASES: dict[str, str] = {
    alias.lower(): canonical for canonical, aliases in _ALIAS_GROUPS for alias in aliases
}

# Identifier-style fields also appear mid-line, e.g. "IP Address: 172.21.4.78 grs10 serial: 0032108FWIS".
_MIDLINE_FIELDS = frozenset({IP_ADDRESS, SERIAL_NUMBER, TICKET})

_SN = r"(?:sn|s/n|serial(?:\s*(?:number|no\.?))?)"
_DEVICE = r"(?:srs|rcb|grs\d*|wm\d*)"
_SERIAL_LABEL_PATTERNS: tuple[str, ...] = (
    rf"(?:srs\s+)?(?:old|new)\s+(?:[A-Za-z0-9]{{1,12}}\s+)?{_SN}",
    rf"(?:old|new)\s+{_DEVICE}",
    rf"[A-Za-z0-9]{{1,12}}\s+{_SN}",
    r"old|new",
)
# Only the bare "Old:" / "New:" form is value-checked, so prose is not mistaken for a serial.
_GUARDED_SERIAL_PATTERN = _SERIAL_LABEL_PATTERNS[-1]
_SERIAL_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{3,}$")

_LABEL_RE = re.compile(
    r"(?P<label>"
    + "|".join(
        [re.escape(alias) for alias in sorted(ALIASES, key=len, reverse=True)]
        + [f"(?:{pattern})" for pattern in _SERIAL_LABEL_PATTERNS]
    )
    + r")"
    r"\s*:",
    re.IGNORECASE,
)
_LINE_START_RE = re.compile(r"(?:^|[\n\r\t])[ \t>*\-\u2022]*$")
_BARE_INC_RE = re.compile(r"\bINC\d{6,}\b", re.IGNORECASE)


def canonical_for_label(label: str) -> tuple[str | None, bool]:
    """Canonical field for a label, plus whether its value needs a serial guard."""
    exact = ALIASES.get(label.lower())
    if exact is not None:
        return exact, False
    for pattern in _SERIAL_LABEL_PATTERNS:
        if re.fullmatch(pattern, label, re.IGNORECASE):
            return SERIAL_NUMBER, pattern == _GUARDED_SERIAL_PATTERN
    return None, False


def _looks_like_serial(value: str) -> bool:
    return bool(_SERIAL_VALUE_RE.match(value)) and any(ch.isdigit() for ch in value)


def _at_line_start(text: str, pos: int) -> bool:
    return pos == 0 or bool(_LINE_START_RE.search(text[:pos]))


def parse_description(text: object) -> dict[str, str | None]:
    """Split one description into the canonical fields by scanning known labels."""
    fields: dict[str, str | None] = dict.fromkeys(CANONICAL_FIELDS)
    if text is None or not str(text).strip():
        return fields

    body = str(text)
    matches: list[tuple[int, int, str, str, bool]] = []
    for match in _LABEL_RE.finditer(body):
        label = match.group("label")
        canonical, guarded = canonical_for_label(label)
        if canonical is None:
            continue
        if not _at_line_start(body, match.start()) and canonical not in _MIDLINE_FIELDS:
            continue
        matches.append((match.start(), match.end(), label, canonical, guarded))

    # A guarded label whose value is not serial-shaped stays part of the preceding field.
    kept = [
        entry
        for index, entry in enumerate(matches)
        if not entry[4]
        or _looks_like_serial(body[entry[1] : matches[index + 1][0] if index + 1 < len(matches) else len(body)].strip())
    ]

    collected: dict[str, list[tuple[str, str]]] = {}
    for index, (_, value_start, label, canonical, _guarded) in enumerate(kept):
        value_end = kept[index + 1][0] if index + 1 < len(kept) else len(body)
        value = body[value_start:value_end].strip()
        if value:
            collected.setdefault(canonical, []).append((label, value))

    for canonical, entries in collected.items():
        # Repeated labels (Old SN / New SN, several IPs) share one cell and keep their labels.
        if len(entries) == 1:
            fields[canonical] = entries[0][1]
        else:
            fields[canonical] = "\n".join(f"{label}: {value}" for label, value in entries)

    if fields[TICKET] is None:
        bare = _BARE_INC_RE.search(body)
        if bare:
            fields[TICKET] = bare.group(0)

    if all(value is None for value in fields.values()):
        fields[SOURCE_DESCRIPTION] = body.strip()
    return fields
