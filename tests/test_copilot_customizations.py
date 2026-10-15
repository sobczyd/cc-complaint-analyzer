"""Structural checks for the workspace RCA harness customizations."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def _frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, body = text.split("---", 2)
    return yaml.safe_load(raw), body


def test_rca_harness_skill_is_discoverable_and_documents_orchestration() -> None:
    path = ROOT / ".github" / "skills" / "rca-harness-batch" / "SKILL.md"
    metadata, body = _frontmatter(path)

    assert metadata["name"] == path.parent.name
    assert metadata["user-invocable"] is True
    assert "RCA harness" in metadata["description"]
    assert "RCA Harness Worker" in body
    assert "--check" in body
    assert "--finalize" in body
    assert "incomplete_assignment_ids" in body


def test_rca_harness_worker_is_restricted_to_one_assignment() -> None:
    path = ROOT / ".github" / "agents" / "rca-harness-worker.agent.md"
    metadata, body = _frontmatter(path)

    assert metadata["user-invocable"] is False
    assert set(metadata["tools"]) == {"read", "edit", "execute"}
    assert "Process only request files listed" in body
    assert "Do not finalize the run" in body
    assert "--publish-response" in body
