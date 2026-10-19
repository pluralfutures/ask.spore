"""LLM clients: the configured provider's (``[llm] provider``, findings M2), and the
router that sends a conversation's model choice to its provider (P1a-10).

The router is what the API's orchestrator holds. Query rewriting and the eval judge
always use the active provider's configured models (the Scaleway default); only the
answer follows the conversation's ``ModelChoice``. The OpenRouter client exists only
when ``[openrouter]`` is configured and ``OPENROUTER_API_KEY`` is set; without it, an
external model is not served (``serves`` is false and the orchestrator refuses it
before any call).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.config import CatalogueEntry, Settings
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
)
from app.llm.openrouter import OpenRouterClient
from app.llm.reasoning import reasoning_params
from app.llm.scaleway import AnswerStream as ScalewayStream
from app.llm.scaleway import ScalewayClient

LLMClient = MistralClient | ScalewayClient
AnswerStream = MistralStream | ScalewayStream


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


def create_llm_router(settings: Settings, rewrite_system: str) -> LLMRouter:
    openrouter = None
    config, key = settings.models.openrouter, settings.secrets.openrouter_api_key
    if config is not None and key is not None:
        openrouter = OpenRouterClient(config, key)
    return LLMRouter(settings, create_llm_client(settings, rewrite_system), openrouter)


class LLMRouter:
    """The default client for rewrites and the judge; per-choice dispatch for answers."""

    def __init__(
        self,
        settings: Settings,
        default: LLMClient,
        openrouter: OpenRouterClient | None = None,
    ) -> None:
        self._settings = settings
        self._default = default
        self._openrouter = openrouter

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
        if choice.reasoning and model.reasoning == "none":
            raise LLMError("reasoning_unsupported")
        params = reasoning_params(model.reasoning, choice.reasoning)
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
            )
        return await self._default.answer(
            system, context_chunks, history, question, model=model.id, reasoning=params
        )
