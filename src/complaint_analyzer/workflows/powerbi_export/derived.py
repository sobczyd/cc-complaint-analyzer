"""Derived Remote Assessment / Device Evaluation Assessment blocks.

Port of ``_assessment`` in ``scripts/dev/preprocess/derived_fields.py`` (``sobczyd/trackforce-insight``).
Trackforce resolves the duplicated report labels ``Test Results``, ``Issue Cause`` and ``Log Evidence``
to their first occurrence, so both blocks use ``test_results``, ``issue_cause`` and ``log_evidence``.
"""

from __future__ import annotations

from typing import Any, Mapping

REMOTE_ASSESSMENT = "Remote Assessment"
DEVICE_EVALUATION_ASSESSMENT = "Device Evaluation Assessment"

_RA_QUESTIONS: tuple[str, ...] = (
    "What troubleshooting/Inspection was performed for the issue(s)",
    "What were the results of troubleshooting/Inspection?",
    "What is the cause/causes of the issue",
    "What are the actions needed to resolve the issue(s)",
    "Did same issue occur within the last 30 days in the same location/unit?",
    "Did review of the customer device log reveal evidence of the customer reported problem(s)?",
)

_DEA_QUESTIONS: tuple[str, ...] = (
    "What testing, inspection, and/or troubleshooting was performed for the issue(s)",
    "What were the results (e.g. did the device fail/pass test specifications, inspection or troubleshooting)?",
    "What is the cause/causes of the issue",
    "What are the actions needed to resolve the issue(s):",
    "Was the device serviced within the past 12 months for the same problem(s)?",
    "Did review of the customer device log reveal evidence of the customer reported problem(s)?",
)

ASSESSMENT_QUESTIONS: dict[str, tuple[str, ...]] = {
    REMOTE_ASSESSMENT: _RA_QUESTIONS,
    DEVICE_EVALUATION_ASSESSMENT: _DEA_QUESTIONS,
}


def _text(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _block(values: Mapping[str, Any], questions: tuple[str, ...], troubleshooting: str, serviced: str) -> str:
    answers = (
        _text(values.get(troubleshooting)),
        _text(values.get("test_results")),
        _text(values.get("issue_cause")),
        f"{_text(values.get('actions_to_resolve'))}:{_text(values.get('ra_actions_to_resolve'))}",
        _text(values.get(serviced)),
        _text(values.get("log_evidence")),
    )
    return "".join(f"{question}:{answer}\n" for question, answer in zip(questions, answers, strict=True))


def assessments(values: Mapping[str, Any]) -> dict[str, str]:
    """Both assessment blocks from already-mapped output columns."""
    return {
        REMOTE_ASSESSMENT: _block(values, _RA_QUESTIONS, "test_inspection_troubleshooting", "did_same_issue_occur"),
        DEVICE_EVALUATION_ASSESSMENT: _block(
            values, _DEA_QUESTIONS, "test_inspection_troubleshooting_2", "was_device_serviced"
        ),
    }
