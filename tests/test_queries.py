"""The query-text loader, and the committed cq_crm_codes_nurse_call_no_comments set."""

from __future__ import annotations

from pathlib import Path

import pytest

from complaint_analyzer.queries import QueryError, load_queries

_QUERY_SET_DIR = (
    Path(__file__).parent.parent
    / "src"
    / "complaint_analyzer"
    / "queries"
    / "cq_crm_codes_nurse_call_no_comments"
)


def test_load_queries_reads_each_version_keyed_by_stem(tmp_path: Path) -> None:
    (tmp_path / "v1.txt").write_text("SELECT Id FROM Case", encoding="utf-8")
    (tmp_path / "v2.txt").write_text("SELECT Id, Status FROM Case", encoding="utf-8")

    queries = load_queries(tmp_path)

    assert queries == {
        "v1": "SELECT Id FROM Case",
        "v2": "SELECT Id, Status FROM Case",
    }


def test_load_queries_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(QueryError, match="query directory not found"):
        load_queries(tmp_path / "does-not-exist")


def test_load_queries_rejects_a_directory_with_no_txt_files(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("not a query", encoding="utf-8")

    with pytest.raises(QueryError, match="no query files"):
        load_queries(tmp_path)


def test_cq_crm_codes_nurse_call_no_comments_has_v1_and_v2() -> None:
    queries = load_queries(_QUERY_SET_DIR)

    assert set(queries) == {"v1", "v2"}
    for text in queries.values():
        assert "FROM Case" in text
        assert "Problem_Codes__r" in text
        assert "Complaint_Qualifications__r" in text
        assert "CareComm - Nurse Call" in text


def test_v2_adds_fields_that_v1_does_not_have() -> None:
    queries = load_queries(_QUERY_SET_DIR)

    v2_only_markers = (
        "HRCSVC_Case_Resolution__c",
        "Account.JDE_External_ID__c",
        "Asset.HRCFSL_UDI__c",
        "ADPC_Name__c",
    )
    for marker in v2_only_markers:
        assert marker not in queries["v1"]
        assert marker in queries["v2"]


def test_neither_version_references_case_comments() -> None:
    queries = load_queries(_QUERY_SET_DIR)

    for text in queries.values():
        assert "CaseComment" not in text
        assert "Comment" not in text
