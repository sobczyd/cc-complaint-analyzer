"""The prompt framework, the registered prompt sets and their manifests."""

from __future__ import annotations

import pytest

from complaint_analyzer.prompts import AnalysisError, available, get_analysis, prompt_set_dir
from complaint_analyzer.prompts.__main__ import main as prompts_cli
from complaint_analyzer.prompts.base import (
    default_render,
    flatten_result,
    parse_json_object,
)
from complaint_analyzer.prompts.case_summary.schema import CaseSummaryResult
from complaint_analyzer.prompts.manifest import (
    next_version,
    render_changelog,
    validate_prompt_set,
)
from complaint_analyzer.prompts.root_cause_analysis.schema import RcaResult
from complaint_analyzer.prompts.root_cause_analysis.validators import (
    check_cause_consistency,
    check_evidence_quotes,
)
from complaint_analyzer.core.records import InputRecord

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


@pytest.mark.parametrize("name", available())
def test_every_registered_prompt_set_validates(name: str) -> None:
    directory = prompt_set_dir(name)
    manifest = validate_prompt_set(directory)
    assert manifest["prompt_set"] == directory.name
    versions = [entry["version"] for entry in manifest["versions"]]
    assert sorted(versions) == sorted(get_analysis(name).prompts)


@pytest.mark.parametrize("name", available())
def test_committed_changelog_matches_the_manifest(name: str) -> None:
    directory = prompt_set_dir(name)
    manifest = validate_prompt_set(directory)
    committed = (directory / "CHANGELOG.md").read_text(encoding="utf-8")
    assert committed == render_changelog(manifest)


def test_rca_lives_in_a_descriptive_folder() -> None:
    assert prompt_set_dir("rca").name == "root_cause_analysis"
    assert prompt_set_dir("case_summary").name == "case_summary"
    assert next_version(prompt_set_dir("rca")) == "v3"


def test_case_summary_builds_and_validates_sample_output() -> None:
    analysis = get_analysis("case_summary")
    assert analysis.name == "case_summary"
    assert analysis.result_model is CaseSummaryResult
    assert "v1" in analysis.prompts
    result = CaseSummaryResult.model_validate(
        {
            "summary": "Router drops connection; replaced cable.",
            "status": "Resolved",
            "actions_taken": ["Checked logs", "Replaced cable"],
            "unexpected": "ignored",
        }
    )
    assert result.status == "resolved"
    assert analysis.validate_result(record(), result) == []


def test_prompts_cli_lists_and_validates(capsys: pytest.CaptureFixture[str]) -> None:
    assert prompts_cli(["--list"]) == 0
    listed = capsys.readouterr().out
    assert "case_summary\tcase_summary\tv3" in listed
    assert "rca\troot_cause_analysis\tv2" in listed

    assert prompts_cli(["rca"]) == 0
    assert "ok: root_cause_analysis (2 version(s))" in capsys.readouterr().out

    assert prompts_cli(["case_summary", "--next-version"]) == 0
    assert capsys.readouterr().out.strip() == "v4"


def test_prompts_cli_reports_a_missing_set(capsys: pytest.CaptureFixture[str]) -> None:
    assert prompts_cli(["does_not_exist"]) == 1
    assert "error:" in capsys.readouterr().err
