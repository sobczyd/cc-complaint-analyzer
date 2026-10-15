"""The transport's ``response_format`` capability fallback.

The endpoint's refusal to honour json mode is learned once per client, because the
second send happens below the rate limiter and the recorder and is invisible to both.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:  # openai 3.x ships httpx2; older releases use httpx.
    import httpx2 as httpx
except ImportError:  # pragma: no cover - depends on the installed SDK
    import httpx

import pytest
from openai import BadRequestError
from pydantic import SecretStr

from complaint_analyzer.llm.openai_compat import OpenAICompatibleClient
from complaint_analyzer.llm.protocol import LlmError
from complaint_analyzer.settings import Credentials

from test_llm_layers import make_request
from test_transport import _Choice, _Completion

UNSUPPORTED = "Invalid value for 'response_format': this model does not support it."


def _bad_request(message: str) -> BadRequestError:
    response = httpx.Response(
        status_code=400,
        request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
    )
    return BadRequestError(message, response=response, body=None)


class _FakeCompletions:
    """Stands in for ``client.chat.completions``; records every payload sent."""

    def __init__(self, *, reject: BadRequestError | None) -> None:
        self.payloads: list[dict[str, Any]] = []
        self._reject = reject

    async def create(self, **payload: Any) -> _Completion:
        self.payloads.append(payload)
        if self._reject is not None and "response_format" in payload:
            raise self._reject
        return _Completion([_Choice('{"symptom": "x"}')])

    @property
    def calls(self) -> int:
        return len(self.payloads)

    @property
    def json_mode_calls(self) -> int:
        return sum(1 for payload in self.payloads if "response_format" in payload)


def _client(monkeypatch: pytest.MonkeyPatch, *, reject: BadRequestError | None):
    credentials = Credentials(
        base_url="https://example.invalid/v1",
        api_key=SecretStr("sk-test-secret-value"),
        model="test-model",
    )
    client = OpenAICompatibleClient(credentials)
    completions = _FakeCompletions(reject=reject)
    monkeypatch.setattr(client._client.chat, "completions", completions)
    return client, completions


async def test_a_rejected_response_format_retries_once_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, reject=_bad_request(UNSUPPORTED))

    response = await client.complete(make_request())

    assert response.content == '{"symptom": "x"}'
    assert completions.calls == 2
    assert "response_format" in completions.payloads[0]
    assert "response_format" not in completions.payloads[1]


async def test_the_capability_gap_is_learned_once_not_per_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, reject=_bad_request(UNSUPPORTED))

    await client.complete(make_request())
    await client.complete(make_request(record_id="R-002", source_row=3))

    assert completions.calls == 3
    assert completions.json_mode_calls == 1
    assert client.supports_response_format is False
    assert client.response_format_fallbacks == 1


async def test_concurrent_callers_fall_back_at_most_once_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, reject=_bad_request(UNSUPPORTED))

    await asyncio.gather(*(client.complete(make_request()) for _ in range(3)))
    await client.complete(make_request())

    assert completions.json_mode_calls <= 3
    assert "response_format" not in completions.payloads[-1]
    assert client.supports_response_format is False


async def test_an_unrelated_bad_request_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, reject=_bad_request("max_tokens is too large"))

    with pytest.raises(LlmError) as caught:
        await client.complete(make_request())

    assert caught.value.retryable is False
    assert caught.value.kind == "invalid_request"
    assert caught.value.status_code == 400
    assert completions.calls == 1
    assert client.supports_response_format is True


async def test_a_successful_call_keeps_json_mode_and_sends_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, completions = _client(monkeypatch, reject=None)

    await client.complete(make_request())
    await client.complete(make_request(record_id="R-002", source_row=3))

    assert completions.calls == 2
    assert completions.json_mode_calls == 2
    assert client.supports_response_format is True
    assert client.response_format_fallbacks == 0
