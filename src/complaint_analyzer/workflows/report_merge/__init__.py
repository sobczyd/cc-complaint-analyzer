"""Merge analysis results back into exported Salesforce workbooks."""

from .merge import (
    ERROR_KEY,
    GENERATED_FILL_COLOR,
    LEGEND_SHEET,
    MISSING_STATUS,
    STATUS_KEY,
    MergeError,
    MergeResult,
    merge_analysis_run,
    merge_results,
    read_results,
    read_sheets,
)

__all__ = [
    "ERROR_KEY",
    "GENERATED_FILL_COLOR",
    "LEGEND_SHEET",
    "MISSING_STATUS",
    "STATUS_KEY",
    "MergeError",
    "MergeResult",
    "merge_analysis_run",
    "merge_results",
    "read_results",
    "read_sheets",
]
