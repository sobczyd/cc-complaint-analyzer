"""JSON contract for resolving a later period's sub-clusters onto a baseline taxonomy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_LABEL_WORDS = 8


def _check_label(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("label must not be blank")
    if len(value.split()) > MAX_LABEL_WORDS:
        raise ValueError(f"label '{value}' is longer than {MAX_LABEL_WORDS} words")
    return value


class ResolveMapping(BaseModel):
    """Where one later-period sub-cluster lands relative to the baseline taxonomy."""

    model_config = ConfigDict(extra="ignore")

    subcluster_id: str
    decision: Literal["match", "new"]
    baseline_subcluster_id: str | None = None
    new_cluster: str | None = None
    new_subcluster: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    rationale: str = ""

    @field_validator("baseline_subcluster_id", "new_cluster", "new_subcluster", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("new_cluster", "new_subcluster")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return None if value is None else _check_label(value)

    @model_validator(mode="after")
    def _consistent(self) -> "ResolveMapping":
        if self.decision == "match" and not self.baseline_subcluster_id:
            raise ValueError("decision 'match' requires baseline_subcluster_id")
        if self.decision == "new" and not (self.new_cluster and self.new_subcluster):
            raise ValueError("decision 'new' requires new_cluster and new_subcluster")
        return self


class ResolveResult(BaseModel):
    """What the model must return for one batch of later-period sub-clusters."""

    model_config = ConfigDict(extra="ignore")

    mappings: list[ResolveMapping] = Field(min_length=1)
