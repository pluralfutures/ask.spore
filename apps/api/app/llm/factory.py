"""LLM clients: the configured provider's (``[llm] provider``, findings M2), and the
router that sends a conversation's model choice to its provider (P1a-10).

The router is what the API's orchestrator holds. Query rewriting and the eval judge
always use the active provider's configured models (the Scaleway default); only the
answer follows the conversation's ``ModelChoice``. The OpenRouter client exists only
when ``[openrouter]`` is configured and ``OPENROUTER_API_KEY`` is set; without it, an
external model is not served (``serves`` is false and the orchestrator refuses it
before any call).

Failover (P1b-17, owner decision 2 of Oct 22, 2026; architecture §5.2 step 9): when an
EU model's answer fails to open with a 5xx, a 429 or a timeout (after the client's own
retry), ``answer_with_failover`` tries

1. the other EU provider's chat model, when ``[llm] eu_failover`` is on (every tenant);
2. then, only when the caller passes ``Failover.external``, an OpenRouter model. The
   orchestrator passes it only for a tenant whose external-models entitlement is on
   with an acceptance reference on file and whose spend cap is not reached
   (``app.chat.selection.external_failover``), so a tenant without the entitlement can
   never reach OpenRouter here. The call goes through ``OpenRouterClient``, which sets
   zero-data-retention routing on every request, and its usage is recorded under the
   OpenRouter model, so it counts against the spend cap.

An external conversation does not fail over, and nothing fails over once text has
streamed. Each failover is logged with the model and the error code only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.core.config import CatalogueEntry, Settings
from app.core.logging import log
from app.llm import catalogue
from app.llm.catalogue import ModelChoice
from app.llm.mistral import AnswerStream as MistralStream
from app.llm.mistral import (
    JudgeResult,
    LLMError,
    MistralClient,
    PromptChunk,
    RewriteResult,
    Statement,
    Turn,
    answer_max_tokens,
)
from app.llm.openrouter import OpenRouterClient
from app.llm.reasoning import reasoning_params
from app.llm.scaleway import AnswerStream as ScalewayStream
from app.llm.scaleway import ScalewayClient

LLMClient = MistralClient | ScalewayClient
AnswerStream = MistralStream | ScalewayStream
# Failures at stream open worth trying another provider for (the client's own retry on
# 5xx has run): the provider is down, overloaded or rate limited, not refusing the call.
FAILOVER_CODES: Final = frozenset({"llm_5xx", "llm_timeout", "llm_unavailable"})
FailoverKind = Literal["eu", "external"]


@dataclass(frozen=True)
class Failover:
    """What an answer may fail over to beyond the EU backup (P1b-17). ``external`` is set
    by the orchestrator only for an entitled tenant under its spend cap."""

    external: CatalogueEntry | None = None


def _fails_over(exc: LLMError) -> bool:
    return exc.error_code in FAILOVER_CODES or exc.status == 429


def create_llm_client(settings: Settings, rewrite_system: str) -> LLMClient:
    """Startup checks guarantee the active provider's section and key are present."""
    models, secrets = settings.models, settings.secrets
    if models.llm.provider == "scaleway":
        if models.scaleway is None or secrets.scaleway_api_key is None:
            raise RuntimeError("scaleway provider without config or key")  # load_settings
        return ScalewayClient(
            models.scaleway,
            secrets.scaleway_api_key,
            rewrite_system,
            project_id=secrets.scaleway_project_id,
        )
    if secrets.mistral_api_key is None:
        raise RuntimeError("mistral provider without key")  # load_settings checks it
    return MistralClient(models.mistral, secrets.mistral_api_key, rewrite_system)


def create_eu_backup(settings: Settings, rewrite_system: str) -> LLMClient | None:
    """The inactive EU provider's client, when ``[llm] eu_failover`` is on (P1b-17)."""
    models, secrets = settings.models, settings.secrets
    if not models.llm.eu_failover:
        return None
    if models.llm.provider == "scaleway":
        if secrets.mistral_api_key is None:
            raise RuntimeError("eu_failover without MISTRAL_API_KEY")  # load_settings
        return MistralClient(models.mistral, secrets.mistral_api_key, rewrite_system)
    if models.scaleway is None or secrets.scaleway_api_key is None:
        raise RuntimeError("eu_failover without scaleway config or key")  # load_settings
    return ScalewayClient(
        models.scaleway,
        secrets.scaleway_api_key,
        rewrite_system,
        project_id=secrets.scaleway_project_id,
    )


def create_llm_router(settings: Settings, rewrite_system: str) -> LLMRouter:
    openrouter = None
    config, key = settings.models.openrouter, settings.secrets.openrouter_api_key
    if config is not None and key is not None:
        openrouter = OpenRouterClient(config, key)
    return LLMRouter(
        settings,
        create_llm_client(settings, rewrite_system),
        openrouter,
        eu_backup=create_eu_backup(settings, rewrite_system),
    )


class LLMRouter:
    """The default client for rewrites and the judge; per-choice dispatch for answers."""

    def __init__(
        self,
        settings: Settings,
        default: LLMClient,
        openrouter: OpenRouterClient | None = None,
        *,
        eu_backup: LLMClient | None = None,
    ) -> None:
        self._settings = settings
        self._default = default
        self._openrouter = openrouter
        self._eu_backup = eu_backup

    @property
    def chat_model(self) -> str:
        return self._default.chat_model

    @property
    def rewrite_model(self) -> str:
        return self._default.rewrite_model

    def serves(self, model: CatalogueEntry) -> bool:
        """Whether a client for this catalogue model's provider exists in this process."""
        if model.provider == "openrouter":
            return self._openrouter is not None
        return model.provider == self._settings.models.llm.provider

    async def aclose(self) -> None:
        await self._default.aclose()
        if self._openrouter is not None:
            await self._openrouter.aclose()
        if self._eu_backup is not None:
            await self._eu_backup.aclose()

    async def rewrite(self, query: str, history: Sequence[Turn]) -> RewriteResult:
        return await self._default.rewrite(query, history)

    async def judge(
        self, system: str, passages: Sequence[PromptChunk], statements: Sequence[Statement]
    ) -> JudgeResult:
        return await self._default.judge(system, passages, statements)

    async def answer(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
        choice: ModelChoice | None = None,
    ) -> AnswerStream:
        """Stream the answer from ``choice``'s model with its reasoning switch mapped
        (``app.llm.reasoning``); the configured default call without a choice."""
        if choice is None:
            return await self._default.answer(system, context_chunks, history, question)
        model = catalogue.entry(self._settings, choice.model)
        if model is None or not self.serves(model):
            raise LLMError("model_unavailable")
        if choice.reasoning and not model.can_reason:
            raise LLMError("reasoning_unsupported")
        params = reasoning_params(model.reasoning, choice.reasoning, model.reasoning_effort_on)
        max_tokens = answer_max_tokens(choice.reasoning)
        if model.provider == "openrouter" and self._openrouter is not None:
            return await self._openrouter.answer(
                system,
                context_chunks,
                history,
                question,
                model=model.id,
                reasoning=params,
                provider_order=model.provider_order,
                provider_only=model.provider_only,
                max_tokens=max_tokens,
            )
        return await self._default.answer(
            system,
            context_chunks,
            history,
            question,
            model=model.id,
            reasoning=params,
            max_tokens=max_tokens,
        )

    async def answer_with_failover(
        self,
        system: str,
        context_chunks: Sequence[PromptChunk],
        history: Sequence[Turn],
        question: str,
        choice: ModelChoice | None = None,
        failover: Failover = Failover(),  # noqa: B008 - frozen, no mutable state
    ) -> tuple[AnswerStream, FailoverKind | None]:
        """``answer``, then the EU backup, then (only with ``failover.external``) the
        tenant's OpenRouter model, when an EU model fails to open. Returns the stream and
        which failover answered (None: the conversation's own model)."""
        try:
            return await self.answer(system, context_chunks, history, question, choice), None
        except LLMError as exc:
            model = catalogue.entry(self._settings, choice.model) if choice else None
            if (model is not None and model.external) or not _fails_over(exc):
                raise
            failure = exc
        if self._eu_backup is not None:
            log(
                "llm.failover",
                level="warning",
                model=self._eu_backup.chat_model,
                error_code=failure.error_code,
                status="eu",
            )
            try:
                stream = await self._eu_backup.answer(
                    system,
                    context_chunks,
                    history,
                    question,
                    max_tokens=answer_max_tokens(False),
                )
                return stream, "eu"
            except LLMError as exc:
                if not _fails_over(exc):
                    raise
                failure = exc
        external = failover.external
        if external is None or not external.external or self._openrouter is None:
            raise failure
        log(
            "llm.failover",
            level="warning",
            model=external.id,
            error_code=failure.error_code,
            status="external",
        )
        stream = await self._openrouter.answer(
            system,
            context_chunks,
            history,
            question,
            model=external.id,
            reasoning=reasoning_params(external.reasoning, False, external.reasoning_effort_on),
            provider_order=external.provider_order,
            provider_only=external.provider_only,
            max_tokens=answer_max_tokens(False),
        )
        return stream, "external"
