"""OpenRouter client (P1a-10): external (non-EU) models. The only module that calls
OpenRouter.

Reached only for a tenant with the operator-set external-models entitlement: the
entitlement and spend-cap checks run before (``app.chat.selection``), and the router
(``app.llm.factory.LLMRouter``) builds this client only when ``OPENROUTER_API_KEY`` is
set. Base URL, pinned slugs and timeout come from ``config/models.toml``
``[openrouter]``, validated at startup against ``allow_list.external_hosts``.

Same answer interface and guarantees as ``app.llm.scaleway`` (OpenAI-compatible, the
``openai`` SDK): the request carries only the system prompt, retrieved passages with
provenance, conversation turns and the question. In addition, every request sets
OpenRouter's provider routing to zero data retention (``provider.zdr``) and denies
providers that collect data (``provider.data_collection``), applied after a catalogue
entry's provider pin (``provider.order``, and ``provider.allow_fallbacks = false``
when the pin is exclusive) so a pin can never remove it; the request has no
``user`` field and no attribution headers, so nothing identifies a tenant, user or
workspace. No tools, no plugins (a ``:online`` slug is refused at startup). SDK
retries are off (our single retry on 5xx) and its logger is silenced; errors are
``LLMError`` with a short code only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

import httpx2
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.core.config import OpenRouterConfig
from app.core.logging import silence_library_loggers
from app.llm.mistral import (
    ANSWER_MAX_TOKENS,
    ANSWER_TEMPERATURE,
    RETRIES_ON_5XX,
    LLMError,
    PromptChunk,
    Turn,
    answer_messages,
)
from app.llm.scaleway import _ERRORS, AnswerStream, _error, _is_5xx

silence_library_loggers("openai", "httpx2")

# Zero-data-retention routing, on every request (compliance addendum, Oct 18, 2026):
# only endpoints with a ZDR policy, and never a provider that may store or train on data.
ZDR_ROUTING: Final[Mapping[str, Any]] = {"zdr": True, "data_collection": "deny"}


def provider_pin(order: Sequence[str], only: bool) -> dict[str, Any]:
    """A catalogue entry's provider pin as OpenRouter routing fields; empty without one."""
    pin: dict[str, Any] = {}
    if order:
        pin["order"] = list(order)
        if only:
            pin["allow_fallbacks"] = False
    return pin


class OpenRouterClient:
    def __init__(
        self,
        config: OpenRouterConfig,
        api_key: SecretStr,
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._owns_http = http_client is None
        self._http = http_client or httpx2.AsyncClient(follow_redirects=False)
        self._sdk = AsyncOpenAI(
            api_key=api_key.get_secret_value(),
            base_url=config.base_url,
            http_client=self._http,
            max_retries=0,  # our own single retry on 5xx, below
            timeout=config.timeout_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def answer(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
        *,
        model: str,
        reasoning: Mapping[str, Any] | None = None,
        provider_order: Sequence[str] = (),
        provider_only: bool = False,
        max_tokens: int = ANSWER_MAX_TOKENS,
    ) -> AnswerStream:
        """Open a streamed answer from a pinned slug. Retries once on a 5xx at open."""
        if model not in self._config.models:
            raise LLMError("model_unavailable")  # only pinned slugs, whoever asks
        messages = answer_messages(system, context_chunks, history, question)
        body: dict[str, Any] = {
            **(reasoning or {}),
            "provider": {**provider_pin(provider_order, provider_only), **ZDR_ROUTING},
        }
        for attempt in range(RETRIES_ON_5XX + 1):
            try:
                events = await self._sdk.chat.completions.create(  # type: ignore[call-overload]
                    model=model,
                    messages=messages,
                    temperature=ANSWER_TEMPERATURE,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=body,
                )
                return AnswerStream(events, model)
            except _ERRORS as exc:
                if _is_5xx(exc) and attempt < RETRIES_ON_5XX:
                    continue
                raise _error(exc) from None
        raise LLMError("llm_unavailable")  # unreachable; keeps mypy's return check honest
