"""Regression tests for token reconciliation, the token ceiling, and retry backoff."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from complaint_analyzer.llm_client.protocol import ChatMessage, ChatRequest, ChatResponse, LlmError
from complaint_analyzer.llm_client.rate_limit import RateLimitedClient, estimate_tokens
from complaint_analyzer.llm_client.retry import RetryingClient, backoff_delay
from complaint_analyzer.core.logs import RunLog

from conftest import FakeTransport, rca_payload
from test_llm_client_layers import make_request


@pytest.fixture
def log() -> RunLog:
    return RunLog(None, echo=False)


def small_request(record_id: str, *, max_output_tokens: int) -> ChatRequest:
    """A request whose token estimate is exactly ``max_output_tokens`` + 1."""
    return make_request(
        record_id=record_id,
        max_output_tokens=max_output_tokens,
        messages=(ChatMessage(role="user", content="xxxx"),),
    )


class GatedTransport:
    """Holds each request inside the transport until it is explicitly released."""

    def __init__(self, totals: dict[str, int]) -> None:
        self._totals = totals
        self.entered: dict[str, asyncio.Event] = {}
        self.release: dict[str, asyncio.Event] = {}

    def gate(self, record_id: str) -> None:
        self.entered[record_id] = asyncio.Event()
        self.release[record_id] = asyncio.Event()

    async def complete(self, request: ChatRequest) -> ChatResponse:
        entered = self.entered.get(request.record_id)
        if entered is not None:
            entered.set()
            await self.release[request.record_id].wait()
        return ChatResponse(
            content="{}",
            model=request.model,
            prompt_tokens=self._totals.get(request.record_id, 0),
            completion_tokens=0,
        )


# --- bug 1: reconciliation must correct the caller's own reservation ------------


async def test_concurrent_reconciliation_corrects_each_own_reservation(log: RunLog) -> None:
    now = {"value": 0.0}
    waits: list[float] = []

    async def advance(seconds: float) -> None:
        waits.append(seconds)
        now["value"] += seconds

    transport = GatedTransport({"A": 10, "B": 10})
    transport.gate("A")
    transport.gate("B")
    client = RateLimitedClient(
        transport,
        rpm=None,
        tpm=250,
        log=log,
        sleep=advance,
        clock=lambda: now["value"],
    )

    first = small_request("A", max_output_tokens=100)
    second = small_request("B", max_output_tokens=100)
    assert estimate_tokens(first) == 101

    task_a = asyncio.create_task(client.complete(first))
    task_b = asyncio.create_task(client.complete(second))
    await transport.entered["A"].wait()
    await transport.entered["B"].wait()  # Both reservations are in flight.

    transport.release["A"].set()
    await task_a
    transport.release["B"].set()
    await task_b

    assert waits == []
    assert client._tokens._used == 20  # 10 reported tokens each, not a shrunk neighbour.

    third = small_request("C", max_output_tokens=229)
    assert estimate_tokens(third) == 230
    await client.complete(third)
    assert waits == []  # 20 + 230 still fits inside the 250 token ceiling.


async def test_reconciliation_is_discarded_once_the_entry_expires(log: RunLog) -> None:
    now = {"value": 0.0}

    async def advance(seconds: float) -> None:
        now["value"] += seconds

    transport = GatedTransport({"A": 10})
    transport.gate("A")
    client = RateLimitedClient(
        transport,
        rpm=None,
        tpm=1000,
        log=log,
        sleep=advance,
        clock=lambda: now["value"],
    )

    task = asyncio.create_task(client.complete(small_request("A", max_output_tokens=100)))
    await transport.entered["A"].wait()
    now["value"] += 120.0  # The reservation falls out of the window mid-flight.
    transport.release["A"].set()
    await task

    assert client._tokens._used == 0


# --- bug 2: an oversized request is flagged, once -------------------------------


async def test_request_larger_than_tpm_warns_exactly_once(tmp_path: Path) -> None:
    now = {"value": 0.0}

    async def advance(seconds: float) -> None:
        now["value"] += seconds

    log_path = tmp_path / "run.log"
    log = RunLog(log_path, echo=False)
    client = RateLimitedClient(
        FakeTransport(),
        rpm=None,
        tpm=500,
        log=log,
        sleep=advance,
        clock=lambda: now["value"],
    )

    request = make_request(max_output_tokens=800)
    assert estimate_tokens(request) > 500

    await client.complete(request)
    await client.complete(make_request(record_id="R-002", max_output_tokens=800))
    log.close()

    lines = log_path.read_text(encoding="utf-8").splitlines()
    warnings = [line for line in lines if "ratelimit.request_exceeds_tpm" in line]
    assert len(warnings) == 1
    assert "WARN" in warnings[0]
    assert "tpm=500" in warnings[0]


# --- bug 3: a server-supplied Retry-After is never clamped ----------------------


def test_server_retry_after_is_not_capped_by_the_backoff_ceiling() -> None:
    assert backoff_delay(1, retry_after=120.0, jitter=0.0) == 120.0
    assert backoff_delay(1, retry_after=600.0) == 600.0
    assert backoff_delay(50, jitter=0.0) == 60.0  # The exponential cap still applies.


async def test_retry_honours_a_retry_after_longer_than_the_cap(log: RunLog) -> None:
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    error = LlmError("slow down", status_code=429, retry_after=180.0, retryable=True)
    transport = FakeTransport(replies=[error, rca_payload()])
    client = RetryingClient(transport, max_attempts=2, log=log, sleep=record_sleep, jitter=0.0)

    await client.complete(make_request())
    assert waits == [180.0]


# --- bug 4: concurrent retries do not wake in lockstep --------------------------


def _herd_transport(retry_after: float) -> FakeTransport:
    def responder(request: ChatRequest):
        if request.attempt == 1:
            return LlmError("slow down", status_code=429, retry_after=retry_after, retryable=True)
        return rca_payload()

    return FakeTransport(responder)


async def test_concurrent_retries_are_spread_above_the_server_delay(log: RunLog) -> None:
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)

    client = RetryingClient(
        _herd_transport(5.0), max_attempts=2, log=log, sleep=record_sleep, jitter=1.0
    )

    await asyncio.gather(
        *(client.complete(make_request(record_id=f"R-{index:03d}")) for index in range(8))
    )

    assert len(delays) == 8
    assert all(delay >= 5.0 for delay in delays)  # The server minimum is respected.
    assert len(set(delays)) > 1  # They do not all wake at the same instant.


async def test_jitter_zero_keeps_the_server_delay_exact(log: RunLog) -> None:
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)
        await asyncio.sleep(0)

    client = RetryingClient(
        _herd_transport(5.0), max_attempts=2, log=log, sleep=record_sleep, jitter=0.0
    )

    await asyncio.gather(
        *(client.complete(make_request(record_id=f"R-{index:03d}")) for index in range(4))
    )

    assert delays == [5.0, 5.0, 5.0, 5.0]
