"""The JSON contract for a root-cause analysis of one service record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CauseStatus = Literal["documented", "hypothesized", "insufficient_evidence"]


class EvidenceItem(BaseModel):
    """One quote copied verbatim from a named input field."""

    model_config = ConfigDict(extra="ignore")

    field: str = ""
    quote: str = ""


class RcaResult(BaseModel):
    """What the model must return for one record.

    ``cause_status`` keeps a documented cause separate from a hypothesis and from an
    absence of evidence. A reboot or a replacement is a restoration action, not a cause.
    """

    model_config = ConfigDict(extra="ignore")

    symptom: str = ""
    restoration_action: str = ""
    documented_cause: str | None = None
    hypothesis: str | None = None
    cause_status: CauseStatus = "insufficient_evidence"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    needs_review: bool = True

    @field_validator("documented_cause", "hypothesis", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cause_status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower().replace(" ", "_").replace("-", "_")
        return value
