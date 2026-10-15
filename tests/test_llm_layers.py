"""The client layers: fingerprinting, recording, retry, rate limiting, and cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from complaint_analyzer.llm.cache import CachingClient, PassthroughClient, build_index
from complaint_analyzer.llm.protocol import ChatMessage, ChatRequest, ChatResponse, LlmError
from complaint_analyzer.llm.rate_limit import RateLimitedClient, estimate_tokens
from complaint_analyzer.llm.recorder import RecordingClient
from complaint_analyzer.llm.retry import RetryingClient, backoff_delay
from complaint_analyzer.logs import RunLog
from complaint_analyzer.run_paths import RunPaths

from conftest import FakeTransport, permanent, transient


def make_request(**overrides) -> ChatRequest:
    base = {
        "model": "test-model",
        "messages": (
            ChatMessage(role="system", content="be careful"),
            ChatMessage(role="user", content="analyze this record"),
        ),
        "max_output_tokens": 800,
        "temperature": 0.0,
        "record_id": "R-001",
        "source_row": 2,
        "analysis": "rca-v1",
        "prompt_version": "v1",
        "prompt_hash": "abc123",
    }
    base.update(overrides)
    return ChatRequest(**base)


@pytest.fixture
def log() -> RunLog:
    return RunLog(None, echo=False)


# --- fingerprinting -------------------------------------------------------------


def test_fingerprint_ignores_record_identity_and_attempt() -> None:
    first = make_request()
    second = make_request(record_id="R-999", source_row=42, attempt=3)
    assert first.fingerprint() == second.fingerprint()


def test_fingerprint_tracks_generation_parameters() -> None:
    assert make_request().fingerprint() != make_request(temperature=0.7).fingerprint()
    assert make_request().fingerprint() != make_request(max_output_tokens=10).fingerprint()


def test_fingerprint_tracks_message_content() -> None:
    changed = make_request(
        messages=(ChatMessage(role="user", content="a different record"),)
    )
    assert make_request().fingerprint() != changed.fingerprint()


def test_request_payload_carries_no_credentials() -> None:
    payload = make_request().request_payload()
    assert "api_key" not in json.dumps(payload).lower()
    assert payload["fingerprint"] == make_request().fingerprint()


def test_with_attempt_is_non_mutating() -> None:
    request = make_request()
    assert request.with_attempt(4).attempt == 4
    assert request.attempt == 1


# --- recorder -------------------------------------------------------------------


async def test_recorder_writes_request_response_and_metadata(tmp_path: Path, log: RunLog) -> None:
    paths = RunPaths.create(tmp_path, "run_x")
    transport = FakeTransport()
    client = RecordingClient(transport, run_paths=paths, log=log)

    response = await client.complete(make_request())

    call_dirs = list((paths.calls_dir / "rca-v1").iterdir())
    assert len(call_dirs) == 1
    call_dir = call_dirs[0]
    assert {path.name for path in call_dir.iterdir()} == {
        "request.json",
        "response.json",
        "metadata.json",
        "process.log",
    }
    metadata = json.loads((call_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["outcome"] == "ok"
    assert metadata["record_id"] == "R-001"
    assert response.call_id == "R-001-a1"


async def test_recorder_records_failures_and_reraises(tmp_path: Path, log: RunLog) -> None:
    paths = RunPaths.create(tmp_path, "run_x")
    client = RecordingClient(FakeTransport(replies=[permanent()]), run_paths=paths, log=log)

    with pytest.raises(LlmError):
        await client.complete(make_request())

    call_dir = next((paths.calls_dir / "rca-v1").iterdir())
    metadata = json.loads((call_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["outcome"] == "error"
    assert metadata["error"]["status_code"] == 400
    assert not (call_dir / "response.json").exists()


async def test_recorder_gives_each_attempt_its_own_directory(tmp_path: Path, log: RunLog) -> None:
    paths = RunPaths.create(tmp_path, "run_x")
    transport = FakeTransport(replies=[transient(), transient(), {"symptom": "ok"}])
    client = RetryingClient(
        RecordingClient(transport, run_paths=paths, log=log),
        max_attempts=3,
        log=log,
        sleep=_no_sleep,
        jitter=0.0,
    )

    await client.complete(make_request())
    assert len(list((paths.calls_dir / "rca-v1").iterdir())) == 3


# --- retry ----------------------------------------------------------------------


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_retry_recovers_from_transient_failures(log: RunLog) -> None:
    transport = FakeTransport(replies=[transient(), {"symptom": "recovered"}])
    client = RetryingClient(transport, max_attempts=4, log=log, sleep=_no_sleep)

    response = await client.complete(make_request())
    assert "recovered" in response.content
    assert transport.call_count == 2
    assert [request.attempt for request in transport.requests] == [1, 2]


async def test_retry_does_not_repeat_permanent_failures(log: RunLog) -> None:
    transport = FakeTransport(replies=[permanent(), {"symptom": "never reached"}])
    client = RetryingClient(transport, max_attempts=4, log=log, sleep=_no_sleep)

    with pytest.raises(LlmError, match="bad request"):
        await client.complete(make_request())
    assert transport.call_count == 1


async def test_retry_gives_up_after_max_attempts(log: RunLog) -> None:
    transport = FakeTransport(responder=lambda _request: transient())
    client = RetryingClient(transport, max_attempts=3, log=log, sleep=_no_sleep)

    with pytest.raises(LlmError, match="giving up after 3"):
        await client.complete(make_request())
    assert transport.call_count == 3


async def test_retry_waits_for_server_supplied_retry_after(log: RunLog) -> None:
    waits: list[float] = []

    async def record_sleep(seconds: float) -> None:
        waits.append(seconds)

    error = LlmError("slow down", status_code=429, retry_after=7.5, retryable=True)
    transport = FakeTransport(replies=[error, {"symptom": "ok"}])
    client = RetryingClient(transport, max_attempts=2, log=log, sleep=record_sleep)

    await client.complete(make_request())
    assert waits == [7.5]


def test_backoff_grows_and_is_capped() -> None:
    assert backoff_delay(1, jitter=0.0) == 1.0
    assert backoff_delay(3, jitter=0.0) == 4.0
    assert backoff_delay(50, jitter=0.0) == 60.0
    assert backoff_delay(1, retry_after=2.0) == 2.0


# --- rate limiting --------------------------------------------------------------


def test_estimate_tokens_counts_prompt_and_reserved_output() -> None:
    request = make_request()
    characters = sum(len(message.content) for message in request.messages)
    assert estimate_tokens(request) == characters // 4 + 800


async def test_rate_limiter_is_inert_when_unconfigured(log: RunLog) -> None:
    transport = FakeTransport()
    client = RateLimitedClient(transport, rpm=None, tpm=None, log=log)
    assert client.enabled is False
    await client.complete(make_request())
    assert transport.call_count == 1


async def test_rate_limiter_waits_once_the_request_window_is_full(log: RunLog) -> None:
    now = {"value": 0.0}
    waits: list[float] = []

    async def advance(seconds: float) -> None:
        waits.append(seconds)
        now["value"] += seconds

    client = RateLimitedClient(
        FakeTransport(),
        rpm=2,
        tpm=None,
        log=log,
        sleep=advance,
        clock=lambda: now["value"],
    )

    for _ in range(3):
        await client.complete(make_request())

    assert len(waits) == 1
    assert waits[0] == pytest.approx(60.0)


async def test_rate_limiter_waits_on_the_token_window(log: RunLog) -> None:
    now = {"value": 0.0}
    waits: list[float] = []

    async def advance(seconds: float) -> None:
        waits.append(seconds)
        now["value"] += seconds

    client = RateLimitedClient(
        FakeTransport(),
        rpm=None,
        tpm=200,
        log=log,
        sleep=advance,
        clock=lambda: now["value"],
    )

    await client.complete(make_request(max_output_tokens=150))
    await client.complete(make_request(max_output_tokens=150))
    assert waits  # The second request could not fit in the same minute.


# --- cache ----------------------------------------------------------------------


async def _seed_run(tmp_path: Path, log: RunLog, *, run_id: str = "run_old") -> RunPaths:
    """Seed a completed run: a recorded call plus the results row that accepted it.

    The cache only reuses replies a run could actually use, so the results row is what
    makes the recorded call eligible. A real run always writes one.
    """
    paths = RunPaths.create(tmp_path, run_id)
    recorder = RecordingClient(
        FakeTransport(replies=[{"symptom": "from the first run"}]),
        run_paths=paths,
        log=log,
    )
    response = await recorder.complete(make_request())
    paths.results_path.write_text(
        json.dumps({"record_id": "R-001", "status": "ok", "call_id": response.call_id}) + "\n",
        encoding="utf-8",
    )
    return paths


async def test_cache_reuses_a_matching_reply_from_an_earlier_run(
    tmp_path: Path, log: RunLog
) -> None:
    await _seed_run(tmp_path, log)
    transport = FakeTransport(replies=[{"symptom": "should not be called"}])
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)

    response = await client.complete(make_request(record_id="R-777"))

    assert "from the first run" in response.content
    assert response.cached is True
    assert response.source_call_id == "R-001-a1"
    assert transport.call_count == 0
    assert (client.hits, client.misses) == (1, 0)


async def test_cache_misses_when_the_prompt_changes(tmp_path: Path, log: RunLog) -> None:
    await _seed_run(tmp_path, log)
    transport = FakeTransport()
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)

    await client.complete(make_request(messages=(ChatMessage(role="user", content="different"),)))
    assert transport.call_count == 1
    assert (client.hits, client.misses) == (0, 1)


async def test_cache_can_skip_the_current_run(tmp_path: Path, log: RunLog) -> None:
    paths = await _seed_run(tmp_path, log)
    transport = FakeTransport()
    client = CachingClient.from_runs_dir(
        transport, runs_dir=tmp_path, log=log, skip=paths.run_dir
    )
    await client.complete(make_request())
    assert transport.call_count == 1


async def test_cache_index_ignores_failed_and_malformed_calls(
    tmp_path: Path, log: RunLog
) -> None:
    paths = RunPaths.create(tmp_path, "run_bad")
    recorder = RecordingClient(FakeTransport(replies=[permanent()]), run_paths=paths, log=log)
    with pytest.raises(LlmError):
        await recorder.complete(make_request())

    broken = paths.calls_dir / "rca-v1" / "broken"
    broken.mkdir(parents=True)
    (broken / "request.json").write_text("{ not json", encoding="utf-8")

    assert build_index(tmp_path) == {}


def test_cache_index_on_an_absent_runs_dir_is_empty(tmp_path: Path) -> None:
    assert build_index(tmp_path / "never_created") == {}


async def test_passthrough_cache_always_delegates(log: RunLog) -> None:
    transport = FakeTransport()
    client = PassthroughClient(transport)
    await client.complete(make_request())
    await client.complete(make_request())
    assert transport.call_count == 2
    assert (client.hits, client.misses) == (0, 2)


# --- response helpers -----------------------------------------------------------


def test_total_tokens_is_none_only_when_nothing_is_reported() -> None:
    assert ChatResponse(content="", model="m").total_tokens is None
    assert ChatResponse(content="", model="m", prompt_tokens=10).total_tokens == 10
    assert (
        ChatResponse(content="", model="m", prompt_tokens=10, completion_tokens=5).total_tokens
        == 15
    )


def test_llm_error_reports_rate_limiting() -> None:
    assert LlmError("x", status_code=429).is_rate_limit is True
    assert LlmError("x", kind="rate_limit").is_rate_limit is True
    assert LlmError("x", status_code=500).is_rate_limit is False
