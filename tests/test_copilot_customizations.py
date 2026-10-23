"""Structural checks for the workspace Copilot customizations."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, body = text.split("---", 2)
    return yaml.safe_load(raw), body


def test_batch_run_skill_is_discoverable_and_documents_orchestration() -> None:
    path = ROOT / ".github" / "skills" / "copilot-batch-run" / "SKILL.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == path.parent.name
    assert metadata["user-invocable"] is True
    assert "harness" in metadata["description"]
    assert "Batch Worker" in body
    assert "--check" in body
    assert "--finalize" in body
    assert "incomplete_assignment_ids" in body


def test_batch_worker_is_restricted_to_one_assignment() -> None:
    path = ROOT / ".github" / "agents" / "batch-worker.agent.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == "Batch Worker"
    assert metadata["user-invocable"] is False
    assert set(metadata["tools"]) == {"read", "edit", "execute"}
    assert "Process only request files listed" in body
    assert "Do not finalize the run" in body
    assert "--publish-response" in body


def test_salesforce_query_author_skill_documents_versioned_workflow() -> None:
    path = ROOT / ".github" / "skills" / "salesforce-query-author" / "SKILL.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == path.parent.name
    assert metadata["user-invocable"] is True
    assert "SOQL" in metadata["description"]
    for marker in (
        "salesforce-local-get_username",
        "salesforce-local-run_soql_query",
        "--next-version",
        "--changelog",
        "manifest.yaml",
        "base_version",
        "LIMIT 5",
    ):
        assert marker in body


def test_old_rca_specific_customizations_are_gone() -> None:
    assert not (ROOT / ".github" / "skills" / "rca-harness-batch").exists()
    assert not (ROOT / ".github" / "agents" / "rca-harness-worker.agent.md").exists()


def test_prompt_author_skill_documents_versioned_workflow() -> None:
    path = ROOT / ".github" / "skills" / "prompt-author" / "SKILL.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == path.parent.name
    assert metadata["user-invocable"] is True
    assert "prompt" in metadata["description"]
    for marker in (
        "src\\complaint_analyzer\\prompts\\",
        "--list",
        "--next-version",
        "--changelog",
        "manifest.yaml",
        "base_version",
        "result_model",
        "copilot-batch-run",
    ):
        assert marker in body

def test_salesforce_fetch_agent_is_run_scoped() -> None:
    path = ROOT / ".github" / "agents" / "salesforce-fetch.agent.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == "salesforce-fetch"
    assert metadata["user-invocable"] is True
    assert "agent" in metadata["tools"]
    assert not any(tool.startswith("salesforce-local") for tool in metadata["tools"])
    for marker in (
        "custom_fetch init",
        "custom_fetch prepare",
        "custom_fetch finalize",
        "fields --query-set",
        "copilot-batch-run",
        "Only SELECT",
    ):
        assert marker in body
    assert "salesforce-local" not in body


def test_defect_mapping_skill_and_worker_are_wired() -> None:
    skill_path = ROOT / ".github" / "skills" / "defect-mapping" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)
    assert metadata["name"] == skill_path.parent.name
    assert metadata["user-invocable"] is True
    for needle in (
        "Defect Mapping Worker",
        "case_assignments.jsonl",
        "direct_links.jsonl",
        "--min-batch",
        "incomplete_request_ids",
    ):
        assert needle in body

    worker_path = ROOT / ".github" / "agents" / "defect-mapping-worker.agent.md"
    worker, worker_body = _frontmatter(worker_path)
    assert worker["name"] == "Defect Mapping Worker"
    assert "publish" in worker_body
    assert "=== Candidate ===" in worker_body

    corpus_path = ROOT / ".github" / "skills" / "jira-rca-corpus" / "SKILL.md"
    corpus, corpus_body = _frontmatter(corpus_path)
    assert corpus["name"] == corpus_path.parent.name
    for needle in ("jira-plan", "jira-normalize", "kb-plan", "kb-normalize", "defect_comment_summary"):
        assert needle in corpus_body


def test_trackwise_integration_skill_is_wired() -> None:
    skill_path = ROOT / ".github" / "skills" / "trackwise-integration" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)
    assert metadata["name"] == skill_path.parent.name
    for needle in ("FactComplaint", "--trackwise-dir", "data\\trackwise", "trackforce-insight"):
        assert needle in body
    _, export_body = _frontmatter(ROOT / ".github" / "skills" / "powerbi-export" / "SKILL.md")
    assert "trackwise-integration" in export_body


def test_case_clustering_skill_and_worker_are_wired() -> None:
    skill_path = ROOT / ".github" / "skills" / "case-clustering" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)
    assert metadata["name"] == skill_path.parent.name
    assert metadata["user-invocable"] is True
    for needle in ("Cluster Worker", "prepare-merge", "finalize", "incomplete_request_ids"):
        assert needle in body

    worker_path = ROOT / ".github" / "agents" / "cluster-worker.agent.md"
    worker, worker_body = _frontmatter(worker_path)
    assert worker["name"] == "Cluster Worker"
    assert "publish" in worker_body

    jama_path = ROOT / ".github" / "skills" / "jama-nursecall-context" / "SKILL.md"
    jama, jama_body = _frontmatter(jama_path)
    assert jama["name"] == jama_path.parent.name
    assert "CWS-CMP-122" in jama_body and "CWS-CMP-320" in jama_body


def test_compare_periods_skill_and_worker_are_wired() -> None:
    skill_path = ROOT / ".github" / "skills" / "compare-periods" / "SKILL.md"
    metadata, body = _frontmatter(skill_path)
    assert metadata["name"] == skill_path.parent.name
    assert metadata["user-invocable"] is True
    for needle in (
        "Cluster Resolve Worker",
        "list-clusters",
        "--min-change",
        "--batch-size",
        "incomplete_request_ids",
        "comparison.xlsx",
        "resolved_assignments.jsonl",
    ):
        assert needle in body

    worker_path = ROOT / ".github" / "agents" / "cluster-resolve-worker.agent.md"
    worker, worker_body = _frontmatter(worker_path)
    assert worker["name"] == "Cluster Resolve Worker"
    assert "publish" in worker_body and "compare_periods" in worker_body
