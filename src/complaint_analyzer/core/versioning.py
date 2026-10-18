"""Shared version tracking for directories of ``v1.txt``, ``v2.txt``, ... files.

Query sets (``complaint_analyzer.queries``) and prompt sets
(``complaint_analyzer.prompts``) use the same layout:

    <set_name>/
        v1.txt
        v2.txt
        manifest.yaml     # one entry per version: prompt, summary, changes, dates, validation
        CHANGELOG.md      # generated from manifest.yaml, never edited by hand

A :class:`SetKind` names the manifest's top-level key (``query_set`` or ``prompt_set``),
the error type to raise, the CLI that regenerates the changelog, and which optional
per-version fields to check and render. Everything else is shared.

Common manifest shape::

    <set_key>: <directory name>
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
        validation:                 # optional
          status: passed            # passed | failed | skipped
          validated_at: "2026-10-15T12:00:00Z"
          notes: Free text.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

MANIFEST_FILENAME = "manifest.yaml"
CHANGELOG_FILENAME = "CHANGELOG.md"
VALIDATION_STATUSES = frozenset({"passed", "failed", "skipped"})

_VERSION_RE = re.compile(r"^v(\d+)$")
_REQUIRED_VERSION = ("version", "file", "created", "prompt", "summary", "changes")

# Validation keys rendered in the changelog, in order, with how to label them.
_VALIDATION_PARTS: tuple[tuple[str, str], ...] = (
    ("org", "org `{}`"),
    ("model", "model `{}`"),
    ("run_id", "run `{}`"),
    ("validated_at", "at {}"),
    ("row_count", "{} row(s)"),
    ("record_count", "{} record(s)"),
)


def version_number(stem: str) -> int | None:
    """Return ``N`` for a ``vN`` version stem, or ``None`` if it isn't one."""
    match = _VERSION_RE.match(stem)
    return int(match.group(1)) if match else None


def version_sort_key(stem: str) -> tuple[int, int, str]:
    """Sort ``vN`` stems numerically (``v2`` before ``v10``), then anything else by name."""
    number = version_number(stem)
    return (0, number, stem) if number is not None else (1, 0, stem)


@dataclass(frozen=True)
class SetKind:
    """What differs between kinds of versioned sets."""

    set_key: str
    error: type[Exception]
    cli_module: str
    # Optional per-version list fields, mapped to their changelog label.
    list_fields: Mapping[str, str] = field(default_factory=dict)
    # Optional per-version scalar fields, mapped to their changelog label.
    scalar_fields: Mapping[str, str] = field(default_factory=dict)


def _as_text(value: Any) -> str:
    """Render YAML scalars (including auto-parsed dates) as plain strings."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return "" if value is None else str(value)


def load_manifest(kind: SetKind, directory: Path) -> dict[str, Any]:
    """Read and structurally check a set's ``manifest.yaml``."""
    path = directory / MANIFEST_FILENAME
    if not path.is_file():
        raise kind.error(f"manifest not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise kind.error(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise kind.error(f"manifest must be a mapping: {path}")

    problems: list[str] = []
    for key in (kind.set_key, "description", "created", "updated", "versions"):
        if key not in data or data[key] in (None, ""):
            problems.append(f"missing top-level key '{key}'")
    versions = data.get("versions")
    if versions is not None and not isinstance(versions, list):
        problems.append("'versions' must be a list")
        versions = []
    for index, entry in enumerate(versions or []):
        problems.extend(_check_version_entry(kind, index, entry))
    if problems:
        raise kind.error(f"{path}: " + "; ".join(problems))
    return data


def _check_version_entry(kind: SetKind, index: int, entry: Any) -> list[str]:
    label = f"versions[{index}]"
    if not isinstance(entry, dict):
        return [f"{label} must be a mapping"]
    problems = [
        f"{label} missing '{key}'" for key in _REQUIRED_VERSION if entry.get(key) in (None, "", [])
    ]
    changes = entry.get("changes")
    if changes is not None and (
        not isinstance(changes, list) or not all(isinstance(c, str) and c.strip() for c in changes)
    ):
        problems.append(f"{label} 'changes' must be a list of non-empty strings")
    for name in kind.list_fields:
        value = entry.get(name)
        if value is not None and not isinstance(value, list):
            problems.append(f"{label} '{name}' must be a list")
    validation = entry.get("validation")
    if validation is not None:
        if not isinstance(validation, dict):
            problems.append(f"{label} 'validation' must be a mapping")
        elif validation.get("status") not in VALIDATION_STATUSES:
            problems.append(
                f"{label} validation.status must be one of {sorted(VALIDATION_STATUSES)}"
            )
    return problems


def validate_set(kind: SetKind, directory: Path) -> dict[str, Any]:
    """Check that the manifest and the ``vN.txt`` files agree; return the manifest.

    Raises ``kind.error`` listing every problem found.
    """
    manifest = load_manifest(kind, directory)
    problems: list[str] = []

    if manifest[kind.set_key] != directory.name:
        problems.append(
            f"{kind.set_key} '{manifest[kind.set_key]}' does not match directory '{directory.name}'"
        )

    declared: list[str] = []
    for position, entry in enumerate(manifest["versions"], start=1):
        version = str(entry["version"])
        declared.append(version)
        if version != f"v{position}":
            problems.append(f"versions must be sequential: expected v{position}, found {version}")
        if entry["file"] != f"{version}.txt":
            problems.append(f"{version}: file must be '{version}.txt', found '{entry['file']}'")
        elif not (directory / entry["file"]).is_file():
            problems.append(f"{version}: file {entry['file']} does not exist")
        base = entry.get("base_version")
        if base is not None:
            base_number = version_number(str(base))
            if base_number is None or base_number >= position:
                problems.append(f"{version}: base_version '{base}' must be an earlier version")

    on_disk = sorted((p.stem for p in directory.glob("*.txt")), key=version_sort_key)
    for stem in on_disk:
        if stem not in declared:
            problems.append(f"{stem}.txt has no manifest entry")

    if problems:
        raise kind.error(f"{directory}: " + "; ".join(problems))
    return manifest


def next_version(kind: SetKind, directory: Path) -> str:
    """Return the next unused ``vN`` for a set (``v1`` for a new or empty set)."""
    highest = 0
    if directory.is_dir():
        for path in directory.glob("*.txt"):
            number = version_number(path.stem)
            if number is not None:
                highest = max(highest, number)
        if (directory / MANIFEST_FILENAME).is_file():
            for entry in load_manifest(kind, directory)["versions"]:
                number = version_number(str(entry["version"]))
                if number is not None:
                    highest = max(highest, number)
    return f"v{highest + 1}"


def render_changelog(kind: SetKind, manifest: dict[str, Any]) -> str:
    """Render a Markdown changelog (newest version first) from a manifest."""
    name = manifest[kind.set_key]
    lines = [
        f"# {name} changelog",
        "",
        f"<!-- Generated from manifest.yaml by `python -m {kind.cli_module}"
        f" {name} --changelog`. Do not edit by hand. -->",
        "",
        str(manifest["description"]).strip(),
        "",
        f"- Created: {_as_text(manifest['created'])}",
        f"- Last updated: {_as_text(manifest['updated'])}",
        f"- Versions: {len(manifest['versions'])}",
        "",
    ]
    for entry in reversed(manifest["versions"]):
        lines.append(f"## {entry['version']} — {_as_text(entry['created'])}")
        lines.append("")
        lines.append(f"**Summary:** {str(entry['summary']).strip()}")
        lines.append("")
        meta = [f"- File: `{entry['file']}`"]
        if entry.get("base_version"):
            meta.append(f"- Based on: {entry['base_version']}")
        if entry.get("author"):
            meta.append(f"- Author: {entry['author']}")
        for key, label in kind.scalar_fields.items():
            if entry.get(key):
                meta.append(f"- {label}: `{_as_text(entry[key])}`")
        for key, label in kind.list_fields.items():
            if entry.get(key):
                meta.append(f"- {label}: " + ", ".join(f"`{item}`" for item in entry[key]))
        lines.extend(meta)
        lines.append("")
        lines.append("**Changes:**")
        lines.append("")
        lines.extend(f"- {change.strip()}" for change in entry["changes"])
        lines.append("")
        lines.append("**Prompt:**")
        lines.append("")
        lines.extend(f"> {line}" if line else ">" for line in str(entry["prompt"]).strip().splitlines())
        lines.append("")
        validation = entry.get("validation")
        if validation:
            parts = [f"status `{validation['status']}`"]
            for key, template in _VALIDATION_PARTS:
                if validation.get(key) is not None and validation.get(key) != "":
                    parts.append(template.format(_as_text(validation[key])))
            lines.append("**Validation:** " + ", ".join(parts))
            if validation.get("notes"):
                lines.append("")
                lines.append(f"_{str(validation['notes']).strip()}_")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_changelog(kind: SetKind, directory: Path) -> Path:
    """Validate the set and (re)write its ``CHANGELOG.md``; return the path written."""
    manifest = validate_set(kind, directory)
    path = directory / CHANGELOG_FILENAME
    path.write_text(render_changelog(kind, manifest), encoding="utf-8")
    return path
