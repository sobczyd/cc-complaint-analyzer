"""Ad-hoc Salesforce fetch: run a run-specific SOQL query into its own run folder.

A run folder lives under ``data/runs`` and holds everything for one request:

    request.txt                                       (the user's prompt)
    query.soql, raw.json, export.json, cases.xlsx     (salesforce export)
    <analysis>.yaml, <analysis>/                      (optional: harness config and batch run)
    cases_with_summaries.xlsx                         (optional: merged, color-coded workbook)
    session.json                                      (metadata)

Nothing is written to ``config/`` or ``queries/``.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ...prompts import get_analysis
from ..analysis_run import (
    AnalysisRunError,
    build_config,
    harness_commands,
    merge_run,
    new_run_dir as _new_run_dir,
    select_model_fields,
    write_config,
)
from ..report_merge import MergeResult
from ..salesforce_export.export import DEFAULT_ID_FIELD, ExportResult, export_soql
from .context import CONTEXT_COLUMN, build_context_workbook

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RUNS_ROOT = REPO_ROOT / "data" / "runs"
REQUEST_FILENAME = "request.txt"
SESSION_FILENAME = "session.json"
SESSION_KIND = "custom_fetch"


def slugify(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:max_length].strip("_")
    return slug or "custom_fetch"


def new_run_dir(runs_root: Path, slug: str, day: date) -> Path:
    """Return an unused ``<slug>_<date>`` folder, adding ``_2``, ``_3``... if taken."""
    return _new_run_dir(runs_root, slugify(slug), day)


@dataclass(frozen=True)
class FetchResult:
    run_dir: Path
    export: ExportResult


def init_run(
    soql: str,
    *,
    slug: str,
    prompt: str = "",
    based_on: str | None = None,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    day: date | None = None,
    target_org: str | None = None,
    from_json: Path | None = None,
    id_field: str = DEFAULT_ID_FIELD,
) -> FetchResult:
    """Create the run folder, record the request, export the cases and write session.json."""
    run_dir = new_run_dir(runs_root, slug, day or date.today())
    run_dir.mkdir(parents=True)
    (run_dir / REQUEST_FILENAME).write_text(prompt, encoding="utf-8")
    try:
        export = export_soql(
            soql, run_dir, target_org=target_org, from_json=from_json, id_field=id_field
        )
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)  # no half-built run folders
        raise
    session: dict[str, Any] = {
        "kind": SESSION_KIND,
        "run_dir": str(run_dir.resolve()),
        "created_at": _now(),
        "prompt": prompt,
        "fields_based_on": based_on,
        "export": export.as_json(),
        "id_field": id_field,
        "analysis": None,
        "harness_commands": {},
        "finalized_at": None,
        "merge": None,
    }
    _write_session(run_dir, session)
    return FetchResult(run_dir=run_dir, export=export)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_session(run_dir: Path) -> dict[str, Any]:
    path = run_dir / SESSION_FILENAME
    if not path.is_file():
        raise AnalysisRunError(f"not a custom fetch run folder (no {SESSION_FILENAME}): {run_dir}")
    session = json.loads(path.read_text(encoding="utf-8"))
    if session.get("kind") != SESSION_KIND:
        raise AnalysisRunError(f"not a custom fetch run folder: {run_dir}")
    session.setdefault("id_field", DEFAULT_ID_FIELD)
    return session


def _write_session(run_dir: Path, session: dict[str, Any]) -> None:
    (run_dir / SESSION_FILENAME).write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class PrepareResult:
    config_path: Path | None
    run_id: str
    fields: tuple[str, ...]
    commands: dict[str, str]

    @property
    def needs_batch_run(self) -> bool:
        return self.config_path is not None


def prepare_analysis(
    run_dir: Path,
    *,
    analysis: str = "case_summary",
    version: str | None = None,
    fields: list[str] | None = None,
    context_fields: list[str] | None = None,
    batch_size: int = 10,
    concurrency: int = 3,
    max_output_tokens: int = 900,
) -> PrepareResult:
    """Write the harness config for a fetched run and record the batch-run commands.

    ``context_fields`` renders those columns (Cases sheet or child sheets) as
    ``ColumnName: value`` lines into one "Case Context" field sent to the model.
    """
    session = _read_session(run_dir)
    export = session["export"]
    definition = get_analysis(analysis)
    version = version or list(definition.prompts)[-1]
    definition.prompt(version)  # fail early on an unknown version

    columns: list[str] = export["columns"]
    dataset_path: Path | None = None
    if context_fields:
        if export["row_count"]:
            dataset_path = build_context_workbook(run_dir, context_fields, id_field=session["id_field"])
        chosen = [CONTEXT_COLUMN]
    elif fields:
        by_name = {column.lower(): column for column in columns}
        missing = [name for name in fields if name.lower() not in by_name]
        if missing:
            raise AnalysisRunError(f"fields not in the exported columns: {', '.join(missing)}")
        chosen = [by_name[name.lower()] for name in fields]
    else:
        chosen = select_model_fields(columns)

    config_path: Path | None = None
    commands: dict[str, str] = {}
    if export["row_count"]:
        config = build_config(
            run_dir,
            analysis=analysis,
            version=version,
            id_field=session["id_field"],
            fields=chosen,
            concurrency=concurrency,
            max_output_tokens=max_output_tokens,
            dataset_path=dataset_path,
        )
        config_path = run_dir / f"{analysis}.yaml"
        write_config(config_path, config)
        commands = harness_commands(config_path.resolve(), analysis, batch_size)

    session["analysis"] = {
        "name": analysis,
        "version": version,
        "run_id": analysis,
        "config": config_path.name if config_path else None,
        "fields": chosen,
        "context_fields": context_fields,
        "skipped": not export["row_count"],
    }
    session["harness_commands"] = commands
    _write_session(run_dir, session)
    return PrepareResult(config_path, analysis, tuple(chosen), commands)


def finalize_analysis(run_dir: Path, *, allow_incomplete: bool = False) -> MergeResult:
    """Merge the harness results into ``cases_with_summaries.xlsx`` and update session.json."""
    session = _read_session(run_dir)
    analysis = session.get("analysis")
    if not analysis:
        raise AnalysisRunError("no analysis prepared for this run; run 'prepare' first")
    export = session["export"]
    row_count = int(export["row_count"])

    notes = [
        f"Request: {session['prompt']}" if session.get("prompt") else "Request: (not recorded)",
        "Query: run-specific SOQL (query.soql)"
        + (f", fields based on {session['fields_based_on']}" if session.get("fields_based_on") else "")
        + (f" (org {export['target_org']})" if export.get("target_org") else ""),
        f"Exported at: {export.get('exported_at', '')}",
        f"Prompt: {analysis['name']} {analysis['version']} (run id {analysis['run_id']})",
    ]
    if not row_count:
        notes.append("No cases were returned; the batch run was skipped.")

    result, merge_info = merge_run(
        run_dir,
        analysis=analysis["name"],
        run_id=analysis["run_id"],
        id_field=session["id_field"],
        row_count=row_count,
        notes=notes,
        allow_incomplete=allow_incomplete,
    )
    session["finalized_at"] = _now()
    session["merge"] = merge_info
    _write_session(run_dir, session)
    return result


__all__ = [
    "FetchResult",
    "PrepareResult",
    "finalize_analysis",
    "init_run",
    "new_run_dir",
    "prepare_analysis",
    "slugify",
]
