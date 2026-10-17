"""Reloadable Salesforce (or other) query text, organized like analysis prompts.

Each subdirectory under ``queries/`` is a named query set::

    queries/<query_set>/
        v1.txt, v2.txt, ...   # query text, one file per version, never overwritten
        manifest.yaml         # per-version prompt, summary, changes, dates, validation
        CHANGELOG.md          # generated from manifest.yaml

Load one with ``load_queries(directory)``:

    from pathlib import Path
    from complaint_analyzer.queries import load_queries

    _DIR = Path(__file__).parent / "cq_crm_codes_nurse_call_no_comments"
    versions = load_queries(_DIR)
    query_v2 = versions["v2"]

Validate a set, get its next version, or regenerate its changelog from the CLI::

    python -m complaint_analyzer.queries <query_set>
    python -m complaint_analyzer.queries <query_set> --next-version
    python -m complaint_analyzer.queries <query_set> --changelog
"""

from __future__ import annotations

from .base import QueryError, load_queries, version_number, version_sort_key
from .manifest import (
    CHANGELOG_FILENAME,
    MANIFEST_FILENAME,
    load_manifest,
    next_version,
    render_changelog,
    validate_query_set,
    write_changelog,
)

__all__ = [
    "CHANGELOG_FILENAME",
    "MANIFEST_FILENAME",
    "QueryError",
    "load_manifest",
    "load_queries",
    "next_version",
    "render_changelog",
    "validate_query_set",
    "version_number",
    "version_sort_key",
    "write_changelog",
]
