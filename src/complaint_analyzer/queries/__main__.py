"""CLI for query sets: ``python -m complaint_analyzer.queries <set> [options]``.

``<set>`` is a query set name under this package (for example
``cq_crm_codes_nurse_call_no_comments``) or a path to a query set directory.
With no options, the set is validated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .base import QueryError
from .manifest import next_version, validate_query_set, write_changelog

QUERIES_DIR = Path(__file__).parent


def resolve_set(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return candidate.resolve()
    return QUERIES_DIR / name_or_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.queries",
        description="Validate a query set, print its next version, or regenerate its changelog.",
    )
    parser.add_argument("query_set", help="query set name under queries/, or a directory path")
    parser.add_argument(
        "--next-version",
        action="store_true",
        help="print the next unused version (v1 for a new set) and exit",
    )
    parser.add_argument(
        "--changelog", action="store_true", help="validate, then regenerate CHANGELOG.md"
    )
    args = parser.parse_args(argv)

    directory = resolve_set(args.query_set)
    try:
        if args.next_version:
            print(next_version(directory))
            return 0
        if args.changelog:
            path = write_changelog(directory)
            print(f"wrote {path}")
            return 0
        manifest = validate_query_set(directory)
        print(f"ok: {manifest['query_set']} ({len(manifest['versions'])} version(s))")
        return 0
    except QueryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
