"""Explicit analysis registry.

Adding an analysis is one import plus one entry here. No import magic, so a broken
analysis fails loudly at startup instead of disappearing from the catalog.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .base import Analysis, AnalysisError
from .rca import build as build_rca

_BUILDERS: Mapping[str, Callable[[], Analysis]] = {
    "rca": build_rca,
}


def available() -> list[str]:
    return sorted(_BUILDERS)


def get_analysis(name: str) -> Analysis:
    try:
        builder = _BUILDERS[name]
    except KeyError:
        raise AnalysisError(
            f"unknown analysis '{name}' (available: {', '.join(available())})"
        ) from None
    return builder()


__all__ = ["Analysis", "AnalysisError", "available", "get_analysis"]
