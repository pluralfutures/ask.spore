"""Scaleway client (findings M2): the guarantees of tests/test_mistral.py, ported.

All calls are mocked at the HTTP layer (httpx2, which the openai SDK uses); no live calls.
The response fixtures are the OpenAI-shaped ones from tests.fakes.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import httpx2
import pytest
from pydantic import SecretStr

from app.core.config import ScalewayConfig
from app.llm.mistral import LLMError, PromptChunk, Statement, Turn
from app.llm.ratelimit import TokenBucket
from app.llm.scaleway import ScalewayClient, endpoint
from tests import fakes
from tests.test_mistral import _prompt_inputs, surrounding_call

__all__ = ["surrounding_call"]  # fixture reused from the Mistral tests

CONFIG = ScalewayConfig(
    base_url="https://api.scaleway.ai",
    chat_model="deepseek-v4.1-flash",
    rewrite_model="deepseek-rewrite-x",
    judge_model="deepseek-judge-x",
    timeout_seconds=5,
    rate_limit_rps=1000,
    tokens_per_minute=10_000_000,
)
API_KEY = "test-scaleway-key"
PROJECT = "0b8c5d3e-1f2a-4b6c-9d7e-8f9a0b1c2d3e"


def _convert(reply: httpx.Response | Exception) -> httpx2.Response | Exception:
    if isinstance(reply, httpx.ReadTimeout):
        return httpx2.ReadTimeout("synthetic")
    if isinstance(reply, Exception):
        return reply
    return httpx2.Response(reply.status_code, headers=dict(reply.headers), content=reply.content)


class Recorder:
    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = [_convert(r) for r in replies]
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        request.read()
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def client(
        self,
        rewrite_system: str = "Rewrite prompt.",
        project_id: str | None = None,
        bucket: TokenBucket | None = None,
    ) -> ScalewayClient:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(self))
        return ScalewayClient(
            CONFIG,
            SecretStr(API_KEY),
            rewrite_system,
            project_id=project_id,
            http_client=http,
            bucket=bucket,
        )

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


async def collect(client: ScalewayClient, **kwargs: Any) -> tuple[str, Any]:
    stream = await client.answer(
        kwargs.get("system", "System prompt."),
        kwargs.get("chunks", []),
        kwargs.get("history", []),
        kwargs.get("question", "What is the synthetic finding?"),
    )
    text = "".join([part async for part in stream])
    return text, stream.usage


def _serialised(request: httpx2.Request) -> str:
    headers = "\n".join(
        f"{k}: {v}" for k, v in request.headers.items() if k.lower() != "authorization"
    )
    return f"{request.method} {request.url}\n{headers}\n\n{request.content.decode()}"


ALLOWED_BODY_KEYS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "stream",
    "stream_options",
    "reasoning_effort",
}


# --- data minimisation ------------------------------------------------------------------


async def test_serialised_requests_contain_no_tenant_user_or_package_identifiers(
    surrounding_call: dict[str, Any],
) -> None:
    recorder = Recorder(fakes.completion("synthetic capacity 2025"), fakes.sse(fakes.delta("[1]")))
    client = recorder.client(project_id=PROJECT)
    chunks, turns = _prompt_inputs(surrounding_call)

    await client.rewrite("And in 2025?", turns)
    await collect(client, chunks=chunks, history=turns, question="And in 2025?")

    assert len(recorder.requests) == 2
    for request in recorder.requests:
        wire = _serialised(request)
        for name, value in surrounding_call["ids"].items():
            # wire includes every header, the SDK's x-stainless-* platform headers too
            assert value not in wire, f"{name} leaked into the Scaleway request"
        body = json.loads(request.content)
        assert "tools" not in body and "user" not in body and "metadata" not in body
        assert set(body) <= ALLOWED_BODY_KEYS, sorted(body)
    answer_body = recorder.bodies()[1]
    assert "Synthetic capacity grew by 12 percent" in answer_body["messages"][-1]["content"]
    assert 'publisher="Synthetic Institute"' in answer_body["messages"][-1]["content"]


async def test_judge_request_contains_only_prompt_passages_and_statements(
    surrounding_call: dict[str, Any],
) -> None:
    recorder = Recorder(fakes.completion('{"verdicts": [{"n": 1, "verdict": "supported"}]}'))
    chunks, _ = _prompt_inputs(surrounding_call)
    statements = [Statement(text="Capacity grew by 12 percent in 2025.", cites=(1,))]

    result = await recorder.client().judge("Judge prompt.", chunks, statements)

    assert result.text == '{"verdicts": [{"n": 1, "verdict": "supported"}]}'
    assert result.usage is not None and result.usage.tokens_in == 40
    (request,) = recorder.requests
    wire = _serialised(request)
    for name, value in surrounding_call["ids"].items():
        assert value not in wire, f"{name} leaked into the judge request"
    body = json.loads(request.content)
    assert set(body) <= ALLOWED_BODY_KEYS | {"response_format"}, sorted(body)
    assert body["model"] == "deepseek-judge-x"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert '<statement n="1" cites="1">' in body["messages"][1]["content"]


def test_request_types_carry_no_identifier_fields() -> None:
    assert set(PromptChunk.__dataclass_fields__) == {
        "publisher",
        "title",
        "published_on",
        "page_or_slide",
        "text",
        "untrusted",
    }
    assert set(Turn.__dataclass_fields__) == {"role", "content"}


# --- endpoint, models, streaming ----------------------------------------------------------


@pytest.mark.parametrize(
    ("project", "path"),
    [(None, "/v1/chat/completions"), (PROJECT, f"/{PROJECT}/v1/chat/completions")],
)
async def test_uses_configured_endpoint_models_and_reasoning_off(
    project: str | None, path: str
) -> None:
    recorder = Recorder(
        fakes.completion("q"),
        fakes.sse(fakes.delta("a", {"prompt_tokens": 1, "completion_tokens": 1})),
    )
    client = recorder.client(project_id=project)
    await client.rewrite("q", [])
    await collect(client)
    urls = {(r.url.scheme, r.url.host, r.url.path) for r in recorder.requests}
    assert urls == {("https", "api.scaleway.ai", path)}
    bodies = recorder.bodies()
    assert [b["model"] for b in bodies] == ["deepseek-rewrite-x", "deepseek-v4.1-flash"]
    assert {b["reasoning_effort"] for b in bodies} == {"none"}
    assert bodies[1]["stream"] is True
    assert bodies[1]["stream_options"] == {"include_usage": True}
    assert recorder.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_endpoint_form() -> None:
    assert endpoint("https://api.scaleway.ai/", None) == "https://api.scaleway.ai/v1"
    assert endpoint("https://api.scaleway.ai", PROJECT) == f"https://api.scaleway.ai/{PROJECT}/v1"


async def test_stream_is_reassembled_with_usage() -> None:
    parts = ["Synthetic ", "capacity ", "grew", " by 12%", " [1]", "."]
    events: list[dict[str, Any] | str] = [fakes.delta(p) for p in parts[:-1]]
    events.append(fakes.delta(parts[-1], {"prompt_tokens": 321, "completion_tokens": 17}))
    events.append("[DONE]")
    text, usage = await collect(Recorder(fakes.sse(*events)).client())
    assert text == "".join(parts)
    assert (usage.tokens_in, usage.tokens_out) == (321, 17)


async def test_stream_handles_multibyte_text_and_empty_deltas() -> None:
    reply = fakes.sse(fakes.delta("Énergie "), fakes.delta(""), fakes.delta("renouvelable — 12 %"))
    text, usage = await collect(Recorder(reply).client())
    assert text == "Énergie renouvelable — 12 %"
    assert usage is None


async def test_rewrite_returns_one_clean_line() -> None:
    recorder = Recorder(fakes.completion('"capacity growth Germany 2025"\nBecause...'))
    result = await recorder.client(rewrite_system="REWRITE SYS").rewrite("and Germany?", [])
    assert result.query == "capacity growth Germany 2025"
    assert recorder.bodies()[0]["messages"][0] == {"role": "system", "content": "REWRITE SYS"}


# --- errors and retry -------------------------------------------------------------------


async def test_answer_retries_once_on_5xx() -> None:
    recorder = Recorder(fakes.error(503), fakes.sse(fakes.delta("recovered")))
    text, _ = await collect(recorder.client())
    assert text == "recovered"
    assert len(recorder.requests) == 2


async def test_answer_gives_up_after_one_retry() -> None:
    recorder = Recorder(fakes.error(502), fakes.error(500))
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.client())
    assert excinfo.value.error_code == "llm_5xx"
    assert len(recorder.requests) == 2


async def test_rewrite_and_judge_retry_once_on_5xx() -> None:
    recorder = Recorder(
        fakes.error(500), fakes.completion("standalone"), fakes.error(503), fakes.completion("{}")
    )
    client = recorder.client()
    assert (await client.rewrite("q", [])).query == "standalone"
    assert (await client.judge("J.", [], [])).text == "{}"
    assert len(recorder.requests) == 4


@pytest.mark.parametrize("status", [400, 401, 429])
async def test_no_retry_on_4xx(status: int) -> None:
    recorder = Recorder(fakes.error(status))
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.client())
    assert (excinfo.value.error_code, excinfo.value.status) == ("llm_4xx", status)
    assert len(recorder.requests) == 1


async def test_timeout_is_reported_without_retry() -> None:
    recorder = Recorder(httpx.ReadTimeout("synthetic"))
    with pytest.raises(LLMError) as excinfo:
        await recorder.client().rewrite("q", [])
    assert excinfo.value.error_code == "llm_timeout"
    assert len(recorder.requests) == 1


async def test_error_never_carries_the_upstream_body() -> None:
    with pytest.raises(LLMError) as excinfo:
        await collect(Recorder(fakes.error(400)).client())
    assert str(excinfo.value) == "llm_4xx"
    assert "synthetic upstream error body" not in repr(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


async def test_sdk_logger_cannot_write_bodies(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    logging.getLogger("openai").debug("Request options: {'json_data': 'BODY-MARKER'}")
    await collect(Recorder(fakes.sse(fakes.delta("x"))).client())
    captured = capsys.readouterr()
    assert "BODY-MARKER" not in captured.out + captured.err + caplog.text


def test_timeout_and_retries_come_from_config() -> None:
    client = Recorder().client()
    assert client._sdk.timeout == 5
    assert client._sdk.max_retries == 0


# --- throttle -----------------------------------------------------------------------------


class _Bucket(TokenBucket):
    def __init__(self) -> None:
        super().__init__(1000, 10_000_000)
        self.acquired: list[int] = []
        self.settled: list[tuple[int, int]] = []

    async def acquire(self, tokens: int) -> int:
        self.acquired.append(tokens)
        return tokens

    def settle(self, reserved: int, used: int) -> None:
        self.settled.append((reserved, used))


async def test_every_call_reserves_and_settles_with_real_usage() -> None:
    bucket = _Bucket()
    recorder = Recorder(
        fakes.completion("q"),
        fakes.sse(fakes.delta("a", {"prompt_tokens": 300, "completion_tokens": 20})),
        fakes.error(400),
    )
    client = recorder.client(bucket=bucket)
    await client.rewrite("q", [])
    await collect(client)
    with pytest.raises(LLMError):
        await client.rewrite("q", [])
    assert len(bucket.acquired) == 3
    reserved = bucket.acquired
    assert bucket.settled == [(reserved[0], 48), (reserved[1], 320), (reserved[2], reserved[2])]
