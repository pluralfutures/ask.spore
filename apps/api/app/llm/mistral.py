"""Mistral client (P0-13). The only module that calls Mistral.

Base URL and dated model names come from ``config/models.toml`` (validated at
startup against the EU allow-list); nothing here names a host or a model.

Data minimisation at the model boundary (CLAUDE.md, compliance guide): the types
this module accepts can only carry what a prompt may contain — the system prompt,
retrieved passages with provenance (publisher, title, date, page), conversation
turns and the question. There is no parameter through which a tenant, user,
conversation or package identifier could reach the request, and no tools are sent.

Errors are reported as ``LLMError`` with a short code; the SDK's own error
message embeds the response body and must never be logged.
"""

from __future__ import annotations

import html
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import httpx
from mistralai.client import Mistral
from mistralai.client.errors import MistralError
from mistralai.client.utils.logger import NoOpLogger
from pydantic import SecretStr

from app.core.config import MistralConfig

Role = Literal["user", "assistant"]

ANSWER_TEMPERATURE = 0.2
ANSWER_MAX_TOKENS = 1500
REWRITE_TEMPERATURE = 0.0
REWRITE_MAX_TOKENS = 128
MAX_REWRITE_LENGTH = 500
RETRIES_ON_5XX = 1


class LLMError(RuntimeError):
    """A Mistral call failed. ``error_code`` is safe to log; the cause is not."""

    def __init__(self, error_code: str, status: int | None = None) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.status = status


@dataclass(frozen=True)
class Turn:
    role: Role
    content: str


@dataclass(frozen=True)
class PromptChunk:
    """One retrieved passage as the model sees it: provenance and text, no IDs."""

    publisher: str
    title: str
    published_on: date | None
    page_or_slide: int | None
    text: str
    untrusted: bool  # crawled web text (CLAUDE.md: wrapped as untrusted input)


@dataclass(frozen=True)
class Usage:
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class RewriteResult:
    query: str
    usage: Usage | None


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def render_context(chunks: Sequence[PromptChunk]) -> str:
    """The numbered context block. Passage ``n`` is cited as ``[n]``.

    Text and attributes are escaped, so a passage cannot close its own element or
    forge another passage.
    """
    passages = []
    for n, chunk in enumerate(chunks, start=1):
        attrs = [
            f'n="{n}"',
            f'publisher="{_attr(chunk.publisher)}"',
            f'title="{_attr(chunk.title)}"',
            f'date="{chunk.published_on.isoformat() if chunk.published_on else "unknown"}"',
        ]
        if chunk.page_or_slide is not None:
            attrs.append(f'page="{chunk.page_or_slide}"')
        if chunk.untrusted:
            attrs.append('trust="untrusted"')
        passages.append(
            f"<passage {' '.join(attrs)}>\n{html.escape(chunk.text, quote=False)}\n</passage>"
        )
    return "<context>\n" + "\n".join(passages) + "\n</context>"


def answer_messages(
    system: str, context_chunks: Sequence[PromptChunk], history: Sequence[Turn], question: str
) -> list[dict[str, str]]:
    """System prompt, earlier turns, then context plus question as the last user turn."""
    final = f"{render_context(context_chunks)}\n\n<question>\n{question}\n</question>"
    return [
        {"role": "system", "content": system},
        *({"role": turn.role, "content": turn.content} for turn in history),
        {"role": "user", "content": final},
    ]


def rewrite_messages(system: str, query: str, history: Sequence[Turn]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        *({"role": turn.role, "content": turn.content} for turn in history),
        {"role": "user", "content": query},
    ]


def _clean_query(raw: str, fallback: str) -> str:
    line = next((part.strip() for part in raw.strip().splitlines() if part.strip()), "")
    line = line.strip("\"'` ")
    return line[:MAX_REWRITE_LENGTH] if line else fallback


def _text(content: Any) -> str:
    """Delta or message content: a string, or a list of typed chunks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(getattr(part, "text", "") or "") for part in content)
    return ""


def _usage(info: Any) -> Usage | None:
    if info is None:
        return None
    return Usage(
        tokens_in=int(getattr(info, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(info, "completion_tokens", 0) or 0),
    )


def _error(exc: Exception) -> LLMError:
    if isinstance(exc, MistralError):
        code = "llm_5xx" if exc.status_code >= 500 else "llm_4xx"
        return LLMError(code, exc.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("llm_timeout")
    return LLMError("llm_unavailable")


def _is_5xx(exc: Exception) -> bool:
    return isinstance(exc, MistralError) and exc.status_code >= 500


class AnswerStream:
    """Async iterator of answer text deltas; ``usage`` is set when the stream ends."""

    def __init__(self, events: Any, model: str) -> None:
        self._events = events
        self.model = model
        self.usage: Usage | None = None

    def __aiter__(self) -> AsyncIterator[str]:
        return self._deltas()

    async def _deltas(self) -> AsyncIterator[str]:
        try:
            async with self._events as events:
                async for event in events:
                    chunk = event.data
                    if chunk.usage is not None:
                        self.usage = _usage(chunk.usage)
                    for choice in chunk.choices:
                        delta = _text(choice.delta.content)
                        if delta:
                            yield delta
        except (MistralError, httpx.HTTPError) as exc:
            # Mid-stream failure: tokens may already be with the user, so no retry.
            raise _error(exc) from None


class MistralClient:
    def __init__(
        self,
        config: MistralConfig,
        api_key: SecretStr,
        rewrite_system: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._rewrite_system = rewrite_system
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(follow_redirects=False)
        self._sdk = Mistral(
            api_key=api_key.get_secret_value(),
            server_url=config.base_url,
            async_client=self._http,
            retry_config=None,  # our own single retry on 5xx, below
            timeout_ms=int(config.timeout_seconds * 1000),
            # Explicit: the SDK default logs request bodies when MISTRAL_DEBUG is set.
            debug_logger=NoOpLogger(),
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

    async def rewrite(self, query: str, history: Sequence[Turn]) -> RewriteResult:
        """One standalone search query from the latest turn plus recent history."""
        messages = rewrite_messages(self._rewrite_system, query, history)
        for attempt in range(RETRIES_ON_5XX + 1):
            try:
                response = await self._sdk.chat.complete_async(
                    model=self._config.rewrite_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=REWRITE_TEMPERATURE,
                    max_tokens=REWRITE_MAX_TOKENS,
                    stream=False,
                )
                break
            except (MistralError, httpx.HTTPError) as exc:
                if _is_5xx(exc) and attempt < RETRIES_ON_5XX:
                    continue
                raise _error(exc) from None
        message = response.choices[0].message if response.choices else None
        raw = _text(message.content) if message is not None else ""
        return RewriteResult(query=_clean_query(raw, query), usage=_usage(response.usage))

    async def answer(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
    ) -> AnswerStream:
        """Open a streamed answer. Retries once if the stream fails to open with a 5xx."""
        messages = answer_messages(system, context_chunks, history, question)
        for attempt in range(RETRIES_ON_5XX + 1):
            try:
                events = await self._sdk.chat.stream_async(
                    model=self._config.chat_model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=ANSWER_TEMPERATURE,
                    max_tokens=ANSWER_MAX_TOKENS,
                )
                return AnswerStream(events, self._config.chat_model)
            except (MistralError, httpx.HTTPError) as exc:
                if _is_5xx(exc) and attempt < RETRIES_ON_5XX:
                    continue
                raise _error(exc) from None
        raise LLMError("llm_unavailable")  # unreachable; keeps mypy's return check honest
