"""The query-text loader, and the committed cq_crm_codes_nurse_call_no_comments set."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as _yaml

from complaint_analyzer.queries import (
    CHANGELOG_FILENAME,
    MANIFEST_FILENAME,
    QueryError,
    load_queries,
    next_version,
    render_changelog,
    validate_query_set,
    version_number,
    version_sort_key,
    write_changelog,
)
from complaint_analyzer.queries.__main__ import main as queries_cli

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


def test_cq_crm_codes_nurse_call_no_comments_has_v1_to_v3() -> None:
    queries = load_queries(_QUERY_SET_DIR)

    assert set(queries) == {"v1", "v2", "v3"}
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

# --- versioning, manifest and CLI -------------------------------------------------


def _write_set(directory: Path, versions: int = 2, **overrides: object) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for n in range(1, versions + 1):
        (directory / f"v{n}.txt").write_text(f"SELECT Id FROM Case -- v{n}\n", encoding="utf-8")
        entries.append(
            {
                "version": f"v{n}",
                "file": f"v{n}.txt",
                "created": "2026-01-0" + str(n),
                "base_version": None if n == 1 else f"v{n - 1}",
                "prompt": f"Prompt for v{n}",
                "summary": f"Summary v{n}",
                "changes": ["Initial version."] if n == 1 else [f"Change in v{n}"],
                "objects": ["Case"],
                "validation": {"status": "passed", "org": "dev", "row_count": 5},
            }
        )
    manifest = {
        "query_set": directory.name,
        "description": "Test set.",
        "created": "2026-01-01",
        "updated": f"2026-01-0{versions}",
        "versions": entries,
    }
    manifest.update(overrides)
    (directory / MANIFEST_FILENAME).write_text(_yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest


def test_version_numbers_sort_numerically(tmp_path: Path) -> None:
    for n in (1, 2, 10):
        (tmp_path / f"v{n}.txt").write_text(f"q{n}", encoding="utf-8")

    assert list(load_queries(tmp_path)) == ["v1", "v2", "v10"]
    assert version_number("v10") == 10
    assert version_number("draft") is None
    assert sorted(["draft", "v10", "v2"], key=version_sort_key) == ["v2", "v10", "draft"]


def test_v3_adds_case_description_to_v2() -> None:
    queries = load_queries(_QUERY_SET_DIR)

    assert "Description," not in queries["v2"].split("FROM Case")[0].replace("Model_Description__c", "")
    assert "Subject, Description," in queries["v3"]


def test_next_version_starts_at_v1_and_follows_existing(tmp_path: Path) -> None:
    assert next_version(tmp_path / "new_set") == "v1"
    assert next_version(_QUERY_SET_DIR) == "v4"
    _write_set(tmp_path / "s", versions=3)
    assert next_version(tmp_path / "s") == "v4"


def test_valid_set_passes_validation(tmp_path: Path) -> None:
    _write_set(tmp_path / "s")
    assert len(validate_query_set(tmp_path / "s")["versions"]) == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d, m: m["versions"][1].update(version="v3", file="v3.txt"), "sequential"),
        (lambda d, m: (d / "v3.txt").write_text("x", encoding="utf-8"), "v3.txt has no manifest entry"),
        (lambda d, m: m["versions"][0]["validation"].update(status="ok"), "validation.status"),
        (lambda d, m: m.update(query_set="other"), "does not match directory"),
        (lambda d, m: m["versions"][0].pop("file"), "missing 'file'"),
        (lambda d, m: m["versions"][1].update(base_version="v2"), "earlier version"),
    ],
)
def test_validation_reports_manifest_problems(tmp_path: Path, mutate, message: str) -> None:
    directory = tmp_path / "s"
    manifest = _write_set(directory)
    mutate(directory, manifest)
    (directory / MANIFEST_FILENAME).write_text(_yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(QueryError, match=message):
        validate_query_set(directory)


def test_render_changelog_lists_newest_first(tmp_path: Path) -> None:
    manifest = _write_set(tmp_path / "s")
    text = render_changelog(manifest)

    assert text.startswith("# s changelog")
    assert text.index("## v2") < text.index("## v1")
    assert "- Change in v2" in text
    assert "> Prompt for v1" in text
    assert "**Validation:** status `passed`, org `dev`, 5 row(s)" in text


def test_committed_set_manifest_is_valid_and_changelog_is_current() -> None:
    manifest = validate_query_set(_QUERY_SET_DIR)

    assert [v["version"] for v in manifest["versions"]] == ["v1", "v2", "v3"]
    committed = (_QUERY_SET_DIR / CHANGELOG_FILENAME).read_text(encoding="utf-8")
    assert committed == render_changelog(manifest)


def test_write_changelog_creates_file(tmp_path: Path) -> None:
    _write_set(tmp_path / "s")
    path = write_changelog(tmp_path / "s")
    assert path.read_text(encoding="utf-8").startswith("# s changelog")


def test_cli_validate_next_version_and_changelog(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "s"
    _write_set(directory)

    assert queries_cli([str(directory)]) == 0
    assert "ok: s (2 version(s))" in capsys.readouterr().out
    assert queries_cli([str(directory), "--next-version"]) == 0
    assert capsys.readouterr().out.strip() == "v3"
    assert queries_cli([str(directory), "--changelog"]) == 0
    assert (directory / CHANGELOG_FILENAME).is_file()


def test_cli_reports_errors(tmp_path: Path, capsys) -> None:
    (tmp_path / "s").mkdir()
    assert queries_cli([str(tmp_path / "s")]) == 1
    assert "error:" in capsys.readouterr().err
