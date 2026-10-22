"""Scaleway Generative APIs client (Phase 0 provider, findings M2). The only module
that calls Scaleway.

Same interface and guarantees as ``app.llm.mistral``: the prompt types and message
builders are shared from there, so the request carries only the system prompt,
retrieved passages with provenance, conversation turns and the question (no tenant,
user or package identifiers, no tools). Base URL, model names, timeout and the
client-side throttle come from ``config/models.toml`` ``[scaleway]``, validated at
startup against the EU allow-list. ``SCALEWAY_PROJECT_ID``, if set, scopes the
endpoint to that project (``https://api.scaleway.ai/<project-id>/v1``); it is our
account's project, not a tenant identifier.

Uses the ``openai`` SDK (OpenAI-compatible endpoint, Stack Decision) with its own
retries off (our single retry on 5xx) and its logger silenced: with OPENAI_LOG=debug
it would log request bodies. Errors are ``LLMError`` with a short code only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.core.config import ScalewayConfig
from app.core.logging import silence_library_loggers
from app.llm.mistral import (
    ANSWER_MAX_TOKENS,
    ANSWER_TEMPERATURE,
    JUDGE_MAX_TOKENS,
    JUDGE_TEMPERATURE,
    RETRIES_ON_5XX,
    REWRITE_MAX_TOKENS,
    REWRITE_TEMPERATURE,
    JudgeResult,
    LLMError,
    PromptChunk,
    RewriteResult,
    Statement,
    Turn,
    Usage,
    _clean_query,
    answer_messages,
    judge_messages,
    reasoning_tokens,
    rewrite_messages,
)
from app.llm.ratelimit import TokenBucket, estimate_tokens
from app.llm.reasoning import ThinkFilter

silence_library_loggers("openai", "httpx2")


def endpoint(base_url: str, project_id: str | None) -> str:
    """``<base>/v1``, or ``<base>/<project-id>/v1`` when a project is given."""
    base = base_url.rstrip("/")
    return f"{base}/{project_id}/v1" if project_id else f"{base}/v1"


def _usage(info: Any) -> Usage | None:
    if info is None:
        return None
    return Usage(
        tokens_in=int(getattr(info, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(info, "completion_tokens", 0) or 0),
        reasoning_tokens=reasoning_tokens(info),
    )


def _total(usage: Usage | None, reserved: int) -> int:
    return reserved if usage is None else usage.tokens_in + usage.tokens_out


def _error(exc: Exception) -> LLMError:
    if isinstance(exc, openai.APIStatusError):
        code = "llm_5xx" if exc.status_code >= 500 else "llm_4xx"
        return LLMError(code, exc.status_code)
    if isinstance(exc, openai.APITimeoutError | httpx2.TimeoutException):
        return LLMError("llm_timeout")
    return LLMError("llm_unavailable")


def _is_5xx(exc: Exception) -> bool:
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


_ERRORS = (openai.APIError, httpx2.HTTPError)


class AnswerStream:
    """Async iterator of answer text deltas; ``usage`` and ``finish_reason`` are set when
    the stream ends (``"length"``: the output budget ran out).

    Shared with ``app.llm.openrouter``, which has no client-side throttle (``bucket``).
    """

    def __init__(
        self, events: Any, model: str, bucket: TokenBucket | None = None, reserved: int = 0
    ) -> None:
        self._events = events
        self.model = model
        self.usage: Usage | None = None
        self.finish_reason: str | None = None
        self._bucket = bucket
        self._reserved = reserved

    def __aiter__(self) -> AsyncIterator[str]:
        return self._deltas()

    async def _deltas(self) -> AsyncIterator[str]:
        # Reasoning is never passed on (P1a-11): only ``delta.content`` is read, so
        # ``reasoning_content`` (Scaleway), ``reasoning`` and ``reasoning_details``
        # (OpenRouter) are dropped here, and inline ``<think>`` blocks are filtered out.
        thinking = ThinkFilter()
        try:
            async with self._events as events:
                async for chunk in events:
                    if chunk.usage is not None:
                        self.usage = _usage(chunk.usage)
                    for choice in chunk.choices:
                        if choice.finish_reason:
                            self.finish_reason = choice.finish_reason
                        delta = choice.delta.content if choice.delta else None
                        text = thinking.feed(delta) if delta else ""
                        if text:
                            yield text
            tail = thinking.flush()
            if tail:
                yield tail
        except _ERRORS as exc:
            # Mid-stream failure: tokens may already be with the user, so no retry.
            raise _error(exc) from None
        finally:
            if self._bucket is not None:
                self._bucket.settle(self._reserved, _total(self.usage, self._reserved))


class ScalewayClient:
    def __init__(
        self,
        config: ScalewayConfig,
        api_key: SecretStr,
        rewrite_system: str,
        *,
        project_id: str | None = None,
        http_client: httpx2.AsyncClient | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._config = config
        self._rewrite_system = rewrite_system
        self._owns_http = http_client is None
        self._http = http_client or httpx2.AsyncClient(follow_redirects=False)
        self._bucket = bucket or TokenBucket(config.rate_limit_rps, config.tokens_per_minute)
        self._sdk = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            base_url=endpoint(config.base_url, project_id),
            http_client=self._http,
            max_retries=0,  # our own single retry on 5xx, below
            timeout=config.timeout_seconds,
        )

    @property
    def chat_model(self) -> str:
        return self._config.chat_model

    @property
    def rewrite_model(self) -> str:
        return self._config.rewrite_model

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: str,
        **extra: Any,
    ) -> Any:
        reserved = await self._bucket.acquire(
            estimate_tokens([m["content"] for m in messages], max_tokens)
        )
        response = None
        try:
            for attempt in range(RETRIES_ON_5XX + 1):
                try:
                    response = await self._sdk.chat.completions.create(  # type: ignore[call-overload]
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        reasoning_effort=reasoning_effort,
                        stream=False,
                        **extra,
                    )
                    return response
                except _ERRORS as exc:
                    if _is_5xx(exc) and attempt < RETRIES_ON_5XX:
                        continue
                    raise _error(exc) from None
            raise LLMError("llm_unavailable")  # unreachable; keeps mypy's return check honest
        finally:
            usage = _usage(getattr(response, "usage", None))
            self._bucket.settle(reserved, _total(usage, reserved))

    async def rewrite(self, query: str, history: Sequence[Turn]) -> RewriteResult:
        """One standalone search query from the latest turn plus recent history."""
        response = await self._complete(
            rewrite_messages(self._rewrite_system, query, history),
            self._config.rewrite_model,
            REWRITE_TEMPERATURE,
            REWRITE_MAX_TOKENS,
            self._config.reasoning_effort,
        )
        message = response.choices[0].message if response.choices else None
        raw = (message.content or "") if message is not None else ""
        return RewriteResult(query=_clean_query(raw, query), usage=_usage(response.usage))

    async def judge(
        self,
        system: str,
        passages: Sequence[PromptChunk],
        statements: Sequence[Statement],
        *,
        model: str | None = None,
        reasoning_effort: str = "none",
    ) -> JudgeResult:
        """Faithfulness verdicts for ``statements`` (eval harness, P0-18), as JSON text.

        ``model`` is ``[eval] judge_model`` (P1b-15 c); the chat model without it."""
        response = await self._complete(
            judge_messages(system, passages, statements),
            model or self._config.chat_model,
            JUDGE_TEMPERATURE,
            JUDGE_MAX_TOKENS,
            reasoning_effort,
            response_format={"type": "json_object"},
        )
        message = response.choices[0].message if response.choices else None
        raw = (message.content or "") if message is not None else ""
        return JudgeResult(text=raw, usage=_usage(response.usage))

    async def answer(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
        *,
        model: str | None = None,
        reasoning: Mapping[str, Any] | None = None,
        max_tokens: int = ANSWER_MAX_TOKENS,
    ) -> AnswerStream:
        """Open a streamed answer. Retries once if the stream fails to open with a 5xx.

        ``model``, ``reasoning`` and ``max_tokens`` come from the conversation's model
        choice (``app.llm.factory.LLMRouter``, P1a-10, P1a-11): a pinned Scaleway model,
        the request fields of its reasoning switch (``app.llm.reasoning``) and the output
        budget for that switch. Without them the configured ``chat_model`` and
        ``reasoning_effort`` are used, as in Phase 0.
        """
        messages = answer_messages(system, context_chunks, history, question)
        model = model or self._config.chat_model
        params = (
            {"reasoning_effort": self._config.reasoning_effort}
            if reasoning is None
            else dict(reasoning)
        )
        reserved = await self._bucket.acquire(
            estimate_tokens([m["content"] for m in messages], max_tokens)
        )
        for attempt in range(RETRIES_ON_5XX + 1):
            try:
                events = await self._sdk.chat.completions.create(  # type: ignore[call-overload]
                    model=model,
                    messages=messages,
                    temperature=ANSWER_TEMPERATURE,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=params or None,
                )
                return AnswerStream(events, model, self._bucket, reserved)
            except _ERRORS as exc:
                if _is_5xx(exc) and attempt < RETRIES_ON_5XX:
                    continue
                self._bucket.settle(reserved, reserved)
                raise _error(exc) from None
        raise LLMError("llm_unavailable")  # unreachable; keeps mypy's return check honest
