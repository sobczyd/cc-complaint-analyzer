"""The analysis framework and the RCA analysis itself."""

from __future__ import annotations

import pytest

from complaint_analyzer.analyses import AnalysisError, available, get_analysis
from complaint_analyzer.analyses.base import (
    default_render,
    flatten_result,
    parse_json_object,
)
from complaint_analyzer.analyses.rca.schema import RcaResult
from complaint_analyzer.analyses.rca.validators import (
    check_cause_consistency,
    check_evidence_quotes,
)
from complaint_analyzer.records import InputRecord

FIELDS = ("Service description", "Troubleshooting")


def record(**fields: str) -> InputRecord:
    values = {"Service description": "Router drops connection.", "Troubleshooting": "Found packet loss."}
    values.update(fields)
    return InputRecord(record_id="R-001", source_row=2, fields=values)


def test_registry_exposes_rca() -> None:
    assert "rca" in available()
    assert get_analysis("rca").name == "rca"


def test_registry_rejects_unknown_analysis() -> None:
    with pytest.raises(AnalysisError, match="unknown analysis"):
        get_analysis("nope")


def test_unknown_prompt_version_is_reported() -> None:
    with pytest.raises(AnalysisError, match="no prompt version"):
        get_analysis("rca").prompt("v999")


def test_prompt_hash_is_stable_and_version_specific() -> None:
    analysis = get_analysis("rca")
    assert analysis.prompt_hash("v1") == analysis.prompt_hash("v1")
    assert len(analysis.prompt_hash("v1")) == 64


def test_output_columns_match_the_schema() -> None:
    assert get_analysis("rca").output_columns == list(RcaResult.model_fields)


def test_default_render_labels_fields_and_marks_blanks() -> None:
    rendered = default_render(record(Troubleshooting=""), FIELDS)
    assert "RECORD ID: R-001" in rendered
    assert "Service description:" in rendered
    assert "(blank)" in rendered


@pytest.mark.parametrize(
    "text",
    [
        '{"symptom": "x"}',
        '```json\n{"symptom": "x"}\n```',
        'Here you go:\n{"symptom": "x"}\nHope that helps.',
    ],
)
def test_parse_json_object_tolerates_wrapping(text: str) -> None:
    assert parse_json_object(text) == {"symptom": "x"}


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "empty response"),
        ("no json here", "no JSON object"),
        ("[1, 2, 3]", "not an object"),
        ("{not valid}", "not valid JSON"),
    ],
)
def test_parse_json_object_rejects_bad_input(text: str, message: str) -> None:
    with pytest.raises(AnalysisError, match=message):
        parse_json_object(text)


def test_flatten_result_renders_every_field_as_text() -> None:
    result = RcaResult.model_validate(
        {
            "symptom": "Drops connection",
            "cause_status": "documented",
            "documented_cause": "Damaged cable",
            "evidence": [{"field": "Troubleshooting", "quote": "Found packet loss."}],
            "missing_evidence": ["a", "b"],
            "needs_review": False,
        }
    )
    flat = flatten_result(result)
    assert set(flat) == set(RcaResult.model_fields)
    assert flat["needs_review"] == "no"
    assert flat["missing_evidence"] == "a\nb"
    assert "Found packet loss." in flat["evidence"]
    assert flat["hypothesis"] == ""


def test_schema_normalizes_status_and_blank_strings() -> None:
    result = RcaResult.model_validate(
        {"cause_status": " Insufficient-Evidence ", "documented_cause": "   "}
    )
    assert result.cause_status == "insufficient_evidence"
    assert result.documented_cause is None


def test_schema_ignores_unknown_keys() -> None:
    assert RcaResult.model_validate({"symptom": "x", "unexpected": 1}).symptom == "x"


def test_evidence_quote_must_appear_verbatim() -> None:
    result = RcaResult.model_validate(
        {"evidence": [{"field": "Troubleshooting", "quote": "Found   PACKET loss."}]}
    )
    assert check_evidence_quotes(record(), result) == []

    invented = RcaResult.model_validate(
        {"evidence": [{"field": "Troubleshooting", "quote": "Measured 40dB of loss."}]}
    )
    assert "verbatim" in check_evidence_quotes(record(), invented)[0]


def test_evidence_must_name_a_supplied_field() -> None:
    result = RcaResult.model_validate({"evidence": [{"field": "Resolution", "quote": "x"}]})
    assert "not supplied" in check_evidence_quotes(record(), result)[0]


@pytest.mark.parametrize(
    "cited",
    ["Troubleshooting:", " Troubleshooting ", "troubleshooting", "TROUBLESHOOTING:"],
)
def test_a_field_label_is_matched_despite_punctuation_or_case(cited: str) -> None:
    """The rendered record labels fields as ``Name:``; citing that is not an invention."""
    result = RcaResult.model_validate(
        {"evidence": [{"field": cited, "quote": "Found packet loss."}]}
    )
    assert check_evidence_quotes(record(), result) == []


def test_a_genuinely_unknown_field_is_still_reported() -> None:
    result = RcaResult.model_validate(
        {"evidence": [{"field": "Invented Field:", "quote": "Found packet loss."}]}
    )
    assert "not supplied" in check_evidence_quotes(record(), result)[0]


def test_a_bad_quote_is_still_caught_when_the_label_has_a_colon() -> None:
    result = RcaResult.model_validate(
        {"evidence": [{"field": "Troubleshooting:", "quote": "never said this"}]}
    )
    issues = check_evidence_quotes(record(), result)
    assert len(issues) == 1
    assert "verbatim" in issues[0]
    # The message names the supplied field, not the punctuated citation.
    assert "'Troubleshooting'" in issues[0]


def test_evidence_needs_both_a_field_and_a_quote() -> None:
    result = RcaResult.model_validate({"evidence": [{"field": "", "quote": ""}]})
    assert "missing a field name or quote" in check_evidence_quotes(record(), result)[0]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"cause_status": "documented"}, 2),
        (
            {
                "cause_status": "documented",
                "documented_cause": "Damaged cable",
                "evidence": [{"field": "Troubleshooting", "quote": "Found packet loss."}],
            },
            0,
        ),
        ({"cause_status": "hypothesized"}, 1),
        ({"cause_status": "hypothesized", "hypothesis": "Cabling"}, 0),
        ({"cause_status": "insufficient_evidence", "documented_cause": "Cable"}, 1),
        ({"cause_status": "insufficient_evidence"}, 0),
    ],
)
def test_cause_consistency(payload: dict, expected: int) -> None:
    result = RcaResult.model_validate(payload)
    assert len(check_cause_consistency(record(), result)) == expected


def test_analysis_runs_every_validator() -> None:
    analysis = get_analysis("rca")
    result = RcaResult.model_validate(
        {
            "cause_status": "documented",
            "evidence": [{"field": "Troubleshooting", "quote": "never said this"}],
        }
    )
    issues = analysis.validate_result(record(), result)
    assert any("verbatim" in issue for issue in issues)
    assert any("documented_cause is empty" in issue for issue in issues)
