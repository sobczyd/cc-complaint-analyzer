"""The layer that keeps request and token rates under the configured ceilings.

Two independent sliding windows: one counting requests, one counting tokens. A
``None`` limit disables its window entirely, which is the default.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque

from ..logs import RunLog
from .protocol import ChatClient, ChatRequest, ChatResponse

WINDOW_SECONDS = 60.0
CHARS_PER_TOKEN = 4


def estimate_tokens(request: ChatRequest) -> int:
    """A deliberately rough pre-call estimate.

    The real count is only known after the reply arrives, so this exists to stop the
    limiter from overshooting badly; it is reconciled against reported usage.
    """
    characters = sum(len(message.content) for message in request.messages)
    return max(1, characters // CHARS_PER_TOKEN) + request.max_output_tokens


@dataclass
class _Reservation:
    """A durable handle on one recorded entry, valid until the entry expires."""

    moment: float
    amount: int
    live: bool = True


class _SlidingWindow:
    """Counts units used in the last ``WINDOW_SECONDS`` and waits when full."""

    def __init__(self, limit: int, *, clock: Callable[[], float]) -> None:
        self._limit = limit
        self._clock = clock
        self._events: Deque[_Reservation] = deque()
        self._used = 0

    @property
    def limit(self) -> int:
        return self._limit

    def exceeds_limit(self, amount: int) -> bool:
        return amount > self._limit

    def _evict(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self._events and self._events[0].moment <= cutoff:
            entry = self._events.popleft()
            entry.live = False
            self._used -= entry.amount

    def wait_time(self, amount: int) -> float:
        now = self._clock()
        self._evict(now)
        if self._used + amount <= self._limit:
            return 0.0
        if not self._events:
            # A single request larger than the whole budget can never fit; waiting
            # for an empty window would block forever. The caller warns about it.
            return 0.0
        return max(0.0, self._events[0].moment + WINDOW_SECONDS - now)

    def record(self, amount: int) -> _Reservation:
        now = self._clock()
        self._evict(now)
        entry = _Reservation(now, amount)
        self._events.append(entry)
        self._used += amount
        return entry

    def adjust(self, reservation: _Reservation | None, delta: int) -> None:
        """Correct one specific entry once its true cost is known."""
        if reservation is None or delta == 0:
            return
        self._evict(self._clock())
        if not reservation.live:
            return
        corrected = max(0, reservation.amount + delta)
        self._used += corrected - reservation.amount
        reservation.amount = corrected


class RateLimitedClient:
    """Throttles to ``rpm`` requests and ``tpm`` tokens per minute."""

    def __init__(
        self,
        inner: ChatClient,
        *,
        rpm: int | None,
        tpm: int | None,
        log: RunLog,
        sleep=asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._log = log
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._requests = _SlidingWindow(rpm, clock=clock) if rpm else None
        self._tokens = _SlidingWindow(tpm, clock=clock) if tpm else None
        self._oversize_warned = False

    @property
    def enabled(self) -> bool:
        return self._requests is not None or self._tokens is not None

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if not self.enabled:
            return await self._inner.complete(request)

        estimated = estimate_tokens(request)
        reservation = await self._acquire(request, estimated)

        response = await self._inner.complete(request)

        actual = response.total_tokens
        if self._tokens is not None and actual is not None:
            async with self._lock:
                self._tokens.adjust(reservation, actual - estimated)
        return response

    async def _acquire(self, request: ChatRequest, estimated: int) -> _Reservation | None:
        self._warn_if_oversized(request, estimated)
        while True:
            async with self._lock:
                delay = 0.0
                if self._requests is not None:
                    delay = max(delay, self._requests.wait_time(1))
                if self._tokens is not None:
                    delay = max(delay, self._tokens.wait_time(estimated))

                if delay <= 0:
                    if self._requests is not None:
                        self._requests.record(1)
                    if self._tokens is not None:
                        return self._tokens.record(estimated)
                    return None

            self._log.event(
                "ratelimit.wait",
                record_id=request.record_id,
                wait_s=f"{delay:.2f}",
                estimated_tokens=estimated,
            )
            await self._sleep(delay)

    def _warn_if_oversized(self, request: ChatRequest, estimated: int) -> None:
        """Flag, once, that a single request cannot fit inside the token ceiling."""
        if self._oversize_warned or self._tokens is None:
            return
        if not self._tokens.exceeds_limit(estimated):
            return
        self._oversize_warned = True
        self._log.warning(
            "ratelimit.request_exceeds_tpm",
            record_id=request.record_id,
            estimated_tokens=estimated,
            tpm=self._tokens.limit,
            detail="one request's estimate exceeds the configured tpm; the ceiling cannot be honoured for it",
        )
