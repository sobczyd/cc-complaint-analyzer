"""Running one analysis over a selection of records.

Owns concurrency, per-record error isolation, and the two run artifacts that are not
the output workbook: ``results.jsonl`` and ``manifest.json``. Knows nothing about any
specific analysis, nor about how requests reach the network.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from pydantic import ValidationError

from .analyses.base import Analysis, AnalysisError, flatten_result, parse_json_object
from .data import OutputRow, Selection
from .llm.protocol import ChatClient, ChatMessage, ChatRequest, LlmError
from .logs import RunLog
from .records import InputRecord
from .run_paths import RunPaths, utc_now
from .settings import Settings

STATUS_OK = "ok"
STATUS_FLAGGED = "flagged"
STATUS_FAILED = "failed"


@dataclass
class RecordOutcome:
    """What happened to one record."""

    record_id: str
    source_row: int
    status: str
    values: dict[str, str] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    error: str = ""
    call_id: str | None = None
    source_call_id: str | None = None
    cached: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_seconds: float = 0.0

    def as_json(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_row": self.source_row,
            "status": self.status,
            "values": self.values,
            "issues": self.issues,
            "error": self.error or None,
            "call_id": self.call_id,
            "source_call_id": self.source_call_id,
            "cached": self.cached,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "duration_seconds": round(self.duration_seconds, 3),
        }

    def to_output_row(self) -> OutputRow:
        return OutputRow(
            record_id=self.record_id,
            source_row=self.source_row,
            status=self.status,
            values=self.values,
            issues=tuple(self.issues),
            error=self.error,
        )


@dataclass
class RunReport:
    """The summary a caller needs to report and to choose an exit code."""

    run_id: str
    outcomes: list[RecordOutcome]
    started_at: str
    finished_at: str
    duration_seconds: float
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def succeeded(self) -> int:
        return sum(1 for item in self.outcomes if item.status == STATUS_OK)

    @property
    def flagged(self) -> int:
        return sum(1 for item in self.outcomes if item.status == STATUS_FLAGGED)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.outcomes if item.status == STATUS_FAILED)

    @property
    def prompt_tokens(self) -> int:
        """Prompt tokens this run actually paid for; cache hits reused earlier ones."""
        return sum(item.prompt_tokens or 0 for item in self.outcomes if not item.cached)

    @property
    def completion_tokens(self) -> int:
        return sum(item.completion_tokens or 0 for item in self.outcomes if not item.cached)

    @property
    def reused_prompt_tokens(self) -> int:
        """Prompt tokens carried over from the original call behind each cache hit."""
        return sum(item.prompt_tokens or 0 for item in self.outcomes if item.cached)

    @property
    def reused_completion_tokens(self) -> int:
        return sum(item.completion_tokens or 0 for item in self.outcomes if item.cached)


def build_request(
    record: InputRecord,
    *,
    analysis: Analysis,
    settings: Settings,
    model: str,
) -> ChatRequest:
    """Turn one record into one outbound request."""
    version = settings.analysis.version
    body = "\n\n".join(
        [
            analysis.prompt(version),
            "SERVICE RECORD",
            analysis.render_message(record, settings.dataset.fields),
        ]
    )
    return ChatRequest(
        model=model,
        messages=(
            ChatMessage(role="system", content=analysis.system_prompt),
            ChatMessage(role="user", content=body),
        ),
        max_output_tokens=settings.analysis.max_output_tokens,
        temperature=settings.analysis.temperature,
        record_id=record.record_id,
        source_row=record.source_row,
        analysis=settings.analysis.key,
        prompt_version=version,
        prompt_hash=analysis.prompt_hash(version),
    )


async def analyze_record(
    record: InputRecord,
    *,
    analysis: Analysis,
    settings: Settings,
    client: ChatClient,
    model: str,
    log: RunLog,
) -> RecordOutcome:
    """Analyze one record. Never raises; every failure becomes a failed outcome."""
    outcome = RecordOutcome(
        record_id=record.record_id,
        source_row=record.source_row,
        status=STATUS_FAILED,
    )
    started = time.perf_counter()

    try:
        request = build_request(record, analysis=analysis, settings=settings, model=model)
        response = await client.complete(request)

        outcome.call_id = response.call_id
        outcome.source_call_id = response.source_call_id
        outcome.cached = response.cached
        outcome.prompt_tokens = response.prompt_tokens
        outcome.completion_tokens = response.completion_tokens

        payload = parse_json_object(response.content)
        result = analysis.result_model.model_validate(payload)
        issues = analysis.validate_result(record, result)

        outcome.values = flatten_result(result)
        outcome.issues = issues
        outcome.status = STATUS_FLAGGED if issues else STATUS_OK
    except ValidationError as exc:
        outcome.error = f"response did not match the {analysis.name} schema: {exc.error_count()} problem(s)"
        outcome.issues = [_describe(error) for error in exc.errors()]
    except (AnalysisError, LlmError) as exc:
        outcome.error = str(exc)
    except Exception as exc:  # Isolation: one bad record must not end the run.
        outcome.error = f"{type(exc).__name__}: {exc}"
    finally:
        outcome.duration_seconds = time.perf_counter() - started

    if outcome.status == STATUS_FAILED:
        log.error("record.failed", record_id=record.record_id, error=outcome.error)
    else:
        log.event(
            "record.done",
            record_id=record.record_id,
            status=outcome.status,
            issues=len(outcome.issues) or None,
            cached=outcome.cached or None,
            duration_s=f"{outcome.duration_seconds:.2f}",
        )
    return outcome


def _describe(error: dict[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
    return f"{location}: {error.get('msg', 'invalid')}"


async def run(
    selection: Selection,
    *,
    analysis: Analysis,
    settings: Settings,
    client: ChatClient,
    model: str,
    run_paths: RunPaths,
    run_id: str,
    log: RunLog,
    cache: Any | None = None,
) -> RunReport:
    """Analyze every selected record, writing results as they complete.

    ``cache`` is read after the run finishes, so its counters are final rather than
    the zeroes they held when the stack was assembled.
    """
    started_at = utc_now()
    started = time.perf_counter()
    semaphore = asyncio.Semaphore(settings.analysis.concurrency)
    write_lock = asyncio.Lock()

    log.event(
        "run.start",
        run_id=run_id,
        analysis=settings.analysis.key,
        records=len(selection.records),
        concurrency=settings.analysis.concurrency,
        cache_mode=settings.cache.mode,
    )

    results_path = run_paths.results_path
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_handle = results_path.open("w", encoding="utf-8")
    outcomes: list[RecordOutcome] = []

    async def worker(record: InputRecord) -> RecordOutcome:
        async with semaphore:
            outcome = await analyze_record(
                record,
                analysis=analysis,
                settings=settings,
                client=client,
                model=model,
                log=log,
            )
        async with write_lock:
            results_handle.write(json.dumps(outcome.as_json(), ensure_ascii=False) + "\n")
            results_handle.flush()
            outcomes.append(outcome)
        return outcome

    tasks = [asyncio.create_task(worker(record)) for record in selection.records]
    try:
        # gather() surfaces the first failure immediately but leaves its siblings
        # running, so they are cancelled and awaited before anything is closed.
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                log.error("run.worker_failed", error=f"{type(result).__name__}: {result}")
        raise
    finally:
        results_handle.close()

    order = {record.record_id: index for index, record in enumerate(selection.records)}
    outcomes.sort(key=lambda item: order.get(item.record_id, 0))

    finished_at = utc_now()
    report = RunReport(
        run_id=run_id,
        outcomes=outcomes,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_seconds=time.perf_counter() - started,
        cache_hits=getattr(cache, "hits", 0),
        cache_misses=getattr(cache, "misses", 0),
    )

    log.event(
        "run.done",
        run_id=run_id,
        ok=report.succeeded,
        flagged=report.flagged,
        failed=report.failed,
        cache_hits=report.cache_hits,
        duration_s=f"{report.duration_seconds:.2f}",
    )
    return report


def write_manifest(
    run_paths: RunPaths,
    *,
    report: RunReport,
    settings: Settings,
    selection: Selection,
    analysis: Analysis,
    model: str,
    config_path: str,
    backend: str = "api",
) -> None:
    """Write ``manifest.json``: everything needed to understand the run, no credentials."""
    manifest = {
        "finalized": True,
        "run_id": report.run_id,
        "config_path": config_path,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_seconds": round(report.duration_seconds, 3),
        "backend": {"type": backend, "model": model},
        "analysis": {
            "name": analysis.name,
            "key": settings.analysis.key,
            "version": settings.analysis.version,
            "prompt_hash": analysis.prompt_hash(settings.analysis.version),
            "output_columns": analysis.output_columns,
            "concurrency": settings.analysis.concurrency,
            "max_output_tokens": settings.analysis.max_output_tokens,
            "temperature": settings.analysis.temperature,
        },
        "model": model,
        "dataset": {
            "path": str(settings.dataset.path),
            "sheet": settings.dataset.sheet,
            "id_field": settings.dataset.id_field,
            "fields": list(settings.dataset.fields),
            "filters": [spec.model_dump() for spec in settings.dataset.filters],
            "limit": settings.dataset.limit,
        },
        "selection": {
            "total_rows": selection.total_rows,
            "matched_rows": selection.matched_rows,
            "analyzed_rows": len(selection.records),
            "skipped": [
                {"source_row": item.source_row, "reason": item.reason}
                for item in selection.skipped
            ],
        },
        "rate_limits": settings.rate_limits.model_dump(),
        "cache": {
            "mode": settings.cache.mode,
            "hits": report.cache_hits,
            "misses": report.cache_misses,
        },
        "results": {
            "ok": report.succeeded,
            "flagged": report.flagged,
            "failed": report.failed,
            "prompt_tokens": report.prompt_tokens,
            "completion_tokens": report.completion_tokens,
            "total_tokens": report.prompt_tokens + report.completion_tokens,
            "reused_prompt_tokens": report.reused_prompt_tokens,
            "reused_completion_tokens": report.reused_completion_tokens,
            "reused_total_tokens": report.reused_prompt_tokens + report.reused_completion_tokens,
        },
    }
    temporary = run_paths.manifest_path.with_name(run_paths.manifest_path.name + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, run_paths.manifest_path)


def output_rows(report: RunReport) -> Sequence[OutputRow]:
    return [outcome.to_output_row() for outcome in report.outcomes]
