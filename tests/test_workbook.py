"""Workbook reading and row selection."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook as OpenpyxlWorkbook

from complaint_analyzer.workbook import DataError, load_sheet, select
from complaint_analyzer.workbook.workbook import cell_text
from complaint_analyzer.core.settings import DatasetSettings, FilterSpec

from conftest import SHEET, make_settings


def test_load_sheet_reads_headers_and_rows(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    assert book.columns[0] == "Record ID"
    assert "Resolution" in book.columns
    # Six data rows; none are fully blank.
    assert len(book) == 6
    assert book.rows[0].source_row == 2
    assert book.rows[0].value("Record ID") == "R-001"


def test_load_sheet_rejects_missing_sheet(workbook_path: Path) -> None:
    with pytest.raises(DataError, match="not found"):
        load_sheet(workbook_path, "No Such Sheet")


def test_load_sheet_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="not found"):
        load_sheet(tmp_path / "absent.xlsx", SHEET)


def test_load_sheet_rejects_duplicate_headers(tmp_path: Path) -> None:
    path = tmp_path / "dupe.xlsx"
    book = OpenpyxlWorkbook()
    book.active.title = SHEET
    book.active.append(["Record ID", "Status", "Status"])
    book.save(path)
    book.close()
    with pytest.raises(DataError, match="duplicate column header"):
        load_sheet(path, SHEET)


def test_require_columns_names_what_is_missing(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    with pytest.raises(DataError, match="Nonexistent"):
        book.require_columns(["Record ID", "Nonexistent"])


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ""),
        (True, "yes"),
        (False, "no"),
        (3.0, "3"),
        (3.5, "3.5"),
        ("  padded  ", "padded"),
    ],
)
def test_cell_text(value: object, expected: str) -> None:
    assert cell_text(value) == expected


def _dataset(**overrides) -> DatasetSettings:
    raw = {
        "path": "unused.xlsx",
        "sheet": SHEET,
        "id_field": "Record ID",
        "fields": ["Service description"],
        "filters": [],
        "limit": None,
    }
    raw.update(overrides)
    return DatasetSettings.model_validate(raw)


def test_select_applies_filters_and_reports_skips(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(filters=[{"field": "Status", "operator": "eq", "value": "Closed"}])
    result = select(book, dataset)

    assert [record.record_id for record in result.records] == ["R-001", "R-002", "R-004"]
    assert result.total_rows == 6
    assert result.matched_rows == 5  # Includes the blank-id and duplicate-id rows.
    reasons = {item.reason for item in result.skipped}
    assert any("blank" in reason for reason in reasons)
    assert any("duplicate" in reason for reason in reasons)


def test_select_projects_only_configured_fields(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(fields=["Service description", "Resolution"])
    record = select(book, dataset).records[0]
    assert set(record.fields) == {"Service description", "Resolution"}
    assert record.field("Troubleshooting") == ""


def test_select_limit_applies_after_filtering(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(
        filters=[{"field": "Status", "operator": "eq", "value": "Closed"}],
        limit=2,
    )
    result = select(book, dataset)
    assert [record.record_id for record in result.records] == ["R-001", "R-002"]
    assert result.matched_rows == 5
    assert result.limited is True


def test_select_limit_override_wins(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(limit=1)
    assert len(select(book, dataset, limit=3).records) == 3


def test_select_rejects_filter_on_unknown_column(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(filters=[{"field": "Nope", "operator": "eq", "value": "x"}])
    with pytest.raises(DataError, match="Nope"):
        select(book, dataset)


@pytest.mark.parametrize(
    "spec,expected_ids",
    [
        ({"field": "Status", "operator": "eq", "value": "closed"}, ["R-001", "R-002", "R-004"]),
        ({"field": "Status", "operator": "ne", "value": "Closed"}, ["R-003"]),
        ({"field": "Status", "operator": "in", "value": ["Open", "Pending"]}, ["R-003"]),
        ({"field": "Resolution", "operator": "contains", "value": "reboot"}, ["R-002"]),
        ({"field": "Troubleshooting", "operator": "is_blank"}, ["R-003"]),
        (
            {"field": "Troubleshooting", "operator": "not_blank"},
            ["R-001", "R-002", "R-004"],
        ),
        ({"field": "Priority", "operator": "gt", "value": 3}, ["R-004"]),
        ({"field": "Priority", "operator": "gte", "value": 3}, ["R-001", "R-004"]),
        ({"field": "Priority", "operator": "lt", "value": 2}, ["R-002"]),
        ({"field": "Priority", "operator": "lte", "value": 2}, ["R-002", "R-003"]),
    ],
)
def test_every_operator(workbook_path: Path, spec: dict, expected_ids: list[str]) -> None:
    book = load_sheet(workbook_path, SHEET)
    result = select(book, _dataset(filters=[spec]))
    assert [record.record_id for record in result.records] == expected_ids


def test_filters_combine_with_and(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(
        filters=[
            {"field": "Status", "operator": "eq", "value": "Closed"},
            {"field": "Priority", "operator": "gte", "value": 3},
        ]
    )
    assert [record.record_id for record in select(book, dataset).records] == ["R-001", "R-004"]


def test_ordered_comparison_on_blank_cell_is_false(workbook_path: Path) -> None:
    book = load_sheet(workbook_path, SHEET)
    dataset = _dataset(filters=[{"field": "Troubleshooting", "operator": "gt", "value": "a"}])
    ids = [record.record_id for record in select(book, dataset).records]
    assert "R-003" not in ids


def test_make_settings_helper_round_trips(workbook_path: Path, tmp_path: Path) -> None:
    settings = make_settings(workbook_path, tmp_path / "runs", analysis={"concurrency": 4})
    assert settings.analysis.concurrency == 4
    assert settings.analysis.key == "rca-v1"
    assert isinstance(settings.dataset.filters[0], FilterSpec)
