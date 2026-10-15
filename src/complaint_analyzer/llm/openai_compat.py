"""The OpenAI-compatible transport. The only module that imports the provider SDK.

Everything above this layer speaks ``ChatRequest``/``ChatResponse`` and never sees an
SDK type, so swapping providers means writing one more module like this one.
"""

from __future__ import annotations

from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from ..settings import Credentials
from .protocol import ChatRequest, ChatResponse, LlmError

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _retry_after(exc: Any) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    for name in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(str(raw).strip().rstrip("s"))
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


class OpenAICompatibleClient:
    """Calls a chat-completions endpoint and normalizes its failures."""

    def __init__(self, credentials: Credentials, *, timeout: float = 120.0) -> None:
        self._client = AsyncOpenAI(
            base_url=credentials.base_url,
            api_key=credentials.api_key.get_secret_value(),
            timeout=timeout,
            max_retries=0,  # Retrying is the retry layer's job, not the SDK's.
        )
        self._json_mode = True
        self.response_format_fallbacks = 0

    @property
    def supports_response_format(self) -> bool:
        """False once the endpoint has rejected ``response_format``."""
        return self._json_mode

    async def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [message.as_dict() for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(request.extra)

        try:
            completion = await self._client.chat.completions.create(**payload)
        except BadRequestError as exc:
            # A rejected response_format is a capability gap, not a bad request we
            # should give up on; retry once without it. The gap is remembered on the
            # instance so later requests never ask for json mode. Requests already in
            # flight may each reach this branch before the flag is read; the write is
            # idempotent, so the cost is one extra send per concurrent request once per
            # run rather than one per record.
            if "response_format" not in payload or "response_format" not in str(exc):
                raise self._translate(exc) from exc
            self._json_mode = False
            self.response_format_fallbacks += 1
            payload.pop("response_format", None)
            try:
                completion = await self._client.chat.completions.create(**payload)
            except Exception as retry_exc:
                raise self._translate(retry_exc) from retry_exc
        except Exception as exc:
            raise self._translate(exc) from exc

        return self._to_response(completion, request)

    async def aclose(self) -> None:
        await self._client.close()

    @staticmethod
    def _to_response(completion: Any, request: ChatRequest) -> ChatResponse:
        choices = getattr(completion, "choices", None) or []
        if not choices:
            raise LlmError("model returned no choices", retryable=True, kind="empty_response")

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) or ""
        usage = getattr(completion, "usage", None)

        return ChatResponse(
            content=content,
            model=getattr(completion, "model", None) or request.model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            raw=_dump(completion),
        )

    @staticmethod
    def _translate(exc: Exception) -> LlmError:
        if isinstance(exc, LlmError):
            return exc
        if isinstance(exc, RateLimitError):
            return LlmError(
                str(exc),
                status_code=429,
                retry_after=_retry_after(exc),
                retryable=True,
                kind="rate_limit",
            )
        if isinstance(exc, APITimeoutError):
            return LlmError(str(exc), retryable=True, kind="timeout")
        if isinstance(exc, APIConnectionError):
            return LlmError(str(exc), retryable=True, kind="connection")
        if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
            return LlmError(
                str(exc),
                status_code=getattr(exc, "status_code", None),
                retryable=False,
                kind="auth",
            )
        if isinstance(exc, (BadRequestError, NotFoundError)):
            return LlmError(
                str(exc),
                status_code=getattr(exc, "status_code", None),
                retryable=False,
                kind="invalid_request",
            )
        if isinstance(exc, APIStatusError):
            status = getattr(exc, "status_code", None)
            return LlmError(
                str(exc),
                status_code=status,
                retry_after=_retry_after(exc),
                retryable=status in RETRYABLE_STATUS,
                kind="http_error",
            )
        return LlmError(f"{type(exc).__name__}: {exc}", retryable=False, kind="unexpected")


def _dump(completion: Any) -> Any:
    for method in ("model_dump", "to_dict", "dict"):
        dumper = getattr(completion, method, None)
        if callable(dumper):
            try:
                return dumper()
            except Exception:  # pragma: no cover - defensive, SDK shape varies
                continue
    return None
