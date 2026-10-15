"""The single owner of every run and call output path.

No other module builds output paths. Changing the on-disk layout is one edit here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

MANIFEST_NAME = "manifest.json"
RUN_LOG_NAME = "run.log"
RESULTS_NAME = "results.jsonl"
OUTPUT_WORKBOOK_NAME = "analyzed.xlsx"
CALLS_DIR_NAME = "calls"
EXCHANGE_DIR_NAME = "exchange"
EXCHANGE_REQUESTS_DIR_NAME = "requests"
EXCHANGE_RESPONSES_DIR_NAME = "responses"
EXCHANGE_MANIFEST_NAME = "manifest.json"
EXCHANGE_ASSIGNMENTS_NAME = "assignments.json"

REQUEST_NAME = "request.json"
RESPONSE_NAME = "response.json"
METADATA_NAME = "metadata.json"
PROCESS_LOG_NAME = "process.log"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(moment: datetime) -> str:
    """Sortable UTC stamp, for example ``20261015T173200123456Z``."""
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"


def safe_component(value: str) -> str:
    cleaned = _UNSAFE.sub("-", value.strip()).strip("-")
    return cleaned or "unnamed"


def default_run_id(moment: datetime | None = None) -> str:
    return "run_" + timestamp(moment or utc_now())


@dataclass(frozen=True)
class RunPaths:
    """Resolved locations for one run."""

    run_dir: Path

    @classmethod
    def create(cls, runs_dir: Path, run_id: str) -> "RunPaths":
        paths = cls(run_dir=runs_dir / safe_component(run_id))
        paths.run_dir.mkdir(parents=True, exist_ok=True)
        return paths

    @classmethod
    def create_new(cls, runs_dir: Path, run_id: str) -> "RunPaths":
        paths = cls(run_dir=runs_dir / safe_component(run_id))
        paths.run_dir.mkdir(parents=True, exist_ok=False)
        return paths

    @classmethod
    def open_existing(cls, runs_dir: Path, run_id: str) -> "RunPaths":
        paths = cls(run_dir=runs_dir / safe_component(run_id))
        if not paths.run_dir.is_dir():
            raise FileNotFoundError(paths.run_dir)
        return paths

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / MANIFEST_NAME

    @property
    def run_log_path(self) -> Path:
        return self.run_dir / RUN_LOG_NAME

    @property
    def results_path(self) -> Path:
        return self.run_dir / RESULTS_NAME

    @property
    def output_workbook_path(self) -> Path:
        return self.run_dir / OUTPUT_WORKBOOK_NAME

    @property
    def calls_dir(self) -> Path:
        return self.run_dir / CALLS_DIR_NAME

    @property
    def exchange_dir(self) -> Path:
        return self.run_dir / EXCHANGE_DIR_NAME

    @property
    def exchange_requests_dir(self) -> Path:
        return self.exchange_dir / EXCHANGE_REQUESTS_DIR_NAME

    @property
    def exchange_responses_dir(self) -> Path:
        return self.exchange_dir / EXCHANGE_RESPONSES_DIR_NAME

    @property
    def exchange_manifest_path(self) -> Path:
        return self.exchange_dir / EXCHANGE_MANIFEST_NAME

    @property
    def exchange_assignments_path(self) -> Path:
        return self.exchange_dir / EXCHANGE_ASSIGNMENTS_NAME

    def call_dir(self, analysis_key: str, call_id: str, started: datetime) -> Path:
        """``calls/<analysis-version>/<utc-timestamp>_<call-id>/``, created on demand."""
        directory = (
            self.calls_dir
            / safe_component(analysis_key)
            / f"{timestamp(started)}_{safe_component(call_id)}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        return directory
