"""Structured run and per-call logging with secret redaction."""

from __future__ import annotations

import threading
from datetime import timezone
from pathlib import Path
from typing import Any, Iterable

from .run_paths import PROCESS_LOG_NAME, utc_now

REDACTED = "[redacted]"
_SECRET_KEY_HINTS = ("api_key", "apikey", "authorization", "token", "secret", "password")


class _Writer:
    """Append-only line writer that is safe to share across tasks."""

    def __init__(self, path: Path | None, *, echo: bool) -> None:
        self._path = path
        self._echo = echo
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8")
        else:
            self._handle = None

    def write(self, line: str) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.write(line + "\n")
                self._handle.flush()
            if self._echo:
                print(line, flush=True)

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.close()
                self._handle = None


def _format(level: str, event: str, fields: dict[str, Any]) -> str:
    stamp = utc_now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [f"{stamp} {level} {event}"]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", " ").replace("\r", " ")
        if any(hint in key.lower() for hint in _SECRET_KEY_HINTS):
            text = REDACTED
        parts.append(f"{key}={text}")
    return " ".join(parts)


class RunLog:
    """Writes ``run.log`` and echoes to stdout."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        echo: bool = True,
        secrets: Iterable[str] = (),
    ) -> None:
        self._writer = _Writer(path, echo=echo)
        self._secrets = tuple(s for s in secrets if s)

    def redact(self, line: str) -> str:
        for secret in self._secrets:
            line = line.replace(secret, REDACTED)
        return line

    def event(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        self._writer.write(self.redact(_format(level, event, fields)))

    def warning(self, event: str, **fields: Any) -> None:
        self.event(event, level="WARN", **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.event(event, level="ERROR", **fields)

    def call_log(self, call_dir: Path) -> "CallLog":
        return CallLog(call_dir / PROCESS_LOG_NAME, parent=self)

    def close(self) -> None:
        self._writer.close()


class CallLog:
    """Writes one attempt's ``process.log`` and forwards each event to the run log."""

    def __init__(self, path: Path, *, parent: RunLog) -> None:
        self._writer = _Writer(path, echo=False)
        self._parent = parent

    def event(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        self._writer.write(self._parent.redact(_format(level, event, fields)))
        self._parent.event(event, level=level, **fields)

    def local(self, event: str, *, level: str = "INFO", **fields: Any) -> None:
        """Record detail in ``process.log`` only, keeping ``run.log`` readable."""
        self._writer.write(self._parent.redact(_format(level, event, fields)))

    def warning(self, event: str, **fields: Any) -> None:
        self.event(event, level="WARN", **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.event(event, level="ERROR", **fields)

    def close(self) -> None:
        self._writer.close()
