"""Version tracking for prompt sets: ``manifest.yaml`` plus a generated ``CHANGELOG.md``.

Every prompt set directory (``root_cause_analysis``, ``case_summary``, ...) holds
``v1.txt``, ``v2.txt``, ... and one ``manifest.yaml`` describing each version: the request
that produced it, what changed, which result model it targets, when it was written, and
how it was checked. ``CHANGELOG.md`` is generated from the manifest and never edited by hand.

Manifest shape::

    prompt_set: case_summary          # must equal the directory name
    description: What the prompt is for.
    created: "2026-10-15"
    updated: "2026-10-15"
    versions:
      - version: v1                   # sequential: v1, v2, v3, ...
        file: v1.txt                  # must equal "<version>.txt"
        created: "2026-10-15"
        author: copilot               # optional
        base_version: null            # optional; an earlier version this one revises
        prompt: The request that produced this version.
        summary: One-line description of the version.
        changes:                      # non-empty list of strings
          - Initial version.
        result_model: CaseSummaryResult   # optional; the Pydantic schema the output targets
        validation:                   # optional
          model: gpt-4.1
          run_id: 2026-10-15-smoke
          validated_at: "2026-10-15T12:00:00Z"
          status: passed              # passed | failed | skipped
          record_count: 10
          notes: Free text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import versioning
from ..versioning import CHANGELOG_FILENAME, MANIFEST_FILENAME, VALIDATION_STATUSES
from .base import AnalysisError

__all__ = [
    "CHANGELOG_FILENAME",
    "KIND",
    "MANIFEST_FILENAME",
    "VALIDATION_STATUSES",
    "load_manifest",
    "next_version",
    "render_changelog",
    "validate_prompt_set",
    "write_changelog",
]

KIND = versioning.SetKind(
    set_key="prompt_set",
    error=AnalysisError,
    cli_module="complaint_analyzer.prompts",
    scalar_fields={"result_model": "Result model"},
)


def load_manifest(directory: Path) -> dict[str, Any]:
    """Read and structurally check a prompt set's ``manifest.yaml``."""
    return versioning.load_manifest(KIND, directory)


def validate_prompt_set(directory: Path) -> dict[str, Any]:
    """Check that the manifest and the ``vN.txt`` files agree; return the manifest."""
    return versioning.validate_set(KIND, directory)


def next_version(directory: Path) -> str:
    """Return the next unused ``vN`` for a prompt set (``v1`` for a new or empty set)."""
    return versioning.next_version(KIND, directory)


def render_changelog(manifest: dict[str, Any]) -> str:
    """Render a Markdown changelog (newest version first) from a manifest."""
    return versioning.render_changelog(KIND, manifest)


def write_changelog(directory: Path) -> Path:
    """Validate the set and (re)write its ``CHANGELOG.md``; return the path written."""
    return versioning.write_changelog(KIND, directory)
