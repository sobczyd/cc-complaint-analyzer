"""CLI: run a versioned query set against Salesforce and write ``cases.xlsx``.

    python -m complaint_analyzer.workflows.salesforce_export export --query-set cq_crm_codes_nurse_call_no_comments \
        --out-dir data/runs/my_export [--version v1] [--target-org hillrom] [--from-json raw.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export import (
    DEFAULT_ID_FIELD,
    DEFAULT_TIMEOUT_SECONDS,
    ExportError,
    export_query_set,
    export_soql,
    select_clause,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m complaint_analyzer.workflows.salesforce_export")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="run a query set and write cases.xlsx")
    source = export.add_mutually_exclusive_group(required=True)
    source.add_argument("--query-set", help="folder under queries/")
    source.add_argument("--soql-file", type=Path, help="run-specific SOQL file (ad-hoc query)")
    export.add_argument("--version", help="query version, for example v1 (default: latest)")
    export.add_argument("--out-dir", required=True, type=Path)
    export.add_argument("--target-org", help="sf org alias or username (default: sf default)")
    export.add_argument(
        "--from-json", type=Path, help="replay a saved 'sf data query --json' response"
    )
    export.add_argument("--id-field", default=DEFAULT_ID_FIELD)
    export.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    fields = commands.add_parser("fields", help="print SELECT...FROM of a saved query without its filters")
    fields.add_argument("--query-set", required=True)
    fields.add_argument("--version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fields":
        try:
            print(select_clause(args.query_set, args.version))
        except ExportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        common = dict(
            target_org=args.target_org,
            from_json=args.from_json,
            id_field=args.id_field,
            timeout=args.timeout,
        )
        if args.soql_file is not None:
            soql = args.soql_file.read_text(encoding="utf-8")
            result = export_soql(soql, args.out_dir, **common)
        else:
            result = export_query_set(args.query_set, args.out_dir, version=args.version, **common)
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"exported {result.row_count} record(s) from {result.query_set} {result.version} "
        f"to {result.workbook}"
    )
    if not result.done:
        print("warning: Salesforce reported done=false; the result may be incomplete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
