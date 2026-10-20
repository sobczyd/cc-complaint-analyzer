"""JSON contracts for batch clustering of case summaries and for the final cluster merge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_LABEL_WORDS = 8


def _check_label(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("label must not be blank")
    if len(value.split()) > MAX_LABEL_WORDS:
        raise ValueError(f"label '{value}' is longer than {MAX_LABEL_WORDS} words")
    return value


class BatchSubcluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subcluster_id: str
    label: str
    description: str = ""
    rationale: str = ""
    case_numbers: list[str] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _check_label(value)

    @field_validator("case_numbers", mode="before")
    @classmethod
    def _stringify(cls, value: object) -> object:
        return [str(item).strip() for item in value] if isinstance(value, list) else value


class BatchCluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cluster_id: str
    label: str
    description: str = ""
    rationale: str = ""
    subclusters: list[BatchSubcluster] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _check_label(value)

    @property
    def case_numbers(self) -> list[str]:
        return [case for sub in self.subclusters for case in sub.case_numbers]


class BatchClusterResult(BaseModel):
    """What the model must return for one batch of cases."""

    model_config = ConfigDict(extra="ignore")

    clusters: list[BatchCluster] = Field(min_length=1)


class FinalSubcluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    description: str = ""
    rationale: str = ""

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _check_label(value)


class FinalCluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    description: str = ""
    rationale: str = ""
    subclusters: list[FinalSubcluster] = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return _check_label(value)


class MergeMapping(BaseModel):
    """Where one batch sub-cluster lands in the final taxonomy."""

    model_config = ConfigDict(extra="ignore")

    batch_id: str
    subcluster_id: str
    final_cluster: str
    final_subcluster: str
    rationale: str = ""


class MergeResult(BaseModel):
    """What the model must return when merging all batch taxonomies."""

    model_config = ConfigDict(extra="ignore")

    final_clusters: list[FinalCluster] = Field(min_length=1)
    mappings: list[MergeMapping] = Field(min_length=1)
