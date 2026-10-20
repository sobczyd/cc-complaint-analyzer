import json
from pathlib import Path

from complaint_analyzer.workflows.classify_complaints import build_diagram, write_diagram
from complaint_analyzer.workflows.classify_complaints.__main__ import main

ROOT = Path(__file__).resolve().parents[1]


def _make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    (run / "clusters" / "all_b50").mkdir(parents=True)
    (run / "session.json").write_text(
        json.dumps({"prompt": "classify past week", "fields_based_on": "cq_set",
                    "export": {"row_count": 12, "target_org": "hillrom"}}),
        encoding="utf-8",
    )
    (run / "clusters" / "all_b50" / "manifest.json").write_text(
        json.dumps({"batch_size": 50, "case_count": 12, "batches": [{"batch_id": "batch_01"}]}),
        encoding="utf-8",
    )
    (run / "clusters" / "all_b50" / "final_taxonomy.json").write_text(
        json.dumps({"clusters": [{}, {}]}), encoding="utf-8"
    )
    return run


def test_diagram_reflects_run(tmp_path: Path) -> None:
    text = build_diagram(_make_run(tmp_path))
    assert "```mermaid" in text
    assert "batches of 50" in text
    assert "hillrom" in text and "cq_set" in text
    assert "2 clusters" in text


def test_state_and_diagram_cli(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    assert main(["state", "--run", str(run), "--set", "summary_batch_size=7", "glossary=updated"]) == 0
    state = json.loads((run / "classification.json").read_text(encoding="utf-8"))
    assert state == {"summary_batch_size": 7, "glossary": "updated"}
    assert main(["diagram", "--run", str(run)]) == 0
    assert "glossary: updated" in (run / "workflow.md").read_text(encoding="utf-8")
    assert write_diagram(run) == run / "workflow.md"


def test_skill_exists_and_names_chain() -> None:
    body = (ROOT / ".github" / "skills" / "classify-complaints" / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith("---\nname: classify-complaints")
    for needle in ("cq_crm_codes_nurse_call_no_comments", "case-clustering", "copilot-batch-run", "workflow.md"):
        assert needle in body
