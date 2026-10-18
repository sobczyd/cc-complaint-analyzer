"""CLI: ``python -m complaint_analyzer.workflows.daily_review <workflow> init|finalize``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ..report_merge import MergeError
from ..salesforce_export.export import ExportError
from ...core.settings import load_settings
from . import (
    DEFAULT_RUNS_ROOT,
    WORKFLOWS,
    SessionError,
    finalize_session,
    get_workflow,
    init_session,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.daily_review",
        description="Daily review sessions: export cases, then merge harness summaries.",
    )
    parser.add_argument("workflow", choices=sorted(WORKFLOWS), help="workflow name")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a session folder, export cases, write config")
    init.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    init.add_argument("--date", type=date.fromisoformat, help="session date (default: today)")
    init.add_argument("--target-org", help="sf org alias/username (default: sf default org)")
    init.add_argument("--from-json", type=Path, help="reuse a saved `sf data query --json` file")
    init.add_argument("--query-version", help="query set version (default: latest)")
    init.add_argument("--batch-size", type=int, default=10)

    fin = sub.add_parser("finalize", help="merge harness results into the session workbook")
    fin.add_argument("--session", type=Path, required=True, help="session folder")
    fin.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="merge even if the harness run has not been finalized",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workflow = get_workflow(args.workflow)
        if args.command == "init":
            result = init_session(
                workflow,
                runs_root=args.runs_root,
                day=args.date,
                target_org=args.target_org,
                from_json=args.from_json,
                query_version=args.query_version,
                batch_size=args.batch_size,
            )
            if result.config_path is not None:
                load_settings(result.config_path)
            payload = {
                "session_dir": str(result.session_dir.resolve()),
                "query_set": result.export.query_set,
                "query_version": result.export.version,
                "target_org": result.export.target_org,
                "rows": result.export.row_count,
                "done": result.export.done,
                "workbook": str(result.export.workbook.resolve()),
                "config": str(result.config_path.resolve()) if result.config_path else None,
                "run_id": result.run_id,
                "needs_batch_run": result.needs_batch_run,
                "harness_commands": result.commands,
            }
        else:
            merged = finalize_session(args.session, allow_incomplete=args.allow_incomplete)
            payload = {
                "session_dir": str(args.session.resolve()),
                "out": str(merged.out_path.resolve()),
                "rows": merged.row_count,
                "matched": merged.matched,
                "status_counts": dict(merged.status_counts),
                "unmatched_results": merged.unmatched_results,
                "generated_columns": list(merged.generated_columns),
            }
    except (SessionError, ExportError, MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
