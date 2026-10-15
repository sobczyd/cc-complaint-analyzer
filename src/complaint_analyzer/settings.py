"""Configuration: YAML file for repeatable settings, environment for credentials."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

OPERATORS = (
    "eq",
    "ne",
    "in",
    "contains",
    "is_blank",
    "not_blank",
    "gt",
    "gte",
    "lt",
    "lte",
)

VALUELESS_OPERATORS = frozenset({"is_blank", "not_blank"})
SEQUENCE_OPERATORS = frozenset({"in"})


class ConfigError(Exception):
    """Raised when configuration or credentials are unusable."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterSpec(_Strict):
    field: str
    operator: Literal[OPERATORS]  # type: ignore[valid-type]
    value: Any = None

    @model_validator(mode="after")
    def _check_value(self) -> "FilterSpec":
        if self.operator in VALUELESS_OPERATORS:
            if self.value is not None:
                raise ValueError(f"operator '{self.operator}' takes no value")
        elif self.operator in SEQUENCE_OPERATORS:
            if not isinstance(self.value, (list, tuple)) or not self.value:
                raise ValueError(f"operator '{self.operator}' needs a non-empty list value")
        elif self.value is None:
            raise ValueError(f"operator '{self.operator}' needs a value")
        return self


class DatasetSettings(_Strict):
    path: Path
    sheet: str
    id_field: str
    fields: list[str] = Field(min_length=1)
    filters: list[FilterSpec] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)

    @field_validator("fields")
    @classmethod
    def _unique_fields(cls, value: list[str]) -> list[str]:
        seen = {name.strip() for name in value}
        if len(seen) != len(value):
            raise ValueError("duplicate entries in dataset.fields")
        if "" in seen:
            raise ValueError("dataset.fields contains an empty name")
        return [name.strip() for name in value]


class AnalysisSettings(_Strict):
    name: str = "rca"
    version: str = "v1"
    concurrency: int = Field(default=3, ge=1, le=32)
    max_output_tokens: int = Field(default=800, ge=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    @property
    def key(self) -> str:
        """Identifier used for call directories and metadata."""
        return f"{self.name}-{self.version}"


class RateLimitSettings(_Strict):
    rpm: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    max_attempts: int = Field(default=4, ge=1, le=10)


class CacheSettings(_Strict):
    mode: Literal["off", "reuse"] = "off"

    @field_validator("mode", mode="before")
    @classmethod
    def _unquoted_off(cls, value: Any) -> Any:
        # Unquoted `off` in YAML parses as the boolean False.
        if value is False:
            return "off"
        return value


class OutputSettings(_Strict):
    runs_dir: Path = Path("data/runs")


class Settings(_Strict):
    dataset: DatasetSettings
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)


class Credentials(BaseModel):
    """Endpoint credentials. ``api_key`` is a SecretStr so it stays out of repr and logs."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_key: SecretStr
    model: str


def load_settings(path: Path) -> Settings:
    """Read and validate a YAML config file."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {path}\n{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must contain a mapping: {path}")
    try:
        return Settings.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc


def load_credentials(env_file: Path | None = None) -> Credentials:
    """Read endpoint credentials from the environment (and a local .env if present)."""
    if env_file is None:
        env_file = Path(".env")
    if env_file.is_file():
        load_dotenv(env_file, override=False)

    values = {name: (os.getenv(name) or "").strip() for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")}
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise ConfigError(
            "missing required environment variables: " + ", ".join(missing) + ". "
            "Copy .env.example to .env and fill it in."
        )
    return Credentials(
        base_url=values["LLM_BASE_URL"],
        api_key=SecretStr(values["LLM_API_KEY"]),
        model=values["LLM_MODEL"],
    )
