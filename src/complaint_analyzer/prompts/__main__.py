"""CLI for prompt sets: ``python -m complaint_analyzer.prompts <set> [options]``.

``<set>`` is a prompt set folder under this package (for example ``case_summary`` or
``root_cause_analysis``), a registry name such as ``rca``, or a path to a prompt set
directory. With no options, the set is validated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import PROMPTS_DIR, _FOLDERS, available, prompt_set_dir
from .base import AnalysisError
from .manifest import next_version, validate_prompt_set, write_changelog


def resolve_set(name_or_path: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return candidate.resolve()
    return PROMPTS_DIR / _FOLDERS.get(name_or_path, name_or_path)


def _list() -> int:
    status = 0
    for name in available():
        directory = prompt_set_dir(name)
        try:
            manifest = validate_prompt_set(directory)
            latest = manifest["versions"][-1]["version"]
            print(f"{name}\t{directory.name}\t{latest}\t{manifest['description']}")
        except AnalysisError as exc:
            print(f"{name}\t{directory.name}\terror: {exc}", file=sys.stderr)
            status = 1
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m complaint_analyzer.prompts",
        description="Validate a prompt set, print its next version, or regenerate its changelog.",
    )
    parser.add_argument(
        "prompt_set", nargs="?", help="prompt set folder under prompts/, or a directory path"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list registered prompts with their folder and latest version, then exit",
    )
    parser.add_argument(
        "--next-version",
        action="store_true",
        help="print the next unused version (v1 for a new set) and exit",
    )
    parser.add_argument(
        "--changelog", action="store_true", help="validate, then regenerate CHANGELOG.md"
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list()
    if not args.prompt_set:
        parser.error("prompt_set is required unless --list is given")

    directory = resolve_set(args.prompt_set)
    try:
        if args.next_version:
            print(next_version(directory))
            return 0
        if args.changelog:
            path = write_changelog(directory)
            print(f"wrote {path}")
            return 0
        manifest = validate_prompt_set(directory)
        print(f"ok: {manifest['prompt_set']} ({len(manifest['versions'])} version(s))")
        return 0
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
