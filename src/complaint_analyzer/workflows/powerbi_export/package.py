"""Power BI data-model package: one Excel file per table, written to ``<run>\\powerbi_export_package``."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from .export import DEFAULT_TEMPLATE, PowerBIExportError, export_powerbi, read_sheet

PACKAGE_DIR = "powerbi_export_package"
KEY = "Source Identifier Raw"
DIM_ID_COLUMNS = [KEY, "Source Identifier", "PR ID", "Trackwise_Status"]
DIM_CLUSTER_COLUMNS = [
    "Case Number", "Period", "Resolved cluster", "Resolved subcluster", "Mapping status", "Mapping confidence",
]
DIM_DEFECT_COLUMNS = [
    "Case Number", "issue_key", "issue_type", "confidence", "rationale", "version_justification", "kb_support",
]

README = """# Power BI export package

Generated {generated} from `{run}`. Each Excel file is one table; point Power BI at this folder and refresh.

| File | Table | Key |
|---|---|---|
| FactSource.xlsx (Sheet1) | FactSource | `Source Identifier Raw` |
| DimID.xlsx (DimID) | DimID | `Source Identifier Raw` |
| DimCluster.xlsx (DimCluster) | DimCluster | `Case Number` |
| DimDefect.xlsx (DimDefect) | DimDefect | `Case Number` (many rows per case) |

## Relationships (single direction, filtering from the dimension to FactSource)
- FactSource[Source Identifier Raw] 1 : 1 DimID[Source Identifier Raw]
- FactSource[Source Identifier Raw] 1 : 1 DimCluster[Case Number]
- FactSource[Source Identifier Raw] 1 : * DimDefect[Case Number]

All keys are text (leading zeros kept). A case can match several defects, so use a distinct count of cases
when slicing by defect.

## Notes
- TODO: DimID is built from FactSource only (`Source Identifier`, `PR ID`). The Trackwise export is not
  available yet; add its columns to DimID when it is (`Trackwise_Status` is a blank placeholder).
- DimDefect holds real defect matches only; cases with no defect have no rows.
- `package_manifest.json` lists the sources, row counts and coverage gaps.
"""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, sheet_name: str, headers: list[str], rows: list[list[Any]]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"
    book.save(path)


def _latest(directory: Path, filename: str, name: str | None, what: str) -> Path | None:
    """Pick ``directory\\<name>\\filename``; without a name use the newest one."""
    if name:
        path = directory / name / filename
        if not path.is_file():
            raise PowerBIExportError(f"{what} file not found: {path}")
        return path
    found = sorted(directory.glob(f"*/{filename}"), key=lambda item: item.stat().st_mtime) if directory.is_dir() else []
    return found[-1] if found else None


def _comparison_path(value: Path) -> Path:
    path = value / "comparison.xlsx" if value.is_dir() else value
    if not path.is_file():
        raise PowerBIExportError(f"comparison workbook not found: {path}")
    return path


def read_cluster_rows(comparison: Path | None, assignments: Path | None) -> tuple[list[dict[str, Any]], str]:
    if comparison is not None:
        book = load_workbook(comparison, read_only=True, data_only=True)
        try:
            if "Case Assignments" not in book.sheetnames:
                raise PowerBIExportError(f"no 'Case Assignments' sheet in {comparison}")
            rows = list(book["Case Assignments"].iter_rows(values_only=True))
        finally:
            book.close()
        header = [_text(cell) for cell in rows[0]]
        out = []
        for values in rows[1:]:
            record = dict(zip(header, values))
            if not _text(record.get("CaseNumber")):
                continue
            out.append(
                {
                    "Case Number": _text(record["CaseNumber"]),
                    "Period": _text(record.get("Period")),
                    "Resolved cluster": _text(record.get("Resolved cluster")),
                    "Resolved subcluster": _text(record.get("Resolved subcluster")),
                    "Mapping status": _text(record.get("Mapping status")),
                    "Mapping confidence": record.get("Mapping confidence"),
                }
            )
        return out, "comparison"
    if assignments is not None:
        out = []
        for line in assignments.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            out.append(
                {
                    "Case Number": _text(record["case_number"]),
                    "Period": "",
                    "Resolved cluster": _text(record.get("final_cluster")),
                    "Resolved subcluster": _text(record.get("final_subcluster")),
                    "Mapping status": "baseline",
                    "Mapping confidence": None,
                }
            )
        return out, "case_assignments"
    return [], "none"


def read_defect_rows(mappings: Path | None) -> list[dict[str, Any]]:
    if mappings is None:
        return []
    book = load_workbook(mappings, read_only=True, data_only=True)
    try:
        if "Mappings" not in book.sheetnames:
            raise PowerBIExportError(f"no 'Mappings' sheet in {mappings}")
        rows = list(book["Mappings"].iter_rows(values_only=True))
    finally:
        book.close()
    header = [_text(cell) for cell in rows[0]]
    out = []
    for values in rows[1:]:
        record = dict(zip(header, values))
        if not _text(record.get("case_number")) or not _text(record.get("issue_key")):
            continue
        row = {column: record.get(column) for column in DIM_DEFECT_COLUMNS[1:]}
        row["Case Number"] = _text(record["case_number"])
        out.append(row)
    return out


def build_package(
    run_dir: Path,
    *,
    comparison: Path | None = None,
    clusters: str | None = None,
    defects: str | None = None,
    out_dir: Path | None = None,
    template: Path = DEFAULT_TEMPLATE,
    kb_dir: Path | None = None,
) -> dict[str, Any]:
    cases = run_dir / "cases.xlsx"
    if not cases.is_file():
        raise PowerBIExportError(f"cases.xlsx not found in {run_dir}")
    out_dir = out_dir or run_dir / PACKAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    comparison_file = _comparison_path(comparison) if comparison else None
    assignments = None if comparison_file else _latest(run_dir / "clusters", "case_assignments.jsonl", clusters, "clusters")
    mappings = _latest(run_dir / "defects", "mappings.xlsx", defects, "defects")
    if comparison_file is None and assignments is None:
        warnings.append("no cluster source (comparison.xlsx or clusters\\<name>\\case_assignments.jsonl): DimCluster is empty")
    if mappings is None:
        warnings.append("no defects\\<name>\\mappings.xlsx: DimDefect is empty")

    fact_path = out_dir / "FactSource.xlsx"
    stats = export_powerbi(cases, fact_path, template=template, kb_dir=kb_dir)
    fact_rows = read_sheet(fact_path, "Sheet1")
    keys = [_text(row.get(KEY)) for row in fact_rows]
    key_set = set(keys)
    if len(key_set) != len(keys):
        warnings.append(f"FactSource has {len(keys) - len(key_set)} duplicate {KEY} value(s)")

    dim_id = [[key, _text(row.get("Source Identifier")), row.get("PR ID"), ""] for key, row in zip(keys, fact_rows)]
    _write(out_dir / "DimID.xlsx", "DimID", DIM_ID_COLUMNS, dim_id)

    cluster_rows, cluster_source = read_cluster_rows(comparison_file, assignments)
    chosen: dict[str, dict[str, Any]] = {}
    for row in cluster_rows:
        if row["Case Number"] in key_set:
            chosen[row["Case Number"]] = row
    orphan_clusters = len({row["Case Number"] for row in cluster_rows}) - len(chosen)
    _write(
        out_dir / "DimCluster.xlsx", "DimCluster", DIM_CLUSTER_COLUMNS,
        [[row[column] for column in DIM_CLUSTER_COLUMNS] for row in chosen.values()],
    )

    all_defects = read_defect_rows(mappings)
    defect_rows = [row for row in all_defects if row["Case Number"] in key_set]
    _write(
        out_dir / "DimDefect.xlsx", "DimDefect", DIM_DEFECT_COLUMNS,
        [[row[column] for column in DIM_DEFECT_COLUMNS] for row in defect_rows],
    )

    missing_cluster = [key for key in key_set if key not in chosen] if cluster_source != "none" else []
    if missing_cluster:
        warnings.append(f"{len(missing_cluster)} FactSource case(s) have no cluster")
    (out_dir / "README.md").write_text(
        README.format(generated=datetime.now().strftime("%Y-%m-%d %H:%M"), run=run_dir.name), encoding="utf-8"
    )
    sources = {"cases": cases, "comparison": comparison_file, "case_assignments": assignments, "mappings": mappings}
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "cluster_source": cluster_source,
        "sources": {
            name: {"path": str(path), "sha256": _sha256(path)} for name, path in sources.items() if path is not None
        },
        "rows": {
            "FactSource": len(fact_rows),
            "DimID": len(dim_id),
            "DimCluster": len(chosen),
            "DimDefect": len(defect_rows),
        },
        "coverage": {
            "cases_without_cluster": len(missing_cluster),
            "cases_with_defect": len({row["Case Number"] for row in defect_rows}),
            "cases_without_defect": len(key_set - {row["Case Number"] for row in defect_rows}),
            "orphan_cluster_cases_dropped": orphan_clusters,
            "orphan_defect_rows_dropped": len(all_defects) - len(defect_rows),
        },
        "warnings": warnings,
    }
    (out_dir / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**manifest, "out_dir": str(out_dir), "export": stats}
