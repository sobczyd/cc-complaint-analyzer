"""Load versioned query text files, the same way prompt sets load prompt text.

A "query set" is a directory of ``<version>.txt`` files (for example ``v1.txt``,
``v2.txt``) holding SOQL (or other) query text that is meant to be reloaded verbatim,
not generated.
"""

from __future__ import annotations

from pathlib import Path

from ..versioning import version_number, version_sort_key

__all__ = ["QueryError", "load_queries", "version_number", "version_sort_key"]


class QueryError(Exception):
    """Raised when a query directory or a specific query version is missing."""


def load_queries(directory: Path) -> dict[str, str]:
    """Load ``<version>.txt`` files from a query set's directory, in version order."""
    if not directory.is_dir():
        raise QueryError(f"query directory not found: {directory}")
    paths = sorted(directory.glob("*.txt"), key=lambda path: version_sort_key(path.stem))
    queries = {path.stem: path.read_text(encoding="utf-8") for path in paths}
    if not queries:
        raise QueryError(f"no query files (*.txt) in {directory}")
    return queries
