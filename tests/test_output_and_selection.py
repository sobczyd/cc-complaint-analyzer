"""Regression tests for workbook writing and for what selection reports as skipped."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, Iterator

import pytest
from openpyxl import Workbook as OpenpyxlWorkbook
from openpyxl import load_workbook

from complaint_analyzer.data import load_sheet, select
from complaint_analyzer.data.workbook import RawRow
from complaint_analyzer.data.writer import MAX_CELL_LENGTH, OutputRow, write_workbook
from complaint_analyzer.settings import DatasetSettings

from conftest import SHEET

SOURCE_COLUMNS = ("Record ID", "Resolution")
RESULT_COLUMNS = ("symptom", "hypothesis")


def _write(
    path: Path,
    *,
    resolution: str = "",
    symptom: str = "",
    hypothesis: str = "",
    status: str = "ok",
    issues: tuple[str, ...] = (),
    error: str = "",
) -> int:
    row = OutputRow(
        record_id="R-001",
        source_row=2,
        status=status,
        values={"symptom": symptom, "hypothesis": hypothesis},
        issues=issues,
        error=error,
    )
    return write_workbook(
        path,
        source_columns=SOURCE_COLUMNS,
        result_columns=RESULT_COLUMNS,
        rows=[row],
        rows_by_id={
            "R-001": RawRow(source_row=2, values={"Record ID": "R-001", "Resolution": resolution})
        },
    )


def _cells(path: Path) -> dict[str, Any]:
    """Map every header to the (value, data_type) of the single data row."""
    book = load_workbook(path, data_only=True)
    try:
        sheet = book[book.sheetnames[0]]
        header = [cell.value for cell in sheet[1]]
        return {name: sheet.cell(row=2, column=index + 1) for index, name in enumerate(header)}
    finally:
        book.close()


# --- bug 1: values starting with '=' must stay text -----------------------------


def test_source_value_starting_with_equals_is_written_as_text(tmp_path: Path) -> None:
    original = "=1+1 see attached"
    _write(tmp_path / "analyzed.xlsx", resolution=original)

    cell = _cells(tmp_path / "analyzed.xlsx")["Resolution"]
    assert cell.data_type != "f"
    assert cell.value == original


def test_result_value_starting_with_equals_is_written_as_text(tmp_path: Path) -> None:
    original = "=SUM(A1:A9) was the formula in the log"
    _write(tmp_path / "analyzed.xlsx", symptom=original)

    cell = _cells(tmp_path / "analyzed.xlsx")["symptom"]
    assert cell.data_type != "f"
    assert cell.value == original


@pytest.mark.parametrize(
    "text",
    ["=> replaced the uplink cable", "=== NOTE ===", "=A1", "#REF!", "+1-555-0100", "@here"],
)
def test_formula_like_text_round_trips_unchanged(tmp_path: Path, text: str) -> None:
    path = tmp_path / "analyzed.xlsx"
    _write(path, resolution=text, hypothesis=text, error=text)

    cells = _cells(path)
    for name in ("Resolution", "hypothesis", "analysis_error"):
        assert cells[name].data_type == "s"
        assert cells[name].value == text


def test_sanitizing_and_clipping_still_apply(tmp_path: Path) -> None:
    path = tmp_path / "analyzed.xlsx"
    _write(path, resolution="line\x07one\nline two", symptom="=" + "x" * (MAX_CELL_LENGTH * 2))

    cells = _cells(path)
    assert cells["Resolution"].value == "lineone\nline two"
    symptom = cells["symptom"].value
    assert len(symptom) == MAX_CELL_LENGTH
    assert symptom.startswith("=xxx")
    assert symptom.endswith("\u2026")


def test_header_keeps_its_formatting(tmp_path: Path) -> None:
    path = tmp_path / "analyzed.xlsx"
    _write(path)

    book = load_workbook(path)
    try:
        header = book[book.sheetnames[0]][1]
        assert [cell.value for cell in header] == [
            *SOURCE_COLUMNS,
            *RESULT_COLUMNS,
            "analysis_status",
            "analysis_issues",
            "analysis_error",
        ]
        assert all(cell.font.bold for cell in header)
        assert all(cell.alignment.wrap_text for cell in header)
        assert all(cell.alignment.vertical == "top" for cell in header)
    finally:
        book.close()


def test_rows_are_written_with_their_status_block(tmp_path: Path) -> None:
    path = tmp_path / "analyzed.xlsx"
    written = _write(path, status="flagged", issues=("first", "second"), error="boom")

    assert written == 1
    cells = _cells(path)
    assert cells["analysis_status"].value == "flagged"
    assert cells["analysis_issues"].value == "first\nsecond"
    assert cells["analysis_error"].value == "boom"


# --- bug 2: the workbook is closed even when writing fails ----------------------

# Closing a half-written write-only workbook leaves openpyxl's row writer suspended
# on a closed stream; collecting it here keeps the noise out of unrelated tests.
_unraisable = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


@_unraisable
def test_workbook_is_closed_when_row_generation_fails(tmp_path: Path, monkeypatch) -> None:
    closed: list[bool] = []

    class TrackingWorkbook(OpenpyxlWorkbook):
        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr("complaint_analyzer.data.writer.OpenpyxlWorkbook", TrackingWorkbook)

    def exploding_rows() -> Iterator[OutputRow]:
        raise RuntimeError("row generation failed")
        yield  # pragma: no cover - unreachable, makes this a generator

    with pytest.raises(RuntimeError, match="row generation failed"):
        write_workbook(
            tmp_path / "analyzed.xlsx",
            source_columns=SOURCE_COLUMNS,
            result_columns=RESULT_COLUMNS,
            rows=exploding_rows(),
            rows_by_id={},
        )

    assert closed == [True]
    gc.collect()


@_unraisable
def test_workbook_is_closed_when_saving_fails(tmp_path: Path, monkeypatch) -> None:
    closed: list[bool] = []

    class TrackingWorkbook(OpenpyxlWorkbook):
        def save(self, filename) -> None:
            raise OSError("disk full")

        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr("complaint_analyzer.data.writer.OpenpyxlWorkbook", TrackingWorkbook)

    with pytest.raises(OSError, match="disk full"):
        _write(tmp_path / "analyzed.xlsx")

    assert closed == [True]
    gc.collect()


# --- bug 3: rows past the limit were never candidates ---------------------------


def _noisy_workbook(path: Path, *, blanks: int = 50) -> Path:
    book = OpenpyxlWorkbook()
    sheet = book.active
    sheet.title = SHEET
    sheet.append(["Record ID", "Status", "Service description"])
    sheet.append(["R-001", "Closed", "First real row."])
    sheet.append(["R-002", "Closed", "Second real row."])
    for index in range(blanks):
        sheet.append(["", "Closed", f"Row with no identifier {index}."])
    sheet.append(["R-001", "Closed", "Duplicate identifier row."])
    book.save(path)
    book.close()
    return path


def _dataset(**overrides: Any) -> DatasetSettings:
    raw: dict[str, Any] = {
        "path": "unused.xlsx",
        "sheet": SHEET,
        "id_field": "Record ID",
        "fields": ["Service description"],
        "filters": [],
        "limit": None,
    }
    raw.update(overrides)
    return DatasetSettings.model_validate(raw)


def test_rows_past_the_limit_are_not_reported_as_skipped(tmp_path: Path) -> None:
    book = load_sheet(_noisy_workbook(tmp_path / "noisy.xlsx"), SHEET)
    result = select(book, _dataset(), limit=2)

    assert [record.record_id for record in result.records] == ["R-001", "R-002"]
    assert result.skipped == ()
    # Every filtered row is still counted, so the manifest reports the real total.
    assert result.matched_rows == 53
    assert result.total_rows == 53
    assert result.limited is True


def test_skips_before_the_limit_are_still_reported(tmp_path: Path) -> None:
    book = load_sheet(_noisy_workbook(tmp_path / "noisy.xlsx", blanks=1), SHEET)
    result = select(book, _dataset(), limit=3)

    assert [record.record_id for record in result.records] == ["R-001", "R-002"]
    reasons = [item.reason for item in result.skipped]
    assert any("blank" in reason for reason in reasons)
    assert any("duplicate" in reason for reason in reasons)
    assert result.matched_rows == 4
    assert result.limited is True


def test_without_a_limit_every_dropped_row_is_reported(tmp_path: Path) -> None:
    book = load_sheet(_noisy_workbook(tmp_path / "noisy.xlsx", blanks=3), SHEET)
    result = select(book, _dataset())

    assert [record.record_id for record in result.records] == ["R-001", "R-002"]
    assert len(result.skipped) == 4
    assert result.matched_rows == 6
