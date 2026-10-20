"""Export Salesforce query sets to Excel with the ``sf`` CLI.

    python -m complaint_analyzer.workflows.salesforce_export export --query-set cq_crm_codes_nurse_call_no_comments --out-dir DIR
"""

from __future__ import annotations

from .export import (
    CASES_WORKBOOK_FILENAME,
    EXPORT_META_FILENAME,
    MAIN_SHEET,
    QUERY_FILENAME,
    RAW_FILENAME,
    ExportError,
    ExportResult,
    FlatExport,
    SelectShape,
    Table,
    export_query_set,
    flatten_records,
    parse_response,
    parse_select,
    resolve_query,
    run_query,
    write_cases_workbook,
    write_table,
)

__all__ = [
    "CASES_WORKBOOK_FILENAME",
    "EXPORT_META_FILENAME",
    "MAIN_SHEET",
    "QUERY_FILENAME",
    "RAW_FILENAME",
    "ExportError",
    "ExportResult",
    "FlatExport",
    "SelectShape",
    "Table",
    "export_query_set",
    "export_soql",
    "flatten_records",
    "parse_response",
    "parse_select",
    "resolve_query",
    "run_query",
    "select_clause",
    "write_cases_workbook",
    "write_table",
]
