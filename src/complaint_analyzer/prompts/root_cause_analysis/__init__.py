"""Root cause analysis of a single service record."""

from __future__ import annotations

from pathlib import Path

from ..base import Analysis, load_prompts
from .schema import RcaResult
from .validators import check_cause_consistency, check_evidence_quotes

_PROMPTS_DIR = Path(__file__).parent


def build() -> Analysis:
    return Analysis(
        name="rca",
        prompts=load_prompts(_PROMPTS_DIR),
        result_model=RcaResult,
        validators=(check_evidence_quotes, check_cause_consistency),
    )


__all__ = ["build", "RcaResult"]
