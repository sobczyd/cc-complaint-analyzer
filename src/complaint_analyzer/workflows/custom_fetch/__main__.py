"""CLI: fetch cases with a run-specific SOQL query, then optionally summarize them.

    python -m complaint_analyzer.workflows.custom_fetch init --soql-file query.soql `
        --slug nurse_call_may --prompt "Nurse Call cases from May" `
        [--based-on cq_crm_codes_nurse_call_no_comments] [--runs-root data/runs]
    python -m complaint_analyzer.workflows.custom_fetch prepare --run data/runs/<run> `
        [--analysis case_summary] [--version v1] [--fields Subject,Status] [--batch-size 10]
    python -m complaint_analyzer.workflows.custom_fetch finalize --run data/runs/<run> [--allow-incomplete]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...core.settings import load_settings
from ...prompts import AnalysisError
from ..analysis_run import AnalysisRunError
from ..report_merge import MergeError
from ..salesforce_export.export import DEFAULT_ID_FIELD, ExportError
from . import DEFAULT_RUNS_ROOT, finalize_analysis, init_run, prepare_analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m complaint_analyzer.workflows.custom_fetch")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a run folder and export the query result")
    init.add_argument("--soql-file", required=True, type=Path, help="draft SOQL; copied into the run folder")
    init.add_argument("--slug", required=True, help="short name for the run folder")
    init.add_argument("--prompt", default="", help="the user's request, saved as request.txt")
    init.add_argument("--based-on", help="saved query set whose fields were reused")
    init.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    init.add_argument("--target-org")
    init.add_argument("--from-json", type=Path, help="replay a saved 'sf data query --json' response")
    init.add_argument("--id-field", default=DEFAULT_ID_FIELD)

    prepare = commands.add_parser("prepare", help="write the harness config for summarizing a fetched run")
    prepare.add_argument("--run", required=True, type=Path, help="run folder created by 'init'")
    prepare.add_argument("--analysis", default="case_summary", help="registered analysis (case_summary, rca)")
    prepare.add_argument("--version", help="prompt version (default: latest)")
    prepare.add_argument("--fields", help="comma-separated columns to send to the model (default: curated)")
    prepare.add_argument("--context-fields", help="comma-separated columns (Cases or child sheets) rendered as "
                         "'Column: value' lines into one Case Context field; overrides --fields")
    prepare.add_argument("--batch-size", type=int, default=10)

    finalize = commands.add_parser("finalize", help="merge harness results into cases_with_summaries.xlsx")
    finalize.add_argument("--run", required=True, type=Path)
    finalize.add_argument("--allow-incomplete", action="store_true",
                          help="merge even if the harness run has not been finalized")
    return parser


def _init(args: argparse.Namespace) -> int:
    result = init_run(
        args.soql_file.read_text(encoding="utf-8"),
        slug=args.slug,
        prompt=args.prompt,
        based_on=args.based_on,
        runs_root=args.runs_root,
        target_org=args.target_org,
        from_json=args.from_json,
        id_field=args.id_field,
    )
    print(f"exported {result.export.row_count} record(s) to {result.export.workbook}")
    print(f"run folder: {result.run_dir}")
    if not result.export.done:
        print("warning: Salesforce reported done=false; the result may be incomplete")
    return 0


def _prepare(args: argparse.Namespace) -> int:
    fields = [name.strip() for name in args.fields.split(",") if name.strip()] if args.fields else None
    context_fields = (
        [name.strip() for name in args.context_fields.split(",") if name.strip()]
        if args.context_fields else None
    )
    result = prepare_analysis(
        args.run,
        analysis=args.analysis,
        version=args.version,
        fields=fields,
        context_fields=context_fields,
        batch_size=args.batch_size,
    )
    if result.config_path is not None:
        load_settings(result.config_path)
    print(json.dumps({
        "run_dir": str(args.run.resolve()),
        "config": str(result.config_path.resolve()) if result.config_path else None,
        "run_id": result.run_id,
        "fields": list(result.fields),
        "needs_batch_run": result.needs_batch_run,
        "harness_commands": result.commands,
    }, indent=2))
    return 0


def _finalize(args: argparse.Namespace) -> int:
    merged = finalize_analysis(args.run, allow_incomplete=args.allow_incomplete)
    print(json.dumps({
        "run_dir": str(args.run.resolve()),
        "out": str(merged.out_path.resolve()),
        "rows": merged.row_count,
        "matched": merged.matched,
        "status_counts": dict(merged.status_counts),
        "unmatched_results": merged.unmatched_results,
        "generated_columns": list(merged.generated_columns),
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"init": _init, "prepare": _prepare, "finalize": _finalize}[args.command]
    try:
        return handler(args)
    except (ExportError, AnalysisRunError, AnalysisError, MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
