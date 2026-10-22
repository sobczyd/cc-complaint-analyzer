"""CLI.

``python -m complaint_analyzer.workflows.powerbi_export --cases cases.xlsx [--out powerbi.xlsx]`` writes the
workbook; ``... powerbi_export compare --ours powerbi.xlsx [--dashboard salesforce.xlsx]`` runs the parity check.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compare import compare, write_report
from .export import DEFAULT_TEMPLATE, PowerBIExportError, export_powerbi
from .package import build_package


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["compare"]:
        return compare_main(argv[1:])
    if argv[:1] == ["package"]:
        return package_main(argv[1:])
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
        f"{result['kb_titles']} KB title(s), {result['serial_numbers']} case(s) with serial numbers, "
        f"{result['pre_post_serials']} with old/new serials"
    )
    if result["extra_problem_codes"] or result["extra_qualifications"]:
        print(
            f"warning: {result['extra_problem_codes']} extra problem code(s) and "
            f"{result['extra_qualifications']} extra complaint qualification(s) were dropped "
            "(first problem code and latest CQ are used)",
            file=sys.stderr,
        )
    return 0


def package_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.powerbi_export package",
        description="Write FactSource, DimID, DimCluster, DimDefect and DimSummary workbooks to <run>\\powerbi_export_package.",
    )
    parser.add_argument("--run", type=Path, required=True, help="run folder containing cases.xlsx")
    parser.add_argument("--comparison", type=Path, default=None, help="compare_* folder or comparison.xlsx for DimCluster")
    parser.add_argument("--clusters", default=None, help="clusters\\<name> used when no comparison is given")
    parser.add_argument("--defects", default=None, help="defects\\<name> holding mappings.xlsx (default: newest)")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <run>\\powerbi_export_package")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--kb-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        result = build_package(
            args.run, comparison=args.comparison, clusters=args.clusters, defects=args.defects,
            out_dir=args.out_dir, template=args.template, kb_dir=args.kb_dir,
        )
    except PowerBIExportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {result['out_dir']}: " + ", ".join(f"{k} {v}" for k, v in result["rows"].items()) + " row(s)")
    print("coverage: " + ", ".join(f"{k} {v}" for k, v in result["coverage"].items()))
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def compare_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.powerbi_export compare",
        description="Compare a generated powerbi.xlsx with the Power BI dashboard workbook, column by column.",
    )
    parser.add_argument("--ours", type=Path, required=True, help="generated powerbi.xlsx")
    parser.add_argument("--dashboard", type=Path, default=DEFAULT_TEMPLATE, help="dashboard workbook")
    parser.add_argument("--state", default="Closed", help="Source State both rows must have; 'any' disables")
    parser.add_argument("--out", type=Path, default=None, help="default: powerbi_compare.xlsx next to --ours")
    args = parser.parse_args(argv)
    out = args.out or args.ours.with_name("powerbi_compare.xlsx")
    try:
        result = compare(args.ours, args.dashboard, state=None if args.state.lower() == "any" else args.state)
    except PowerBIExportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    write_report(result, out)
    counts: dict[str, int] = {}
    for column in result["columns"]:
        counts[column["status"]] = counts.get(column["status"], 0) + 1
    print(
        f"wrote {out}: {result['cases']} case(s) compared ({result['overlap']} of {result['ours_cases']} "
        f"in the dashboard); " + ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
    )
    for column in result["columns"]:
        if column["status"] == "Not Matched":
            print(f"  not matched: {column['column']} ({column['matched']}/{column['compared']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
