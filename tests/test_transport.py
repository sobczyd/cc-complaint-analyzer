"""The OpenAI-compatible transport's response shaping and error translation.

The network path itself is not exercised here; what matters is that every SDK failure
becomes an ``LlmError`` the retry layer can reason about.
"""

from __future__ import annotations

try:  # openai 3.x ships httpx2; older releases use httpx.
    import httpx2 as httpx
except ImportError:  # pragma: no cover - depends on the installed SDK
    import httpx

import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

from complaint_analyzer.llm.openai_compat import OpenAICompatibleClient, _retry_after
from complaint_analyzer.llm.protocol import LlmError

from test_llm_layers import make_request

translate = OpenAICompatibleClient._translate


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
    )


def _status_error(cls, status: int, headers: dict[str, str] | None = None):
    return cls("boom", response=_response(status, headers), body=None)


def test_rate_limit_is_retryable_and_carries_retry_after() -> None:
    error = translate(_status_error(RateLimitError, 429, {"retry-after": "12"}))
    assert error.retryable is True
    assert error.is_rate_limit is True
    assert error.retry_after == 12.0


def test_timeout_and_connection_failures_are_retryable() -> None:
    request = httpx.Request("POST", "https://example.invalid/v1")
    assert translate(APITimeoutError(request=request)).retryable is True
    assert translate(APIConnectionError(request=request)).retryable is True


@pytest.mark.parametrize("cls,status", [(AuthenticationError, 401), (NotFoundError, 404)])
def test_client_errors_are_not_retried(cls, status: int) -> None:
    error = translate(_status_error(cls, status))
    assert error.retryable is False
    assert error.status_code == status


def test_bad_request_is_not_retried() -> None:
    assert translate(_status_error(BadRequestError, 400)).kind == "invalid_request"


@pytest.mark.parametrize("status,retryable", [(500, True), (503, True), (418, False)])
def test_other_http_statuses_follow_the_retryable_table(status: int, retryable: bool) -> None:
    assert translate(_status_error(APIStatusError, status)).retryable is retryable


def test_unexpected_exceptions_are_wrapped_and_not_retried() -> None:
    error = translate(ValueError("something odd"))
    assert error.retryable is False
    assert "ValueError" in str(error)


def test_an_llm_error_passes_through_unchanged() -> None:
    original = LlmError("already translated", retryable=True)
    assert translate(original) is original


def test_retry_after_ignores_unparseable_headers() -> None:
    assert _retry_after(_status_error(RateLimitError, 429, {"retry-after": "soon"})) is None
    assert _retry_after(_status_error(RateLimitError, 429)) is None
    assert _retry_after(_status_error(RateLimitError, 429, {"retry-after": "1.5s"})) == 1.5


class _Message:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.message = _Message(content)


class _Usage:
    prompt_tokens = 11
    completion_tokens = 22


class _Completion:
    def __init__(self, choices, *, model="served-model", usage=_Usage()) -> None:
        self.choices = choices
        self.model = model
        self.usage = usage

    def model_dump(self) -> dict:
        return {"model": self.model}


def test_response_carries_content_model_and_usage() -> None:
    response = OpenAICompatibleClient._to_response(
        _Completion([_Choice('{"symptom": "x"}')]), make_request()
    )
    assert response.content == '{"symptom": "x"}'
    assert response.model == "served-model"
    assert response.total_tokens == 33
    assert response.raw == {"model": "served-model"}


def test_missing_usage_leaves_tokens_unknown() -> None:
    response = OpenAICompatibleClient._to_response(
        _Completion([_Choice("{}")], usage=None), make_request()
    )
    assert response.total_tokens is None


def test_empty_content_is_preserved_rather_than_guessed() -> None:
    assert OpenAICompatibleClient._to_response(
        _Completion([_Choice(None)]), make_request()
    ).content == ""


def test_a_reply_with_no_choices_is_retryable() -> None:
    with pytest.raises(LlmError) as caught:
        OpenAICompatibleClient._to_response(_Completion([]), make_request())
    assert caught.value.retryable is True
