"""CLI: ``python -m complaint_analyzer.workflows.powerbi_export --cases cases.xlsx [--out powerbi.xlsx]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export import DEFAULT_TEMPLATE, PowerBIExportError, export_powerbi


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.powerbi_export",
        description="Write a Power BI workbook in the data\\input\\salesforce.xlsx layout from cases.xlsx.",
    )
    parser.add_argument("--cases", type=Path, required=True, help="exported cases.xlsx")
    parser.add_argument("--out", type=Path, default=None, help="default: powerbi.xlsx next to --cases")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="workbook whose header row to copy")
    parser.add_argument("--kb-dir", type=Path, default=None, help="data\\kb\\<name> corpus (articles.jsonl) for Reference Name")
    args = parser.parse_args(argv)
    out = args.out or args.cases.with_name("powerbi.xlsx")
    try:
        result = export_powerbi(args.cases, out, template=args.template, kb_dir=args.kb_dir)
    except PowerBIExportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"wrote {result['out']}: {result['cases']} case(s), {result['columns']} columns, "
        f"{result['kb_titles']} KB title(s)"
    )
    if result["extra_problem_codes"] or result["extra_qualifications"]:
        print(
            f"warning: {result['extra_problem_codes']} extra problem code(s) and "
            f"{result['extra_qualifications']} extra complaint qualification(s) were dropped "
            "(first problem code and latest CQ are used)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
