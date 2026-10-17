"""The record passed to an analysis.

Deliberately dependency-free so both ``data`` and ``prompts`` can import it
without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class InputRecord:
    """One selected workbook row, reduced to the configured analysis fields."""

    record_id: str
    source_row: int
    fields: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def field(self, name: str) -> str:
        return self.fields.get(name, "")
