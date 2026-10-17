"""Explicit prompt registry.

Each prompt set lives in its own descriptively named folder (``root_cause_analysis``,
``case_summary``, ...) holding ``vN.txt`` prompt versions, a ``manifest.yaml`` and a
generated ``CHANGELOG.md``. Adding one is one import plus one entry here. No import
magic, so a broken prompt fails loudly at startup instead of disappearing from the catalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from .base import Analysis, AnalysisError
from .case_summary import build as build_case_summary
from .root_cause_analysis import build as build_rca

PROMPTS_DIR = Path(__file__).parent

# Registry key (used by ``analysis.name`` in config) -> builder.
_BUILDERS: Mapping[str, Callable[[], Analysis]] = {
    "case_summary": build_case_summary,
    "rca": build_rca,
}

# Registry key -> prompt-set folder name, where the two differ.
_FOLDERS: Mapping[str, str] = {
    "rca": "root_cause_analysis",
}


def available() -> list[str]:
    return sorted(_BUILDERS)


def prompt_set_dir(name: str) -> Path:
    """Return the folder holding a registered prompt's versions and manifest."""
    if name not in _BUILDERS:
        raise AnalysisError(f"unknown analysis '{name}' (available: {', '.join(available())})")
    return PROMPTS_DIR / _FOLDERS.get(name, name)


def get_analysis(name: str) -> Analysis:
    try:
        builder = _BUILDERS[name]
    except KeyError:
        raise AnalysisError(
            f"unknown analysis '{name}' (available: {', '.join(available())})"
        ) from None
    return builder()


__all__ = ["PROMPTS_DIR", "Analysis", "AnalysisError", "available", "get_analysis", "prompt_set_dir"]
