"""Regression tests for cache poisoning, directory errors, and call-log closure."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterable

import pytest

from complaint_analyzer.llm_client.cache import CachingClient, build_index, iter_call_dirs
from complaint_analyzer.llm_client.protocol import ChatMessage, ChatRequest, LlmError
from complaint_analyzer.llm_client.recorder import RecordingClient
from complaint_analyzer.core.logs import CallLog, RunLog
from complaint_analyzer.core.run_paths import RunPaths

from conftest import FakeTransport, rca_payload

UNPARSEABLE = "I'm sorry, I can't produce JSON for this record."


def make_request(**overrides: Any) -> ChatRequest:
    base: dict[str, Any] = {
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


class CapturingLog(RunLog):
    """A run log that keeps every ``CallLog`` it hands out, so closure can be checked."""

    def __init__(self) -> None:
        super().__init__(None, echo=False)
        self.call_logs: list[CallLog] = []

    def call_log(self, call_dir: Path) -> CallLog:
        made = super().call_log(call_dir)
        self.call_logs.append(made)
        return made


def is_open(call_log: CallLog) -> bool:
    return call_log._writer._handle is not None


def results_row(record_id: str, status: str, call_id: str | None, **extra: Any) -> dict[str, Any]:
    """One ``results.jsonl`` row in exactly the shape ``runner`` writes."""
    row: dict[str, Any] = {
        "record_id": record_id,
        "source_row": 2,
        "status": status,
        "values": {},
        "issues": [],
        "error": None,
        "call_id": call_id,
        "source_call_id": None,
        "cached": False,
        "prompt_tokens": 120,
        "completion_tokens": 60,
        "duration_seconds": 0.1,
    }
    row.update(extra)
    return row


def write_results(run_paths: RunPaths, rows: Iterable[dict[str, Any]]) -> None:
    run_paths.results_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


async def seed_run(
    tmp_path: Path,
    log: RunLog,
    *,
    run_id: str,
    reply: Any,
    rows: Iterable[dict[str, Any]] | None,
    request: ChatRequest | None = None,
) -> RunPaths:
    """A realistic run directory: one recorded call plus the run's ``results.jsonl``."""
    paths = RunPaths.create(tmp_path, run_id)
    recorder = RecordingClient(FakeTransport(replies=[reply]), run_paths=paths, log=log)
    await recorder.complete(request or make_request())
    if rows is not None:
        write_results(paths, rows)
    return paths


def looked_reusable_before_the_fix(call_dir: Path) -> bool:
    """The admission rule this module used to apply: metadata ok plus non-blank content."""
    metadata = json.loads((call_dir / "metadata.json").read_text(encoding="utf-8"))
    response = json.loads((call_dir / "response.json").read_text(encoding="utf-8"))
    return metadata.get("outcome") == "ok" and bool(str(response.get("content", "")).strip())


def only_call_dir(runs_dir: Path) -> Path:
    dirs = list(iter_call_dirs(runs_dir))
    assert len(dirs) == 1
    return dirs[0]


# --- bug 1: an unusable reply must never be reused ------------------------------


async def test_a_reply_the_run_could_not_use_is_not_indexed(tmp_path: Path, log: RunLog) -> None:
    """A 200 carrying unparseable content is an application failure, not a cache entry."""
    paths = await seed_run(
        tmp_path,
        log,
        run_id="run_poison",
        reply=UNPARSEABLE,
        rows=[results_row("R-001", "failed", "R-001-a1", error="invalid JSON")],
    )

    call_dir = only_call_dir(tmp_path)
    assert looked_reusable_before_the_fix(call_dir), "the pre-fix rule would have cached this"
    assert (paths.run_dir / "results.jsonl").exists()

    assert build_index(tmp_path) == {}


async def test_the_poisoned_run_no_longer_answers_a_later_run(
    tmp_path: Path, log: RunLog
) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_poison",
        reply=UNPARSEABLE,
        rows=[results_row("R-001", "failed", "R-001-a1", error="invalid JSON")],
    )

    transport = FakeTransport(replies=[rca_payload()])
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)
    response = await client.complete(make_request())

    assert transport.call_count == 1
    assert response.cached is False
    assert UNPARSEABLE not in response.content
    assert (client.hits, client.misses) == (0, 1)


async def test_a_usable_reply_is_still_reused(tmp_path: Path, log: RunLog) -> None:
    """The fix must not work by disabling the cache."""
    await seed_run(
        tmp_path,
        log,
        run_id="run_good",
        reply={"symptom": "from the first run"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )

    transport = FakeTransport(responder=lambda _r: pytest.fail("cache should have answered"))
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)
    response = await client.complete(make_request(record_id="R-777"))

    assert "from the first run" in response.content
    assert response.cached is True
    assert response.source_call_id == "R-001-a1"
    assert transport.call_count == 0
    assert (client.hits, client.misses) == (1, 0)


async def test_a_flagged_record_is_reusable(tmp_path: Path, log: RunLog) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_flagged",
        reply={"symptom": "good enough"},
        rows=[results_row("R-001", "flagged", "R-001-a1", issues=["needs review"])],
    )
    assert len(build_index(tmp_path)) == 1


async def test_a_good_run_heals_an_earlier_poisoned_one(tmp_path: Path, log: RunLog) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_1_poison",
        reply=UNPARSEABLE,
        rows=[results_row("R-001", "failed", "R-001-a1")],
    )
    await seed_run(
        tmp_path,
        log,
        run_id="run_2_good",
        reply={"symptom": "healed"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )

    transport = FakeTransport(responder=lambda _r: pytest.fail("cache should have answered"))
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)
    response = await client.complete(make_request())

    assert "healed" in response.content


async def test_a_run_without_results_is_not_trusted(tmp_path: Path, log: RunLog) -> None:
    await seed_run(
        tmp_path, log, run_id="run_incomplete", reply={"symptom": "unverified"}, rows=None
    )
    assert build_index(tmp_path) == {}


async def test_an_unreadable_results_file_is_not_trusted(tmp_path: Path, log: RunLog) -> None:
    paths = await seed_run(
        tmp_path,
        log,
        run_id="run_unreadable",
        reply={"symptom": "unverified"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    results = paths.results_path
    results.unlink()
    results.mkdir()  # A directory where a file belongs makes read_text raise OSError.

    assert build_index(tmp_path) == {}


async def test_cache_answered_rows_parse_but_add_nothing(tmp_path: Path, log: RunLog) -> None:
    """Rows served from cache carry ``call_id: null`` and a ``source_call_id``."""
    await seed_run(
        tmp_path,
        log,
        run_id="run_cached_rows",
        reply={"symptom": "unverified"},
        rows=[
            results_row("R-001", "ok", None, source_call_id="R-001-a1", cached=True),
            {"not": "a results row"},
            "",
        ],
    )
    assert build_index(tmp_path) == {}


async def test_malformed_results_lines_are_skipped(tmp_path: Path, log: RunLog) -> None:
    paths = await seed_run(
        tmp_path,
        log,
        run_id="run_mixed",
        reply={"symptom": "fine"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    with paths.results_path.open("a", encoding="utf-8") as handle:
        handle.write("{ not json\n")
        handle.write("null\n")
        handle.write("\n")

    assert len(build_index(tmp_path)) == 1


async def test_a_superseded_attempt_is_not_indexed(tmp_path: Path, log: RunLog) -> None:
    """Attempt 1 failed at the transport; only the attempt results.jsonl names is cached."""
    paths = RunPaths.create(tmp_path, "run_retry")
    transport = FakeTransport(replies=[UNPARSEABLE, json.dumps({"symptom": "second attempt"})])
    recorder = RecordingClient(transport, run_paths=paths, log=log)
    await recorder.complete(make_request(attempt=1))
    await recorder.complete(make_request(attempt=2))
    write_results(paths, [results_row("R-001", "ok", "R-001-a2")])

    index = build_index(tmp_path)
    assert len(index) == 1
    entry = next(iter(index.values()))
    assert entry.call_id == "R-001-a2"
    assert "second attempt" in entry.content


async def test_a_call_with_no_results_row_at_all_is_not_indexed(
    tmp_path: Path, log: RunLog
) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_orphan",
        reply={"symptom": "orphan"},
        rows=[results_row("R-999", "ok", "R-999-a1")],
    )
    assert build_index(tmp_path) == {}


# --- bug 2: directory enumeration must degrade, never abort ---------------------


def _raise_on(target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = Path.iterdir

    def guarded(self: Path):
        if self == target:
            raise PermissionError(13, "access denied")
        return real(self)

    monkeypatch.setattr(Path, "iterdir", guarded)


async def test_an_unreadable_runs_dir_yields_an_empty_index(
    tmp_path: Path, log: RunLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_good",
        reply={"symptom": "fine"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    _raise_on(tmp_path, monkeypatch)
    assert build_index(tmp_path) == {}


async def test_an_unreadable_calls_dir_does_not_abort_the_scan(
    tmp_path: Path, log: RunLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = await seed_run(
        tmp_path,
        log,
        run_id="run_2_broken",
        reply={"symptom": "unreachable"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    await seed_run(
        tmp_path,
        log,
        run_id="run_1_fine",
        reply={"symptom": "still indexed"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )

    _raise_on(broken.calls_dir, monkeypatch)
    index = build_index(tmp_path, log=log)

    assert len(index) == 1
    assert "still indexed" in next(iter(index.values())).content


async def test_an_unreadable_analysis_dir_does_not_abort_the_scan(
    tmp_path: Path, log: RunLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = await seed_run(
        tmp_path,
        log,
        run_id="run_2_broken",
        reply={"symptom": "unreachable"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    await seed_run(
        tmp_path,
        log,
        run_id="run_1_fine",
        reply={"symptom": "still indexed"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )

    _raise_on(broken.calls_dir / "rca-v1", monkeypatch)
    index = build_index(tmp_path, log=log)

    assert len(index) == 1
    assert "still indexed" in next(iter(index.values())).content


async def test_the_caching_client_still_builds_when_the_cache_is_unreadable(
    tmp_path: Path, log: RunLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_run(
        tmp_path,
        log,
        run_id="run_good",
        reply={"symptom": "fine"},
        rows=[results_row("R-001", "ok", "R-001-a1")],
    )
    _raise_on(tmp_path, monkeypatch)

    transport = FakeTransport()
    client = CachingClient.from_runs_dir(transport, runs_dir=tmp_path, log=log)
    await client.complete(make_request())

    assert transport.call_count == 1


# --- bug 3: the call log is always closed ---------------------------------------


class _Cancelling:
    async def complete(self, _request: ChatRequest):
        raise asyncio.CancelledError()


class _Exploding:
    async def complete(self, _request: ChatRequest):
        raise RuntimeError("transport exploded")


async def test_cancellation_closes_the_call_log(tmp_path: Path) -> None:
    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_cancel")
    recorder = RecordingClient(_Cancelling(), run_paths=paths, log=capturing)

    with pytest.raises(asyncio.CancelledError):
        await recorder.complete(make_request())

    assert len(capturing.call_logs) == 1
    assert not is_open(capturing.call_logs[0])


async def test_cancellation_releases_the_process_log_file(tmp_path: Path) -> None:
    """An open handle would block the unlink on Windows."""
    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_cancel")
    recorder = RecordingClient(_Cancelling(), run_paths=paths, log=capturing)

    with pytest.raises(asyncio.CancelledError):
        await recorder.complete(make_request())

    call_dir = only_call_dir(tmp_path)
    (call_dir / "process.log").unlink()


async def test_an_unexpected_exception_closes_the_call_log(tmp_path: Path) -> None:
    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_boom")
    recorder = RecordingClient(_Exploding(), run_paths=paths, log=capturing)

    with pytest.raises(RuntimeError):
        await recorder.complete(make_request())

    assert not is_open(capturing.call_logs[0])


async def test_an_llm_error_closes_the_call_log(tmp_path: Path) -> None:
    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_err")
    recorder = RecordingClient(
        FakeTransport(replies=[LlmError("nope", status_code=400)]),
        run_paths=paths,
        log=capturing,
    )

    with pytest.raises(LlmError):
        await recorder.complete(make_request())

    assert not is_open(capturing.call_logs[0])


async def test_a_successful_call_closes_the_call_log(tmp_path: Path) -> None:
    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_ok")
    recorder = RecordingClient(FakeTransport(), run_paths=paths, log=capturing)

    await recorder.complete(make_request())

    assert not is_open(capturing.call_logs[0])


async def test_a_failure_while_writing_output_still_closes_the_call_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from complaint_analyzer.llm_client import recorder as recorder_module

    def refuse(path: Path, payload: Any) -> None:
        raise OSError(28, "no space left on device")

    monkeypatch.setattr(recorder_module, "write_json", refuse)

    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_full_disk")
    recorder = RecordingClient(FakeTransport(), run_paths=paths, log=capturing)

    with pytest.raises(OSError):
        await recorder.complete(make_request())

    assert not is_open(capturing.call_logs[0])


async def test_a_recording_failure_does_not_mask_the_transport_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from complaint_analyzer.llm_client import recorder as recorder_module

    real = recorder_module.write_json
    calls = {"n": 0}

    def refuse_metadata(path: Path, payload: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            real(path, payload)
            return
        raise OSError(28, "no space left on device")

    monkeypatch.setattr(recorder_module, "write_json", refuse_metadata)

    capturing = CapturingLog()
    paths = RunPaths.create(tmp_path, "run_mask")
    recorder = RecordingClient(_Exploding(), run_paths=paths, log=capturing)

    with pytest.raises(RuntimeError, match="transport exploded"):
        await recorder.complete(make_request())

    assert not is_open(capturing.call_logs[0])
