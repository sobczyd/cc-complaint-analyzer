"""Load versioned query text files, the same way analyses load prompt text.

A "query set" is a directory of ``<version>.txt`` files (for example ``v1.txt``,
``v2.txt``) holding SOQL (or other) query text that is meant to be reloaded verbatim,
not generated.
"""

from __future__ import annotations

from pathlib import Path


class QueryError(Exception):
    """Raised when a query directory or a specific query version is missing."""


def load_queries(directory: Path) -> dict[str, str]:
    """Load ``<version>.txt`` files from a query set's directory."""
    if not directory.is_dir():
        raise QueryError(f"query directory not found: {directory}")
    queries = {path.stem: path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.txt"))}
    if not queries:
        raise QueryError(f"no query files (*.txt) in {directory}")
    return queries
