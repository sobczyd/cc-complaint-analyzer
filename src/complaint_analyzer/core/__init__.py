"""Shared engine: settings, run-record selection, run paths, run/call logging,
versioning, and the row-by-row analysis runner.

Nothing in this package knows about workbooks, the LLM client stack, prompt or
query content, or any particular workflow. Everything else in
``complaint_analyzer`` depends on ``core``; ``core`` depends on nothing else in
the project.
"""

from __future__ import annotations
