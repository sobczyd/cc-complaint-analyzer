"""The layer that writes every attempt to disk.

One call directory per attempt, holding the request, the reply, timings, and the
attempt's own log. This is what makes a run auditable after the fact.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..logs import CallLog, RunLog
from ..run_paths import METADATA_NAME, REQUEST_NAME, RESPONSE_NAME, RunPaths, utc_now
from .protocol import ChatClient, ChatRequest, ChatResponse, LlmError


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


class RecordingClient:
    """Wraps a client and saves each attempt under ``calls/<analysis>/<stamp>_<id>/``."""

    def __init__(self, inner: ChatClient, *, run_paths: RunPaths, log: RunLog) -> None:
        self._inner = inner
        self._run_paths = run_paths
        self._log = log

    async def complete(self, request: ChatRequest) -> ChatResponse:
        started = utc_now()
        call_id = f"{request.record_id}-a{request.attempt}"
        call_dir = self._run_paths.call_dir(request.analysis, call_id, started)
        call_log = self._log.call_log(call_dir)
        try:
            return await self._record(request, started, call_id, call_dir, call_log)
        finally:
            call_log.close()

    async def _record(
        self,
        request: ChatRequest,
        started: Any,
        call_id: str,
        call_dir: Path,
        call_log: CallLog,
    ) -> ChatResponse:
        write_json(call_dir / REQUEST_NAME, request.request_payload())
        call_log.local(
            "call.start",
            record_id=request.record_id,
            attempt=request.attempt,
            model=request.model,
            fingerprint=request.fingerprint(),
        )

        monotonic_start = time.perf_counter()
        try:
            response = await self._inner.complete(request)
        except LlmError as exc:
            duration = time.perf_counter() - monotonic_start
            self._note_failure(
                request,
                started,
                duration,
                call_dir,
                call_log,
                error=exc.as_dict(),
                fields={
                    "kind": exc.kind,
                    "status_code": exc.status_code,
                    "retryable": exc.retryable,
                    "error": str(exc),
                },
            )
            raise
        except BaseException as exc:
            duration = time.perf_counter() - monotonic_start
            self._note_failure(
                request,
                started,
                duration,
                call_dir,
                call_log,
                error={"message": str(exc), "kind": type(exc).__name__},
                fields={"error": f"{type(exc).__name__}: {exc}"},
            )
            raise

        duration = time.perf_counter() - monotonic_start
        stamped = ChatResponse(
            content=response.content,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            raw=response.raw,
            call_id=call_id,
            cached=response.cached,
            source_call_id=response.source_call_id,
        )

        write_json(
            call_dir / RESPONSE_NAME,
            {
                "call_id": call_id,
                "content": stamped.content,
                "model": stamped.model,
                "prompt_tokens": stamped.prompt_tokens,
                "completion_tokens": stamped.completion_tokens,
                "cached": stamped.cached,
                "source_call_id": stamped.source_call_id,
                "raw": stamped.raw,
            },
        )
        write_json(
            call_dir / METADATA_NAME,
            self._metadata(
                request,
                started,
                duration,
                outcome="ok",
                extra={
                    "call_id": call_id,
                    "prompt_tokens": stamped.prompt_tokens,
                    "completion_tokens": stamped.completion_tokens,
                    "total_tokens": stamped.total_tokens,
                    "cached": stamped.cached,
                    "source_call_id": stamped.source_call_id,
                },
            ),
        )
        call_log.local(
            "call.ok",
            record_id=request.record_id,
            attempt=request.attempt,
            duration_s=f"{duration:.3f}",
            total_tokens=stamped.total_tokens,
            cached=stamped.cached,
        )
        return stamped

    def _note_failure(
        self,
        request: ChatRequest,
        started: Any,
        duration: float,
        call_dir: Path,
        call_log: CallLog,
        *,
        error: dict[str, Any],
        fields: dict[str, Any],
    ) -> None:
        """Best effort: never mask the exception that is already propagating."""
        try:
            write_json(
                call_dir / METADATA_NAME,
                self._metadata(request, started, duration, outcome="error", error=error),
            )
            call_log.error(
                "call.failed",
                record_id=request.record_id,
                attempt=request.attempt,
                **fields,
            )
        except Exception:  # noqa: BLE001 - recording must not replace the real failure
            pass

    def _metadata(
        self,
        request: ChatRequest,
        started: Any,
        duration: float,
        *,
        outcome: str,
        error: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcome": outcome,
            "record_id": request.record_id,
            "source_row": request.source_row,
            "analysis": request.analysis,
            "prompt_version": request.prompt_version,
            "prompt_hash": request.prompt_hash,
            "attempt": request.attempt,
            "model": request.model,
            "fingerprint": request.fingerprint(),
            "started_at": started.isoformat(),
            "duration_seconds": round(duration, 3),
        }
        if error is not None:
            payload["error"] = error
        if extra is not None:
            payload.update(extra)
        return payload
