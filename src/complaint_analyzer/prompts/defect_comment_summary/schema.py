"""JSON contract for summarizing a Jira issue's comment thread."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentSummary(BaseModel):
    """What the model must return for one defect or RCA."""

    model_config = ConfigDict(extra="ignore")

    summary: str
    key_points: list[str] = Field(default_factory=list)
    root_cause: str = ""
    fix_or_workaround: str = ""

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value.strip()

    @field_validator("key_points", mode="before")
    @classmethod
    def _points(cls, value: object) -> object:
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else value
