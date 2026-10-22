"""Test doubles: a fake retriever, a fake Redis, and recording Mistral, Scaleway and
OpenRouter transports (the last two over httpx2, which the openai SDK uses)."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import httpx2
from pydantic import SecretStr

from app.core.config import MistralConfig, OpenRouterConfig, ScalewayConfig, Settings
from app.llm.factory import LLMRouter
from app.llm.mistral import MistralClient
from app.llm.openrouter import OpenRouterClient
from app.llm.ratelimit import TokenBucket
from app.llm.scaleway import ScalewayClient
from app.retrieval.types import RetrievedChunk


class FakeRetriever:
    """Implements app.retrieval.protocol.Retriever; records every call."""

    def __init__(
        self, chunks: Sequence[RetrievedChunk] = (), error: Exception | None = None
    ) -> None:
        self.chunks = list(chunks)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def retrieve(
        self, *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {
                "dataset_ids": list(dataset_ids),
                "query": query,
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
            }
        )
        if self.error is not None:
            raise self.error
        return list(self.chunks)


class FakeRedis:
    """Implements app.core.cache.CacheClient in memory."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def set(self, name: str, value: str, ex: int) -> bool:
        self.store[name] = value
        self.ttls[name] = ex
        return True

    async def scan_iter(self, match: str, count: int) -> AsyncIterator[str]:
        for name in list(self.store):
            if fnmatch.fnmatchcase(name, match):
                yield name

    async def delete(self, *names: str) -> int:
        removed = [n for n in names if self.store.pop(n, None) is not None]
        return len(removed)

    async def aclose(self) -> None:
        return None


CONFIG = MistralConfig(
    base_url="https://api.mistral.ai",
    chat_model="mistral-large-2512",
    rewrite_model="mistral-small-2603",
    timeout_seconds=5,
)
API_KEY = "test-mistral-key"


class Recorder:
    """A mock transport that records every request and replies from a queue."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def client(self, rewrite_system: str = "Rewrite prompt.") -> MistralClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self))
        return MistralClient(CONFIG, SecretStr(API_KEY), rewrite_system, http_client=http)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def sse(*events: dict[str, Any] | str) -> httpx.Response:
    lines = []
    for event in events:
        data = event if isinstance(event, str) else json.dumps(event)
        lines.append(f"data: {data}\n\n")
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content="".join(lines).encode()
    )


def delta(text: str, usage: dict[str, int] | None = None) -> dict[str, Any]:
    chunk: dict[str, Any] = {
        "id": "cmpl-1",
        "model": CONFIG.chat_model,
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    if usage is not None:
        chunk["usage"] = usage
        chunk["choices"][0]["finish_reason"] = "stop"
    return chunk


def completion(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "cmpl-2",
            "object": "chat.completion",
            "model": CONFIG.rewrite_model,
            "created": 0,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
        },
    )


def error(status: int) -> httpx.Response:
    return httpx.Response(status, json={"message": "synthetic upstream error body"})


def _convert(reply: httpx.Response | Exception) -> httpx2.Response | Exception:
    if isinstance(reply, httpx.ReadTimeout):
        return httpx2.ReadTimeout("synthetic")
    if isinstance(reply, Exception):
        return reply
    return httpx2.Response(reply.status_code, headers=dict(reply.headers), content=reply.content)


class OpenAIRecorder:
    """Like ``Recorder``, for the openai SDK's httpx2 transport. Replies are httpx
    responses (the fixtures above) and are converted."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies: list[httpx2.Response | Exception] = [_convert(r) for r in replies]
        self.requests: list[httpx2.Request] = []

    def add(self, *replies: httpx.Response | Exception) -> None:
        self.replies.extend(_convert(r) for r in replies)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        request.read()
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def http(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self))

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def scaleway(
        self,
        config: ScalewayConfig,
        rewrite_system: str = "Rewrite prompt.",
        *,
        project_id: str | None = None,
        bucket: TokenBucket | None = None,
    ) -> ScalewayClient:
        return ScalewayClient(
            config,
            SecretStr("test-scaleway-key"),
            rewrite_system,
            project_id=project_id,
            http_client=self.http(),
            bucket=bucket or TokenBucket(1000, 10_000_000),
        )

    def openrouter(self, config: OpenRouterConfig) -> OpenRouterClient:
        return OpenRouterClient(config, SecretStr("test-openrouter-key"), http_client=self.http())


def router(
    settings: Settings,
    scaleway: OpenAIRecorder,
    openrouter: OpenAIRecorder | None = None,
    rewrite_system: str = "Rewrite.",
) -> LLMRouter:
    """The API's router over recorded transports, configured from ``settings``."""
    models = settings.models
    assert models.scaleway is not None
    external = None
    if openrouter is not None:
        assert models.openrouter is not None
        external = openrouter.openrouter(models.openrouter)
    return LLMRouter(settings, scaleway.scaleway(models.scaleway, rewrite_system), external)
