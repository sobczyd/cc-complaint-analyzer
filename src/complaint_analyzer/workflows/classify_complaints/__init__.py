"""Static Mermaid workflow diagram for a classify-complaints run folder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _esc(text: object) -> str:
    return str(text).replace('"', "'").replace("\n", " ")


def _latest_cluster_manifest(run: Path) -> tuple[str | None, dict[str, Any]]:
    manifests = sorted(
        run.glob("clusters/*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not manifests:
        return None, {}
    return manifests[0].parent.name, _read_json(manifests[0])


def build_diagram(run: Path) -> str:
    """Return a markdown document with a Mermaid flowchart describing the run."""
    run = Path(run)
    session = _read_json(run / "session.json")
    state = _read_json(run / "classification.json")
    export = session.get("export", {})
    cluster_name, cluster = _latest_cluster_manifest(run)
    taxonomy = _read_json(run / "clusters" / cluster_name / "final_taxonomy.json") if cluster_name else {}

    request = state.get("request") or session.get("prompt") or "(not recorded)"
    source = state.get("source") or ("fetched from Salesforce" if export else "existing folder")
    query = state.get("query") or session.get("fields_based_on") or "n/a"
    rows = export.get("row_count", "?")
    org = export.get("target_org", "?")
    summ_version = state.get("summary_version", "latest")
    summ_batch = state.get("summary_batch_size", "default")
    cl_batch = cluster.get("batch_size", state.get("cluster_batch_size", "?"))
    cases = cluster.get("case_count", "?")
    n_batches = len(cluster.get("batches", []))
    glossary = state.get("glossary", "as is")
    n_clusters = len(taxonomy.get("clusters", [])) if taxonomy else "?"

    lines = [
        "flowchart TD",
        f'    A["User request<br/>{_esc(request)[:120]}"] --> B{{"Existing folder<br/>with data?"}}',
        f'    B -- "yes" --> D["Reuse cases<br/>{_esc(source)}"]',
        f'    B -- "no" --> C["Fetch from Salesforce (org {_esc(org)})<br/>based on {_esc(query)}<br/>{_esc(rows)} cases"]',
        "    C --> D",
        f'    D --> E["Summarize with case_summary {_esc(summ_version)}<br/>batch size {_esc(summ_batch)}<br/>Batch Worker agents"]',
        '    E --> F["cases_with_summaries.xlsx"]',
        f'    F --> G["Cluster in batches of {_esc(cl_batch)}<br/>{_esc(cases)} cases, {_esc(n_batches)} batches<br/>glossary: {_esc(glossary)}<br/>Cluster Worker agents"]',
        '    G --> H["Merge batch labels<br/>into one taxonomy"]',
        f'    H --> I["Final taxonomy<br/>{_esc(n_clusters)} clusters<br/>clusters.xlsx, final_taxonomy.json"]',
        '    I --> J["Run folder + workflow.md"]',
    ]
    steps = [
        ("Request", "User asks to classify complaints; the agent asks about assumptions and uses defaults if declined."),
        ("Fetch", "Skipped when a folder with data is supplied; otherwise a run-specific query based on the default query set."),
        ("Summarize", "Latest case_summary prompt version, Batch Worker agents, results merged into cases_with_summaries.xlsx."),
        ("Cluster", "case_cluster prompt with the Nurse Call glossary as standing context, in batches."),
        ("Merge", "case_cluster_merge prompt melts duplicate or related labels into one taxonomy."),
        ("Outputs", "final_taxonomy.json, case_assignments.jsonl and clusters.xlsx in the run folder."),
    ]
    body = ["# Classify complaints workflow", "", f"Run folder: `{run.name}`", "", "```mermaid", *lines, "```", "",
            "## Steps", ""]
    body += [f"{i}. **{name}** - {desc}" for i, (name, desc) in enumerate(steps, 1)]
    body.append("")
    return "\n".join(body)


def write_diagram(run: Path) -> Path:
    path = Path(run) / "workflow.md"
    path.write_text(build_diagram(run), encoding="utf-8")
    return path
