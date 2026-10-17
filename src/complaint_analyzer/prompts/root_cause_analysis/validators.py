"""Checks that run after the response parses, before a result is accepted."""

from __future__ import annotations

import re

from pydantic import BaseModel

from ...records import InputRecord

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip().casefold())


def resolve_field(name: str, record: InputRecord) -> str | None:
    """Match a cited field name to a supplied one, or return ``None``.

    The rendered record labels each field as ``Name:``, so a model copying that
    label faithfully cites ``Name:`` rather than ``Name``. Matching on the field's
    identity rather than its punctuation keeps that from being reported as an
    invented field. Case and surrounding whitespace are ignored for the same reason.
    """
    candidate = (name or "").strip().rstrip(":").strip()
    if not candidate:
        return None
    if candidate in record.fields:
        return candidate
    wanted = _normalize(candidate)
    for supplied in record.fields:
        if _normalize(supplied) == wanted:
            return supplied
    return None


def check_evidence_quotes(record: InputRecord, result: BaseModel) -> list[str]:
    """Every quote must name a supplied field and appear verbatim in it.

    Whitespace and letter case are normalized before comparison; wording is not.
    """
    issues: list[str] = []
    for index, item in enumerate(getattr(result, "evidence", []) or [], start=1):
        field_name = (getattr(item, "field", "") or "").strip()
        quote = (getattr(item, "quote", "") or "").strip()
        if not field_name or not quote:
            issues.append(f"evidence[{index}] is missing a field name or quote")
            continue
        supplied = resolve_field(field_name, record)
        if supplied is None:
            issues.append(
                f"evidence[{index}] names field '{field_name}', which was not supplied to the model"
            )
            continue
        if _normalize(quote) not in _normalize(record.field(supplied)):
            issues.append(
                f"evidence[{index}] quote was not found verbatim in field '{supplied}'"
            )
    return issues


def check_cause_consistency(record: InputRecord, result: BaseModel) -> list[str]:
    """A claimed cause must be stated, and must carry supporting evidence."""
    del record
    issues: list[str] = []
    status = getattr(result, "cause_status", "")
    evidence = getattr(result, "evidence", []) or []
    documented = getattr(result, "documented_cause", None)
    hypothesis = getattr(result, "hypothesis", None)

    if status == "documented":
        if not documented:
            issues.append("cause_status is 'documented' but documented_cause is empty")
        if not evidence:
            issues.append("cause_status is 'documented' but no evidence was cited")
    elif status == "hypothesized":
        if not hypothesis:
            issues.append("cause_status is 'hypothesized' but hypothesis is empty")
    elif status == "insufficient_evidence":
        if documented:
            issues.append("cause_status is 'insufficient_evidence' but a documented_cause was asserted")
    return issues
