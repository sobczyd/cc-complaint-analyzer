"""Version tracking for query sets: ``manifest.yaml`` plus a generated ``CHANGELOG.md``.

Every query set directory holds ``v1.txt``, ``v2.txt``, ... and one ``manifest.yaml``
describing each version: the prompt that produced it, what changed, which Salesforce
objects it touches, when it was written, and how it was validated against an org.
``CHANGELOG.md`` is generated from the manifest and never edited by hand.

Manifest shape::

    query_set: cq_crm_codes_nurse_call_no_comments   # must equal the directory name
    description: What the set is for.
    created: "2026-10-15"
    updated: "2026-10-15"
    versions:
      - version: v1                 # sequential: v1, v2, v3, ...
        file: v1.txt                # must equal "<version>.txt"
        created: "2026-10-15"
        author: copilot             # optional
        base_version: null          # optional; an earlier version this one revises
        prompt: The request that produced this version.
        summary: One-line description of the version.
        changes:                    # non-empty list of strings
          - Initial version.
        objects: [Case]             # optional list of sObjects / relationships
        validation:                 # optional
          org: alias-or-username
          validated_at: "2026-10-15T12:00:00Z"
          status: passed            # passed | failed | skipped
          row_count: 5
          notes: Free text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import versioning
from ..versioning import CHANGELOG_FILENAME, MANIFEST_FILENAME, VALIDATION_STATUSES
from .base import QueryError

__all__ = [
    "CHANGELOG_FILENAME",
    "KIND",
    "MANIFEST_FILENAME",
    "VALIDATION_STATUSES",
    "load_manifest",
    "next_version",
    "render_changelog",
    "validate_query_set",
    "write_changelog",
]

KIND = versioning.SetKind(
    set_key="query_set",
    error=QueryError,
    cli_module="complaint_analyzer.queries",
    list_fields={"objects": "Objects"},
)


def load_manifest(directory: Path) -> dict[str, Any]:
    """Read and structurally check a query set's ``manifest.yaml``."""
    return versioning.load_manifest(KIND, directory)


def validate_query_set(directory: Path) -> dict[str, Any]:
    """Check that the manifest and the ``vN.txt`` files agree; return the manifest."""
    return versioning.validate_set(KIND, directory)


def next_version(directory: Path) -> str:
    """Return the next unused ``vN`` for a query set (``v1`` for a new or empty set)."""
    return versioning.next_version(KIND, directory)


def render_changelog(manifest: dict[str, Any]) -> str:
    """Render a Markdown changelog (newest version first) from a manifest."""
    return versioning.render_changelog(KIND, manifest)


def write_changelog(directory: Path) -> Path:
    """Validate the set and (re)write its ``CHANGELOG.md``; return the path written."""
    return versioning.write_changelog(KIND, directory)
