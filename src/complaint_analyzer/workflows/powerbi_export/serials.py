"""Serial-number extraction for the Power BI export.

``serial_numbers`` lists every Nurse Call serial cited in the case. ``pre_sn`` / ``post_sn`` are the
old (replaced) and new (installed) serials, adapted from the historical
``extract_pre_post_serials_from_description``: the serial following "old" (without crossing "new")
and the serial following "new" (without crossing "old"). Their first four digits are the
manufacturing week/year (WWYY, see ``serial_wwyy``), and ``*_date_wwyy`` is the Monday of that ISO week.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable

SERIAL_COLUMNS: tuple[str, ...] = (
    "old_serial_numbers",
    "new_serial_numbers",
    "pre_sn",
    "pre_sn_date",
    "post_sn",
    "post_sn_date",
    "pre_sn_date_wwyy",
    "post_sn_date_wwyy",
    "pre_sn_date_year",
    "post_sn_date_year",
    "current_year",
    "pre_sn_age_in_years",
    "post_sn_age_in_years",
    "pre_sn_age_in_months_since_1970",
    "post_sn_age_in_months_since_1970",
    "current_months_since_1970",
    "pre_sn_age_in_months",
    "pre_sn_age_category",
)
DATE_COLUMNS: tuple[str, ...] = ("pre_sn_date_wwyy", "post_sn_date_wwyy")


def months_since_1970(value: date) -> int:
    return (value.year - 1970) * 12 + value.month - 1


def age_category(age_in_months: int | None) -> str | None:
    if age_in_months is None:
        return None
    if age_in_months <= 18:
        return "within warranty"
    if age_in_months <= 60:
        return "within service life"
    return "beyond expected life"

# "old" widened with the other words used for the replaced device ("Previous RCB SN: ...").
OLD_TOKEN = r"(?<![A-Za-z])(?:old|previous|original|existing)(?![A-Za-z])"
NEW_TOKEN = r"(?<![A-Za-z])new(?![A-Za-z])"
# Widened from the historical (\d+[A-Z]+), which cut "26261F1WM2" to "26261F". The WIS / WM<n>
# suffix covers every serial in the dashboard descriptions and skips account ids (<JDE>CC), dates
# (050925DT) and part numbers (2168B).
SN_TOKEN = r"(?<![A-Za-z0-9])(\d{4,9}[A-Z0-9]{0,3}W(?:IS|M\d))(?![A-Za-z0-9])"

SERIAL_RE = re.compile(SN_TOKEN, re.IGNORECASE)
PRE_SN_RE = re.compile(rf"(?is){OLD_TOKEN}(?:(?!{NEW_TOKEN}).)*?{SN_TOKEN}")
POST_SN_RE = re.compile(rf"(?is){NEW_TOKEN}(?:(?!{OLD_TOKEN}).)*?{SN_TOKEN}")
_OLD_RE = re.compile(OLD_TOKEN, re.IGNORECASE)
_NEW_RE = re.compile(NEW_TOKEN, re.IGNORECASE)


def serial_text(values: Iterable[Any]) -> str:
    """Join the non-empty source fields (Description, Serial Number, part serial...) into one text."""
    return "\n".join(str(value) for value in values if value is not None and str(value).strip())


def find_serials(text: str) -> list[str]:
    """Distinct serials (upper-cased) in order of first appearance."""
    found: list[str] = []
    for match in SERIAL_RE.finditer(text or ""):
        serial = match.group(1).upper()
        if serial not in found:
            found.append(serial)
    return found


def classify_serials(text: str) -> tuple[list[str], list[str]]:
    """Split serials into (old, new) by the nearest preceding old/new keyword on the same line.

    Unlabeled serials are dropped; the line limit keeps a keyword from leaking into the next source field.
    """
    text = text or ""
    markers = sorted(
        [(m.start(), "old") for m in _OLD_RE.finditer(text)] + [(m.start(), "new") for m in _NEW_RE.finditer(text)]
    )
    lists: dict[str, list[str]] = {"old": [], "new": []}
    for match in SERIAL_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        kind = next((label for start, label in reversed(markers) if line_start <= start < match.start()), None)
        serial = match.group(1).upper()
        if kind and serial not in lists[kind]:
            lists[kind].append(serial)
    return lists["old"], lists["new"]


def serial_attributes(serial: str, *, today: date | datetime | None = None) -> dict[str, Any]:
    """Per-serial date, year and age columns used by DimSerial."""
    today = today or date.today()
    stamp = week_monday(serial_wwyy(serial, current_yy=today.year % 100))
    values: dict[str, Any] = dict.fromkeys(
        ("sn_date_wwyy", "sn_date_year", "sn_age_in_years", "sn_age_in_months", "sn_age_category")
    )
    if stamp is not None:
        months = months_since_1970(today) - months_since_1970(stamp)
        values.update(
            sn_date_wwyy=stamp,
            sn_date_year=stamp.year,
            sn_age_in_years=today.year - stamp.year,
            sn_age_in_months=months,
            sn_age_category=age_category(months),
        )
    return values


def _valid_wwyy(wwyy: str, current_yy: int) -> bool:
    return len(wwyy) == 4 and wwyy.isdigit() and 1 <= int(wwyy[:2]) <= 53 and int(wwyy[2:]) <= current_yy


def serial_wwyy(serial: str | None, *, current_yy: int | None = None) -> str | None:
    """Manufacturing week/year (WWYY) of a serial, adapted from the historical ``_adjust_wwyy``.

    Serials are ``WWYY`` + sequence (``062618PWM2``, ``0819028WIS``) or a zero-padded
    ``0`` + ``WWYY`` + sequence + letters (``0102501PWM2``). The padded form reads digits 2-5;
    otherwise digits 1-4 are used and, when they are not a valid week/year (the historical ``00``
    week rule, or a future year), the window shifted by one digit is tried.
    """
    if not serial:
        return None
    if current_yy is None:
        current_yy = date.today().year % 100
    run = re.match(r"\d+", serial)
    digits = run.group(0) if run else ""
    if len(digits) < 4:
        return None
    first, shifted = digits[:4], digits[1:5]
    padded = len(digits) >= 7 and digits[0] == "0" and not re.match(r"W(?:IS|M\d)$", serial[len(digits) :], re.I)
    windows = [shifted, first] if padded else [first, shifted]
    return next((window for window in windows if _valid_wwyy(window, current_yy)), first)


def week_monday(wwyy: str | None) -> date | None:
    """Monday of ISO week ``WW`` in year ``20YY``; ``None`` when the week is invalid."""
    if not wwyy or len(wwyy) != 4 or not wwyy.isdigit():
        return None
    try:
        monday = date.fromisocalendar(2000 + int(wwyy[2:]), int(wwyy[:2]), 1)
    except ValueError:
        return None
    return monday


def pre_post_serials(text: str, *, current_yy: int | None = None, today: date | datetime | None = None) -> dict[str, Any]:
    """The ``SERIAL_COLUMNS`` for one case; all empty unless the text cites old, new and a serial."""
    values: dict[str, Any] = dict.fromkeys(SERIAL_COLUMNS)
    today = today or date.today()
    if current_yy is None:
        current_yy = today.year % 100
    values["current_year"] = today.year
    values["current_months_since_1970"] = months_since_1970(today)
    old, new = classify_serials(text)
    values["old_serial_numbers"] = ", ".join(old) or None
    values["new_serial_numbers"] = ", ".join(new) or None
    if not (text and _OLD_RE.search(text) and _NEW_RE.search(text) and SERIAL_RE.search(text)):
        return values
    pre, post = PRE_SN_RE.search(text), POST_SN_RE.search(text)
    values["pre_sn"] = pre.group(1).upper() if pre else None
    values["post_sn"] = post.group(1).upper() if post else None
    values["pre_sn_date"] = serial_wwyy(values["pre_sn"], current_yy=current_yy)
    values["post_sn_date"] = serial_wwyy(values["post_sn"], current_yy=current_yy)
    values["pre_sn_date_wwyy"] = week_monday(values["pre_sn_date"])
    values["post_sn_date_wwyy"] = week_monday(values["post_sn_date"])
    for side in ("pre", "post"):
        stamp = values[f"{side}_sn_date_wwyy"]
        if stamp is None:
            continue
        values[f"{side}_sn_date_year"] = stamp.year
        values[f"{side}_sn_age_in_years"] = today.year - stamp.year
        values[f"{side}_sn_age_in_months_since_1970"] = months_since_1970(stamp)
    if values["pre_sn_age_in_months_since_1970"] is not None:
        values["pre_sn_age_in_months"] = values["current_months_since_1970"] - values["pre_sn_age_in_months_since_1970"]
        values["pre_sn_age_category"] = age_category(values["pre_sn_age_in_months"])
    return values
