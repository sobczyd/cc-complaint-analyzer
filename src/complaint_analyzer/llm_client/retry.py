"""The layer that retries transient failures.

Only ``LlmError.retryable`` is retried. A server-supplied ``retry_after`` always wins
over the computed backoff, because the server knows when it will accept traffic again.
"""

from __future__ import annotations

import asyncio
import random

from ..core.logs import RunLog
from .protocol import ChatClient, ChatRequest, ChatResponse, LlmError

BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 60.0
SERVER_SPREAD_SECONDS = 1.0


def backoff_delay(
    attempt: int,
    *,
    retry_after: float | None = None,
    jitter: float = 1.0,
    spread: bool = False,
) -> float:
    """Seconds to wait before ``attempt`` + 1.

    A server-supplied ``retry_after`` is authoritative: it is never clamped to
    ``MAX_DELAY_SECONDS``, which caps only the computed exponential backoff. When
    ``spread`` is set, other tasks are already backing off, so a small positive
    offset is added to keep them from waking in lockstep; the server's minimum is
    still respected.
    """
    if retry_after is not None and retry_after >= 0:
        if not spread:
            return retry_after
        return retry_after + jitter * random.random() * SERVER_SPREAD_SECONDS
    exponential = min(BASE_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_DELAY_SECONDS)
    return exponential * (1 + jitter * random.random() * 0.25)


class RetryingClient:
    """Repeats a request up to ``max_attempts`` times while the failure is transient."""

    def __init__(
        self,
        inner: ChatClient,
        *,
        max_attempts: int,
        log: RunLog,
        sleep=asyncio.sleep,
        jitter: float = 1.0,
    ) -> None:
        self._inner = inner
        self._max_attempts = max(1, max_attempts)
        self._log = log
        self._sleep = sleep
        self._jitter = jitter
        self._backing_off = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        last: LlmError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._inner.complete(request.with_attempt(attempt))
            except LlmError as exc:
                last = exc
                if not exc.retryable or attempt == self._max_attempts:
                    break
                delay = backoff_delay(
                    attempt,
                    retry_after=exc.retry_after,
                    jitter=self._jitter,
                    spread=self._backing_off > 0,
                )
                self._log.warning(
                    "call.retry",
                    record_id=request.record_id,
                    attempt=attempt,
                    of=self._max_attempts,
                    kind=exc.kind,
                    status_code=exc.status_code,
                    retry_in_s=f"{delay:.2f}",
                )
                self._backing_off += 1
                try:
                    await self._sleep(delay)
                finally:
                    self._backing_off -= 1

        assert last is not None  # The loop either returns or records an error.
        if last.retryable:
            raise LlmError(
                f"giving up after {self._max_attempts} attempt(s): {last}",
                status_code=last.status_code,
                retry_after=last.retry_after,
                retryable=False,
                kind=last.kind,
            ) from last
        raise last
