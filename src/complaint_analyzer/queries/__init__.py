"""Reloadable Salesforce (or other) query text, organized like analysis prompts.

Each subdirectory under ``queries/`` is a named query set holding ``<version>.txt``
files. Load one with ``load_queries(directory)``:

    from pathlib import Path
    from complaint_analyzer.queries import load_queries

    _DIR = Path(__file__).parent / "cq_crm_codes_nurse_call_no_comments"
    versions = load_queries(_DIR)
    query_v2 = versions["v2"]
"""

from __future__ import annotations

from .base import QueryError, load_queries

__all__ = ["QueryError", "load_queries"]
