"""Transport-independent chat types, the ``ChatClient`` seam, and request fingerprints.

Every layer (cache, retry, rate limit, recorder, transport) implements ``ChatClient``,
so layers can be added, removed, or reordered in one place (``llm.build``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatRequest:
    """One outbound completion request."""

    model: str
    messages: tuple[ChatMessage, ...]
    max_output_tokens: int
    temperature: float
    record_id: str
    source_row: int
    analysis: str
    prompt_version: str
    prompt_hash: str
    attempt: int = 1
    extra: Mapping[str, Any] = field(default_factory=dict)

    def with_attempt(self, attempt: int) -> "ChatRequest":
        return replace(self, attempt=attempt)

    def fingerprint(self) -> str:
        """Deterministic identity of the request content.

        Covers only what changes the model's answer: model, messages, and generation
        parameters. Record identity, attempt number, and timestamps are excluded so a
        later cache lookup can match an equivalent request.
        """
        payload = {
            "model": self.model,
            "messages": [message.as_dict() for message in self.messages],
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def request_payload(self) -> dict[str, Any]:
        """Exactly what is saved to ``request.json`` (no credentials)."""
        return {
            "model": self.model,
            "messages": [message.as_dict() for message in self.messages],
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "analysis": self.analysis,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "record_id": self.record_id,
            "source_row": self.source_row,
            "attempt": self.attempt,
            "fingerprint": self.fingerprint(),
        }


@dataclass(frozen=True)
class ChatResponse:
    """A model reply, or a reused earlier reply."""

    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: Any = None
    call_id: str | None = None
    cached: bool = False
    source_call_id: str | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class LlmError(Exception):
    """A failed request attempt.

    ``retryable`` distinguishes a transient condition (429, timeout, 5xx) from a
    permanent one (bad request, auth failure, oversized request).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        retryable: bool = False,
        kind: str = "error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = retryable
        self.kind = kind

    @property
    def is_rate_limit(self) -> bool:
        return self.status_code == 429 or self.kind == "rate_limit"

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "kind": self.kind,
            "status_code": self.status_code,
            "retry_after": self.retry_after,
            "retryable": self.retryable,
        }


@runtime_checkable
class ChatClient(Protocol):
    """The single interface every layer implements."""

    async def complete(self, request: ChatRequest) -> ChatResponse: ...
