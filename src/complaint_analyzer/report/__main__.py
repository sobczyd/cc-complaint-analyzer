"""CLI: ``python -m complaint_analyzer.report merge --cases ... --run-dir ... --out ...``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .merge import MergeError, merge_analysis_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.report",
        description="Merge analysis results into an exported cases workbook.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser("merge", help="add color-coded generated columns to a cases workbook")
    merge.add_argument("--cases", type=Path, required=True, help="exported cases.xlsx")
    merge.add_argument("--run-dir", type=Path, required=True, help="harness run directory (holds results.jsonl)")
    merge.add_argument("--out", type=Path, required=True, help="output workbook path")
    merge.add_argument("--analysis", default="case_summary", help="registered analysis name (default: case_summary)")
    merge.add_argument("--id-field", default="CaseNumber", help="column joined to results record_id")
    merge.add_argument("--prefix", default=None, help="generated column prefix (default: analysis name)")
    args = parser.parse_args(argv)

    try:
        result = merge_analysis_run(
            args.cases,
            args.run_dir,
            args.out,
            analysis=args.analysis,
            id_field=args.id_field,
            prefix=args.prefix,
        )
    except MergeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "out": str(result.out_path),
                "analysis": result.analysis,
                "rows": result.row_count,
                "matched": result.matched,
                "status_counts": dict(result.status_counts),
                "unmatched_results": result.unmatched_results,
                "generated_columns": list(result.generated_columns),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
