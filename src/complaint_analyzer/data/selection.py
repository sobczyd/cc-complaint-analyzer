"""Choosing which rows to analyze, and reducing them to analysis input.

Filtering is deliberately boring: every configured filter must match (AND), the
limit is applied afterwards in workbook order, and the result carries only the
fields the configuration asked to send to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..records import InputRecord
from ..settings import DatasetSettings, FilterSpec
from .workbook import DataError, RawRow, Workbook, cell_text


@dataclass(frozen=True)
class SkippedRow:
    """A row that was dropped for a reason worth reporting."""

    source_row: int
    reason: str


@dataclass(frozen=True)
class Selection:
    """The outcome of applying filters and the limit to a workbook.

    ``matched_rows`` counts every row that passed the filters, whether or not it
    was analyzed, so the manifest can report how much data the filters selected.
    ``skipped`` only reports rows that were genuine candidates: once the limit is
    satisfied the remaining rows were never going to be analyzed, so dropping one
    for a blank or duplicate identifier is not worth warning about.
    """

    records: tuple[InputRecord, ...]
    rows_by_id: dict[str, RawRow]
    total_rows: int
    matched_rows: int
    skipped: tuple[SkippedRow, ...]

    @property
    def limited(self) -> bool:
        return len(self.records) < self.matched_rows


def _normalize(value: Any) -> str:
    return cell_text(value).strip().casefold()


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = cell_text(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _compare(cell: str, expected: Any) -> int | None:
    """Order a cell against an expected value, numerically when both look numeric."""
    left_number = _as_number(cell)
    right_number = _as_number(expected)
    if left_number is not None and right_number is not None:
        if left_number < right_number:
            return -1
        return 0 if left_number == right_number else 1

    left, right = _normalize(cell), _normalize(expected)
    if not left or not right:
        return None
    if left < right:
        return -1
    return 0 if left == right else 1


def _ordered(operator: str) -> Callable[[str, Any], bool]:
    allowed = {"gt": (1,), "gte": (0, 1), "lt": (-1,), "lte": (-1, 0)}[operator]

    def check(cell: str, expected: Any) -> bool:
        result = _compare(cell, expected)
        return result is not None and result in allowed

    return check


_PREDICATES: dict[str, Callable[[str, Any], bool]] = {
    "eq": lambda cell, expected: _normalize(cell) == _normalize(expected),
    "ne": lambda cell, expected: _normalize(cell) != _normalize(expected),
    "in": lambda cell, expected: _normalize(cell) in {_normalize(item) for item in expected},
    "contains": lambda cell, expected: _normalize(expected) in _normalize(cell),
    "is_blank": lambda cell, _expected: not cell.strip(),
    "not_blank": lambda cell, _expected: bool(cell.strip()),
    "gt": _ordered("gt"),
    "gte": _ordered("gte"),
    "lt": _ordered("lt"),
    "lte": _ordered("lte"),
}


def matches(row: RawRow, spec: FilterSpec) -> bool:
    """Evaluate one filter against one row."""
    try:
        predicate = _PREDICATES[spec.operator]
    except KeyError:  # pragma: no cover - settings validation prevents this
        raise DataError(f"unsupported filter operator: {spec.operator}") from None
    return predicate(row.value(spec.field), spec.value)


def select(workbook: Workbook, dataset: DatasetSettings, *, limit: int | None = None) -> Selection:
    """Apply filters and the limit, returning records ready for an analysis."""
    required: list[str] = [dataset.id_field, *dataset.fields]
    required.extend(spec.field for spec in dataset.filters)
    workbook.require_columns(_unique(required))

    effective_limit = dataset.limit if limit is None else limit

    records: list[InputRecord] = []
    rows_by_id: dict[str, RawRow] = {}
    skipped: list[SkippedRow] = []
    matched = 0

    for row in workbook:
        if not all(matches(row, spec) for spec in dataset.filters):
            continue
        matched += 1

        if effective_limit is not None and len(records) >= effective_limit:
            continue

        record_id = row.value(dataset.id_field).strip()
        if not record_id:
            skipped.append(
                SkippedRow(source_row=row.source_row, reason=f"blank '{dataset.id_field}'")
            )
            continue
        if record_id in rows_by_id:
            skipped.append(
                SkippedRow(
                    source_row=row.source_row,
                    reason=f"duplicate '{dataset.id_field}' value {record_id!r}",
                )
            )
            continue

        rows_by_id[record_id] = row
        records.append(
            InputRecord(
                record_id=record_id,
                source_row=row.source_row,
                fields={name: row.value(name) for name in dataset.fields},
            )
        )

    return Selection(
        records=tuple(records),
        rows_by_id=rows_by_id,
        total_rows=len(workbook),
        matched_rows=matched,
        skipped=tuple(skipped),
    )


def _unique(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered
