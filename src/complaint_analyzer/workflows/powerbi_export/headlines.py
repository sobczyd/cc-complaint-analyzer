"""Short "Issue Group" headline for each Resolved cluster, chosen by ordered regex rules.

First matching rule wins, so order matters. When a new Resolved cluster shows up and gets "Unmapped"
(listed in the package warnings), add a rule here.
"""
from __future__ import annotations

import re

UNMAPPED = "Unmapped"

_RULES: list[tuple[str, str]] = [
    (r"pillow|peripheral", "Bed peripherals"),
    (r"\brtls\b|locating", "RTLS"),
    (r"\bdome\b|\blights?\b", "Dome Lights"),
    (r"reboot", "Reboots"),
    (r"replac", "Device Replacements"),
    (r"no fault|expected behavio", "No Issue Found"),
    (r"insufficient|\bclosed\b", "Inconclusive"),
    (r"voice|audio|voip", "Audio Issues"),
    (r"cabling|\bports?\b|call switch", "Cabling"),
    (r"server services|restart", "Service Restarts"),
    (r"configuration|\bect\b|provisioning", "Configuration"),
    (r"stuck|spurious", "Stuck Calls"),
    (r"status board|bed data", "Status Board & Bed Data"),
    (r"informational|security", "Informational"),
    (r"frozen|recovery mode", "Frozen Screen"),
    (r"user access|login", "User Access & Login"),
    (r"integration|messaging", "Integration & Messaging"),
    (r"database|capacity|upgrade", "Database"),
    (r"software|version", "Software Errors"),
    (r"not reaching|not alerting|\balerts?\b", "Alert Issues"),
    (r"network|infrastructure|\bpower\b", "Network & Infrastructure"),
]
_COMPILED = [(re.compile(pattern, re.IGNORECASE), headline) for pattern, headline in _RULES]


def issue_group(resolved_cluster: str) -> str:
    text = (resolved_cluster or "").strip()
    if not text:
        return ""
    for pattern, headline in _COMPILED:
        if pattern.search(text):
            return headline
    return UNMAPPED
