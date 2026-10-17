"""Plain-language summary of a single service record."""

from __future__ import annotations

from pathlib import Path

from ..base import Analysis, load_prompts
from .schema import CaseSummaryResult

_PROMPTS_DIR = Path(__file__).parent


def build() -> Analysis:
    return Analysis(
        name="case_summary",
        prompts=load_prompts(_PROMPTS_DIR),
        result_model=CaseSummaryResult,
    )


__all__ = ["build", "CaseSummaryResult"]
