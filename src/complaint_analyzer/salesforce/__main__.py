"""CLI: run a versioned query set against Salesforce and write ``cases.xlsx``.

    python -m complaint_analyzer.salesforce export --query-set nurse_call_last_7_days \
        --out-dir data/runs/my_export [--version v1] [--target-org hillrom] [--from-json raw.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export import DEFAULT_ID_FIELD, DEFAULT_TIMEOUT_SECONDS, ExportError, export_query_set


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m complaint_analyzer.salesforce")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="run a query set and write cases.xlsx")
    export.add_argument("--query-set", required=True, help="folder under queries/")
    export.add_argument("--version", help="query version, for example v1 (default: latest)")
    export.add_argument("--out-dir", required=True, type=Path)
    export.add_argument("--target-org", help="sf org alias or username (default: sf default)")
    export.add_argument(
        "--from-json", type=Path, help="replay a saved 'sf data query --json' response"
    )
    export.add_argument("--id-field", default=DEFAULT_ID_FIELD)
    export.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = export_query_set(
            args.query_set,
            args.out_dir,
            version=args.version,
            target_org=args.target_org,
            from_json=args.from_json,
            id_field=args.id_field,
            timeout=args.timeout,
        )
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
