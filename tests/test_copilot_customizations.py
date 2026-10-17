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