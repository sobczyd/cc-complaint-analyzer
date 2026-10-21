"""CLI: ``python -m complaint_analyzer.workflows.compare_periods <list-clusters|prepare|check|publish|finalize>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...prompts.base import AnalysisError
from . import compare


def _add_period(parser: argparse.ArgumentParser, key: str, *, required_run: bool) -> None:
    name = key.upper()
    parser.add_argument(f"--{key}-run", type=Path, required=required_run, help=f"run folder of period {name}")
    parser.add_argument(f"--{key}-clusters", default=None, help=f"cluster directory name under the run's clusters\\ (default: best finalized)")
    parser.add_argument(f"--{key}-start", default=None, help="first CreatedDate to include, YYYY-MM-DD")
    parser.add_argument(f"--{key}-end", default=None, help="last CreatedDate to include (inclusive), YYYY-MM-DD")
    parser.add_argument(f"--{key}-label", default=None, help=f"display label of period {name}, e.g. 'Sep 2026'")


def _spec(args: argparse.Namespace, key: str) -> compare.PeriodSpec:
    run = getattr(args, f"{key}_run") or args.a_run
    return compare.PeriodSpec(
        key.upper(),
        run,
        getattr(args, f"{key}_clusters"),
        compare.parse_date(getattr(args, f"{key}_start"), f"--{key}-start"),
        compare.parse_date(getattr(args, f"{key}_end"), f"--{key}-end"),
        getattr(args, f"{key}_label"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.compare_periods",
        description="Compare the clusters of two time points, mapping the later one onto the baseline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list-clusters", help="list a run's cluster directories, best candidate first")
    listing.add_argument("--run", type=Path, required=True)

    prep = sub.add_parser("prepare", help="load both periods and build the resolution requests")
    prep.add_argument("--out-dir", type=Path, default=None, help="new comparison folder (default: data\\runs\\compare_...)")
    _add_period(prep, "a", required_run=True)
    _add_period(prep, "b", required_run=False)
    prep.add_argument("--date-field", default="CreatedDate")
    prep.add_argument("--id-field", default="CaseNumber")
    prep.add_argument("--comparison-type", default="clusters", choices=compare.COMPARISON_TYPES)
    prep.add_argument("--batch-size", type=int, default=compare.DEFAULT_BATCH_SIZE, help="B sub-clusters per request")
    prep.add_argument("--min-change", type=int, default=compare.DEFAULT_MIN_CHANGE,
                      help="flag UPTICK/DECLINE when the change exceeds this many cases")
    prep.add_argument("--min-cases", type=int, default=compare.DEFAULT_MIN_CASES,
                      help="...and at least one period has this many cases")
    prep.add_argument("--flag-basis", default="count", choices=compare.FLAG_BASES,
                      help="count (raw) or per_day (A scaled to B's number of days)")
    prep.add_argument("--prompt-version", default=None)
    prep.add_argument("--request", default="", help="the user's request, recorded in the manifest")

    for name, help_text in (
        ("check", "report which requests still lack a valid response"),
        ("finalize", "apply the mapping and write the comparison workbook, summary and audit files"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--dir", type=Path, required=True, help="comparison folder")

    pub = sub.add_parser("publish", help="validate a candidate response and store it")
    pub.add_argument("--dir", type=Path, required=True)
    pub.add_argument("--request-id", required=True, help="resolve_NN")
    pub.add_argument("--candidate", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "list-clusters":
            clusters = compare.list_cluster_dirs(args.run)
            out = {"run": str(args.run), "clusters": clusters,
                   "suggested": next((c["name"] for c in clusters if c["finalized"]), None)}
        elif args.command == "prepare":
            a, b = _spec(args, "a"), _spec(args, "b")
            out_dir = args.out_dir or compare.default_out_dir(a, b)
            out = compare.prepare(
                out_dir, a, b,
                date_field=args.date_field, id_field=args.id_field, comparison_type=args.comparison_type,
                batch_size=args.batch_size, min_change=args.min_change, min_cases=args.min_cases,
                flag_basis=args.flag_basis, prompt_version=args.prompt_version, request_text=args.request,
            )
        elif args.command == "check":
            out = compare.check(args.dir)
        elif args.command == "finalize":
            out = compare.finalize(args.dir)
        else:
            errors = compare.publish_response(args.dir, args.request_id, args.candidate)
            out = {"published": not errors, "request_id": args.request_id, "errors": errors}
            print(json.dumps(out, indent=2))
            return 0 if not errors else 3
    except (compare.CompareError, AnalysisError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("ready", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
