"""JSON contract for mapping a batch of complaints to existing defects or RCAs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONFIDENCE = ("high", "medium", "low")
MATCH_TYPES = ("defect", "rca", "none")


class IssueMatch(BaseModel):
    """One defect or RCA that would likely have addressed the complaint."""

    model_config = ConfigDict(extra="ignore")

    issue_key: str
    issue_type: str
    confidence: str
    rationale: str
    version_justification: str = ""
    kb_support: list[str] = Field(default_factory=list)

    @field_validator("issue_key")
    @classmethod
    def _key(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("issue_key must not be blank")
        return value

    @field_validator("issue_type")
    @classmethod
    def _type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("defect", "rca"):
            raise ValueError("issue_type must be 'defect' or 'rca'")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {', '.join(CONFIDENCE)}")
        return value

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must not be blank")
        return value.strip()

    @field_validator("kb_support", mode="before")
    @classmethod
    def _articles(cls, value: object) -> object:
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else value


class CaseMapping(BaseModel):
    """The verdict for one complaint."""

    model_config = ConfigDict(extra="ignore")

    case_number: str
    match_type: str
    rationale: str = ""
    matches: list[IssueMatch] = Field(default_factory=list)

    @field_validator("case_number", mode="before")
    @classmethod
    def _number(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("match_type")
    @classmethod
    def _match_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in MATCH_TYPES:
            raise ValueError(f"match_type must be one of {', '.join(MATCH_TYPES)}")
        return value


class MappingResult(BaseModel):
    """What the model must return for one batch of complaints."""

    model_config = ConfigDict(extra="ignore")

    cases: list[CaseMapping] = Field(min_length=1)
