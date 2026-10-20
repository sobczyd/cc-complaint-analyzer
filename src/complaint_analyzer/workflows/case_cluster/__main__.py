"""CLI: ``python -m complaint_analyzer.workflows.case_cluster <prepare|check|publish|prepare-merge|finalize>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...prompts.base import AnalysisError
from . import clustering


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.case_cluster",
        description="Batch-cluster summarized cases, then merge the batch taxonomies.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="build batch request files from a cases-with-summaries workbook")
    prep.add_argument("--workbook", type=Path, required=True)
    prep.add_argument("--out-dir", type=Path, required=True, help="new cluster run directory")
    prep.add_argument("--sheet", default=None, help="sheet name (default: first sheet)")
    prep.add_argument("--id-field", default="CaseNumber")
    prep.add_argument("--offset", type=int, default=0, help="summarized cases to skip (default 0)")
    prep.add_argument("--limit", type=int, default=100, help="cases to cluster; 0 = all (default 100)")
    prep.add_argument("--batch-size", type=int, default=100)
    prep.add_argument("--prompt-version", default=None)
    prep.add_argument("--merge-prompt-version", default=None)
    prep.add_argument("--meta-merge-prompt-version", default=None)
    prep.add_argument(
        "--merge-fanin",
        type=int,
        default=clustering.DEFAULT_MERGE_FANIN,
        help="max batches (or earlier merges) per merge request; more batches are merged in tiers "
        f"(default {clustering.DEFAULT_MERGE_FANIN})",
    )

    for name, help_text in (
        ("check", "report which requests still lack a valid response"),
        ("prepare-merge", "build the next merge tier's requests; repeat until it reports complete"),
        ("finalize", "apply the merge map and write final taxonomy, assignments and clusters.xlsx"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--dir", type=Path, required=True, help="cluster run directory")

    pub = sub.add_parser("publish", help="validate a candidate response and store it")
    pub.add_argument("--dir", type=Path, required=True)
    pub.add_argument("--request-id", required=True, help="batch_NN, merge, merge_TT_NN or meta_TT_NN")
    pub.add_argument("--candidate", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            out = clustering.prepare(
                args.workbook,
                args.out_dir,
                sheet=args.sheet,
                id_field=args.id_field,
                offset=args.offset,
                limit=args.limit or None,
                batch_size=args.batch_size,
                prompt_version=args.prompt_version,
                merge_version=args.merge_prompt_version,
                meta_merge_version=args.meta_merge_prompt_version,
                merge_fanin=args.merge_fanin,
            )
        elif args.command == "check":
            out = clustering.check(args.dir)
        elif args.command == "prepare-merge":
            out = clustering.prepare_merge(args.dir)
        elif args.command == "finalize":
            out = clustering.finalize(args.dir)
        else:
            errors = clustering.publish_response(args.dir, args.request_id, args.candidate)
            out = {"published": not errors, "request_id": args.request_id, "errors": errors}
            print(json.dumps(out, indent=2))
            return 0 if not errors else 3
    except (clustering.ClusterError, AnalysisError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("ready", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
