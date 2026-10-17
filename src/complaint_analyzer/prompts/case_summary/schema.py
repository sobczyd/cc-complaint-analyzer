"""The JSON contract for a plain-language summary of one service record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CaseStatus = Literal["resolved", "unresolved", "unknown"]


class CaseSummaryResult(BaseModel):
    """What the model must return for one record."""

    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    reported_issue: str = ""
    product: str = ""
    actions_taken: list[str] = Field(default_factory=list)
    resolution: str = ""
    status: CaseStatus = "unknown"
    key_points: list[str] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower().replace(" ", "_").replace("-", "_")
        return value
