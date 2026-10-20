"""CLI: python -m complaint_analyzer.workflows.classify_complaints <state|diagram> --run DIR"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import write_diagram


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="classify_complaints")
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state", help="Record workflow choices in classification.json")
    state.add_argument("--run", required=True)
    state.add_argument("--set", nargs="+", metavar="KEY=VALUE", default=[])

    diagram = sub.add_parser("diagram", help="(Re)generate workflow.md with a Mermaid diagram")
    diagram.add_argument("--run", required=True)

    args = parser.parse_args(argv)
    run = Path(args.run)
    if not run.is_dir():
        parser.error(f"run folder not found: {run}")

    if args.command == "state":
        path = run / "classification.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for item in args.set:
            key, _, value = item.partition("=")
            data[key] = int(value) if value.isdigit() else value
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(path)
    else:
        print(write_diagram(run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
