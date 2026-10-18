"""The layer that reuses replies from earlier runs.

The index is built once, by walking every ``request.json`` already on disk under the
runs directory. A hit is returned without touching the network, which makes re-running
an unchanged configuration cheap and deterministic.

Only replies that an earlier run turned into a usable record result are reusable. A
200 carrying unparseable content is a transport success but an application failure, so
indexing it would serve the same broken reply back forever. ``results.jsonl`` is the
source of truth for that distinction.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..core.logs import RunLog
from ..core.run_paths import (
    CALLS_DIR_NAME,
    METADATA_NAME,
    REQUEST_NAME,
    RESPONSE_NAME,
    RESULTS_NAME,
)
from .protocol import ChatClient, ChatRequest, ChatResponse

USABLE_STATUSES = frozenset({"ok", "flagged"})


@dataclass(frozen=True)
class CachedCall:
    """A previously saved reply, located by request fingerprint."""

    fingerprint: str
    call_dir: Path
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    call_id: str


def _read_json(path: Path) -> dict | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _listdir(directory: Path, *, log: RunLog | None) -> list[Path]:
    """Sorted children of ``directory``; an unreadable directory yields nothing."""
    try:
        return sorted(directory.iterdir())
    except OSError as exc:
        if log is not None:
            log.warning("cache.scan_failed", path=str(directory), error=str(exc))
        return []


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _call_id_of(call_dir: Path, response: dict) -> str:
    recorded = response.get("call_id")
    if isinstance(recorded, str) and recorded:
        return recorded
    name = call_dir.name
    return name.split("_", 1)[1] if "_" in name else name


def usable_call_ids(run_dir: Path, *, log: RunLog | None = None) -> frozenset[str] | None:
    """Call ids that produced an ``ok`` or ``flagged`` record in ``run_dir``.

    ``None`` means the run never recorded what its calls produced, so nothing from it
    can be trusted. Rows answered from cache carry ``call_id: null`` and add nothing.
    """
    path = run_dir / RESULTS_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        if log is not None:
            log.warning("cache.results_unreadable", path=str(path), error=str(exc))
        return None

    usable: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("status") not in USABLE_STATUSES:
            continue
        call_id = row.get("call_id")
        if isinstance(call_id, str) and call_id:
            usable.add(call_id)
    return frozenset(usable)


def iter_call_dirs(
    runs_dir: Path, *, skip: Path | None = None, log: RunLog | None = None
) -> Iterator[Path]:
    """Yield every call directory under ``runs_dir``, newest run first."""
    if not runs_dir.is_dir():
        return
    runs = sorted(
        (entry for entry in _listdir(runs_dir, log=log) if entry.is_dir()),
        key=lambda entry: entry.name,
        reverse=True,
    )
    for run in runs:
        if skip is not None and _same_dir(run, skip):
            continue
        calls = run / CALLS_DIR_NAME
        if not calls.is_dir():
            continue
        for analysis_dir in _listdir(calls, log=log):
            if not analysis_dir.is_dir():
                continue
            for call_dir in _listdir(analysis_dir, log=log):
                if call_dir.is_dir():
                    yield call_dir


def build_index(
    runs_dir: Path, *, skip: Path | None = None, log: RunLog | None = None
) -> dict[str, CachedCall]:
    """Map fingerprint to the most recent reusable call that produced it."""
    index: dict[str, CachedCall] = {}
    usable_by_run: dict[Path, frozenset[str] | None] = {}

    for call_dir in iter_call_dirs(runs_dir, skip=skip, log=log):
        run_dir = call_dir.parents[2]
        if run_dir not in usable_by_run:
            usable_by_run[run_dir] = usable_call_ids(run_dir, log=log)
        usable = usable_by_run[run_dir]
        if not usable:
            continue

        request = _read_json(call_dir / REQUEST_NAME)
        if not request:
            continue
        fingerprint = request.get("fingerprint")
        if not isinstance(fingerprint, str) or fingerprint in index:
            continue

        metadata = _read_json(call_dir / METADATA_NAME)
        if metadata is not None and metadata.get("outcome") != "ok":
            continue

        response = _read_json(call_dir / RESPONSE_NAME)
        if not response:
            continue
        content = response.get("content")
        if not isinstance(content, str) or not content.strip():
            continue

        call_id = _call_id_of(call_dir, response)
        if call_id not in usable:
            continue

        index[fingerprint] = CachedCall(
            fingerprint=fingerprint,
            call_dir=call_dir,
            content=content,
            model=str(response.get("model") or request.get("model") or ""),
            prompt_tokens=_int_or_none(response.get("prompt_tokens")),
            completion_tokens=_int_or_none(response.get("completion_tokens")),
            call_id=call_id,
        )

    return index


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class CachingClient:
    """Serves matching requests from earlier runs; otherwise delegates."""

    def __init__(self, inner: ChatClient, *, index: dict[str, CachedCall], log: RunLog) -> None:
        self._inner = inner
        self._index = index
        self._log = log
        self.hits = 0
        self.misses = 0

    @classmethod
    def from_runs_dir(
        cls,
        inner: ChatClient,
        *,
        runs_dir: Path,
        log: RunLog,
        skip: Path | None = None,
    ) -> "CachingClient":
        index = build_index(runs_dir, skip=skip, log=log)
        log.event("cache.index", entries=len(index), runs_dir=str(runs_dir))
        return cls(inner, index=index, log=log)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        fingerprint = request.fingerprint()
        cached = self._index.get(fingerprint)
        if cached is None:
            self.misses += 1
            return await self._inner.complete(request)

        self.hits += 1
        self._log.event(
            "cache.hit",
            record_id=request.record_id,
            source_call_id=cached.call_id,
            source=str(cached.call_dir),
        )
        return ChatResponse(
            content=cached.content,
            model=cached.model or request.model,
            prompt_tokens=cached.prompt_tokens,
            completion_tokens=cached.completion_tokens,
            raw=None,
            call_id=None,
            cached=True,
            source_call_id=cached.call_id,
        )


class PassthroughClient:
    """``cache.mode: off``. Present so the stack shape never changes."""

    def __init__(self, inner: ChatClient) -> None:
        self._inner = inner
        self.hits = 0
        self.misses = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.misses += 1
        return await self._inner.complete(request)
