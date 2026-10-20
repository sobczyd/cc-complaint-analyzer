"""CLI: ``python -m complaint_analyzer.workflows.defect_mapping <command>``.

Corpus commands (``jira-plan``, ``jira-normalize``, ``jira-comment-dataset``, ``kb-plan``,
``kb-normalize``) build reusable inputs; the mapping commands (``prepare``, ``check``,
``publish``, ``finalize``) run the sub-cluster batches.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...prompts.base import AnalysisError
from . import jira, kb, mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.workflows.defect_mapping",
        description="Map clustered complaints to existing Jira defects and RCAs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    jira_plan = sub.add_parser("jira-plan", help="create a Jira corpus directory with the JQL to run")
    jira_plan.add_argument("--out-dir", type=Path, required=True)
    jira_plan.add_argument("--kind", choices=sorted(jira.PROJECTS), required=True)
    jira_plan.add_argument("--jql", default=None, help="override the default JQL")

    jira_norm = sub.add_parser("jira-normalize", help="turn saved raw pages into issues.jsonl / issues.xlsx")
    jira_norm.add_argument("--dir", type=Path, required=True)
    jira_norm.add_argument("--summaries", type=Path, default=None, help="comment-summary results.jsonl")

    comments = sub.add_parser("jira-comment-dataset", help="workbook of issues whose comments need summarizing")
    comments.add_argument("--dir", type=Path, required=True)
    comments.add_argument("--out", type=Path, required=True)

    kb_plan = sub.add_parser("kb-plan", help="list the KB articles cited by the selected cases")
    kb_plan.add_argument("--out-dir", type=Path, required=True)
    kb_plan.add_argument("--workbook", type=Path, required=True, help="cases workbook with a CQ sheet")
    kb_plan.add_argument("--assignments", type=Path, default=None, help="limit to these cases")

    kb_norm = sub.add_parser("kb-normalize", help="turn saved Confluence pages into articles.jsonl")
    kb_norm.add_argument("--dir", type=Path, required=True)

    prep = sub.add_parser("prepare", help="build one request per sub-cluster batch")
    prep.add_argument("--assignments", type=Path, required=True, help="case_assignments.jsonl")
    prep.add_argument("--out-dir", type=Path, required=True)
    prep.add_argument("--workbook", type=Path, required=True)
    prep.add_argument("--corpus", type=Path, action="append", required=True, help="repeatable")
    prep.add_argument("--kb-dir", type=Path, default=None)
    prep.add_argument("--min-batch", type=int, default=mapping.DEFAULT_MIN_BATCH)
    prep.add_argument("--max-batch", type=int, default=mapping.DEFAULT_MAX_BATCH)
    prep.add_argument("--candidates", type=int, default=mapping.DEFAULT_CANDIDATES)
    prep.add_argument("--per-case", type=int, default=mapping.DEFAULT_PER_CASE)
    prep.add_argument("--prompt-version", default=None)

    for name, help_text in (
        ("check", "report which requests still lack a valid response"),
        ("candidate-keys", "list the issue keys offered as candidates in a prepared run"),
        ("finalize", "combine direct links and responses into mappings.jsonl / mappings.xlsx"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--dir", type=Path, required=True)

    pub = sub.add_parser("publish", help="validate a candidate response and store it")
    pub.add_argument("--dir", type=Path, required=True)
    pub.add_argument("--request-id", required=True)
    pub.add_argument("--candidate", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "jira-plan":
            out = jira.plan(args.out_dir, kind=args.kind, jql=args.jql)
        elif args.command == "jira-normalize":
            out = jira.normalize(args.dir, summaries=args.summaries)
        elif args.command == "jira-comment-dataset":
            out = jira.comment_dataset(args.dir, args.out)
        elif args.command == "kb-plan":
            numbers = _case_numbers(args.assignments)
            out = kb.plan(args.out_dir, workbook=args.workbook, case_numbers=numbers)
        elif args.command == "kb-normalize":
            out = kb.normalize(args.dir)
        elif args.command == "prepare":
            out = mapping.prepare(
                args.assignments,
                args.out_dir,
                workbook=args.workbook,
                corpora=args.corpus,
                kb_dir=args.kb_dir,
                min_batch=args.min_batch,
                max_batch=args.max_batch,
                candidates=args.candidates,
                per_case=args.per_case,
                prompt_version=args.prompt_version,
            )
            out = {key: value for key, value in out.items() if key != "requests"} | {
                "request_count": len(out["requests"])
            }
        elif args.command == "check":
            out = mapping.check(args.dir)
        elif args.command == "candidate-keys":
            out = mapping.candidate_keys(args.dir)
        elif args.command == "finalize":
            out = mapping.finalize(args.dir)
        else:
            errors = mapping.publish_response(args.dir, args.request_id, args.candidate)
            print(json.dumps({"published": not errors, "request_id": args.request_id, "errors": errors}, indent=2))
            return 0 if not errors else 3
    except (jira.JiraCorpusError, kb.KbCorpusError, mapping.MappingError, AnalysisError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    return 0 if out.get("ready", True) else 1


def _case_numbers(assignments: Path | None) -> list[str] | None:
    if assignments is None:
        return None
    lines = assignments.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["case_number"] for line in lines if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
