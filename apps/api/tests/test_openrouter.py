"""P1a-10: OpenRouter client, the LLM router and the reasoning mapping per switch kind.

All calls are mocked at the HTTP layer (httpx2); no live calls. The serialised-request
test is the control the compliance addendum names: zero-data-retention routing on every
request and no tenant, user or workspace identifier anywhere on the wire.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Any

import httpx
import pytest

from app.core.config import OpenRouterConfig, Settings
from app.llm.catalogue import ModelChoice
from app.llm.factory import LLMRouter, create_llm_router
from app.llm.mistral import LLMError
from app.llm.openrouter import OpenRouterClient
from app.llm.reasoning import reasoning_params
from tests import fakes
from tests.fakes import OpenAIRecorder, router
from tests.test_mistral import _prompt_inputs, surrounding_call
from tests.test_scaleway import _serialised

__all__ = ["surrounding_call"]  # fixture reused from the Mistral tests

CLAUDE = "anthropic/claude-opus-5.5"
GPT = "openai/gpt-6.1-sol"
CONFIG = OpenRouterConfig(
    base_url="https://eu.openrouter.ai/api/v1", models=(GPT, CLAUDE), timeout_seconds=5
)
# Everything an OpenRouter answer request may carry; nothing else.
ALLOWED_BODY_KEYS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "stream",
    "stream_options",
    "reasoning",
    "provider",
}


async def collect(client: OpenRouterClient | LLMRouter, **kwargs: Any) -> str:
    stream = await client.answer(  # type: ignore[call-arg]
        "System prompt.",
        kwargs.pop("chunks", []),
        kwargs.pop("history", []),
        "What is the synthetic finding?",
        **kwargs,
    )
    return "".join([part async for part in stream])


# --- data minimisation and ZDR --------------------------------------------------------


@pytest.mark.parametrize("on", [True, False])
async def test_serialised_request_carries_zdr_and_no_identifiers(
    surrounding_call: dict[str, Any], on: bool
) -> None:
    ids = {**surrounding_call["ids"], "workspace_id": str(uuid.uuid4())}
    recorder = OpenAIRecorder(
        fakes.sse(
            fakes.delta("Grew [1]."), fakes.delta("", {"prompt_tokens": 9, "completion_tokens": 3})
        )
    )
    client = recorder.openrouter(CONFIG)
    chunks, turns = _prompt_inputs(surrounding_call)

    await collect(
        client,
        chunks=chunks,
        history=turns,
        model=CLAUDE,
        reasoning=reasoning_params("effort", on),
    )

    [request] = recorder.requests
    assert str(request.url) == "https://eu.openrouter.ai/api/v1/chat/completions"
    wire = _serialised(request)
    for name, value in ids.items():
        assert value not in wire, f"{name} leaked into the OpenRouter request"
    for header in ("http-referer", "x-title"):
        assert header not in {k.lower() for k in request.headers}
    body = json.loads(request.content)
    assert set(body) <= ALLOWED_BODY_KEYS, sorted(body)
    assert "tools" not in body and "user" not in body and "plugins" not in body
    assert body["provider"] == {"zdr": True, "data_collection": "deny"}
    assert body["model"] == CLAUDE
    assert body["reasoning"] == {"effort": "medium" if on else "none", "exclude": True}
    assert 'publisher="Synthetic Institute"' in body["messages"][-1]["content"]


async def test_zdr_cannot_be_overridden_by_reasoning_fields() -> None:
    recorder = OpenAIRecorder(fakes.sse(fakes.delta("Ok.")))
    await collect(
        recorder.openrouter(CONFIG),
        model=CLAUDE,
        reasoning={"provider": {"zdr": False}, "reasoning": {"effort": "none"}},
    )
    assert recorder.bodies()[0]["provider"] == {"zdr": True, "data_collection": "deny"}


# --- provider pins (owner, Oct 19, 2026) ------------------------------------------------


@pytest.mark.parametrize(("model", "provider"), [(CLAUDE, "amazon-bedrock"), (GPT, "azure")])
async def test_pinned_model_request_carries_the_pin_zdr_and_no_identifiers(
    settings: Settings, surrounding_call: dict[str, Any], model: str, provider: str
) -> None:
    ids = {**surrounding_call["ids"], "workspace_id": str(uuid.uuid4())}
    openrouter = OpenAIRecorder(fakes.sse(fakes.delta("Grew [1].")))
    chunks, turns = _prompt_inputs(surrounding_call)

    await collect(
        router(settings, OpenAIRecorder(), openrouter),
        chunks=chunks,
        history=turns,
        choice=ModelChoice(model, True),
    )

    [request] = openrouter.requests
    body = json.loads(request.content)
    assert body["model"] == model
    assert body["provider"] == {
        "order": [provider],
        "allow_fallbacks": False,
        "zdr": True,
        "data_collection": "deny",
    }
    assert set(body) <= ALLOWED_BODY_KEYS, sorted(body)
    wire = _serialised(request)
    for name, value in ids.items():
        assert value not in wire, f"{name} leaked into the OpenRouter request"


async def test_entry_without_a_pin_sends_no_order_and_no_fallback_key(settings: Settings) -> None:
    unpinned = [
        e.model_copy(update={"provider_order": (), "provider_only": False})
        for e in settings.models.catalogue
    ]
    models = settings.models.model_copy(update={"catalogue": tuple(unpinned)})
    openrouter = OpenAIRecorder(fakes.sse(fakes.delta("Ok.")))
    llm = router(dataclasses.replace(settings, models=models), OpenAIRecorder(), openrouter)

    await collect(llm, choice=ModelChoice(CLAUDE, False))

    assert openrouter.bodies()[0]["provider"] == {"zdr": True, "data_collection": "deny"}


async def test_unpinned_slug_is_refused_without_a_call() -> None:
    recorder = OpenAIRecorder()
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.openrouter(CONFIG), model="anthropic/claude-opus-5.5:online")
    assert excinfo.value.error_code == "model_unavailable"
    assert recorder.requests == []


# --- timeouts and retries -------------------------------------------------------------


async def test_retries_once_on_5xx_then_streams() -> None:
    recorder = OpenAIRecorder(fakes.error(502), fakes.sse(fakes.delta("Grew [1].")))
    assert await collect(recorder.openrouter(CONFIG), model=GPT) == "Grew [1]."
    assert len(recorder.requests) == 2


async def test_second_5xx_is_an_error_code_without_body() -> None:
    recorder = OpenAIRecorder(fakes.error(503), fakes.error(503))
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.openrouter(CONFIG), model=GPT)
    assert (excinfo.value.error_code, excinfo.value.status) == ("llm_5xx", 503)
    assert "synthetic upstream error body" not in str(excinfo.value)
    assert len(recorder.requests) == 2


async def test_4xx_is_not_retried() -> None:
    recorder = OpenAIRecorder(fakes.error(402))
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.openrouter(CONFIG), model=GPT)
    assert excinfo.value.error_code == "llm_4xx"
    assert len(recorder.requests) == 1


async def test_timeout_is_reported_as_a_code() -> None:
    recorder = OpenAIRecorder(httpx.ReadTimeout("synthetic"))
    with pytest.raises(LLMError) as excinfo:
        await collect(recorder.openrouter(CONFIG), model=GPT)
    assert excinfo.value.error_code == "llm_timeout"


def test_timeout_comes_from_config() -> None:
    client = OpenAIRecorder().openrouter(CONFIG)
    assert client._sdk.timeout == CONFIG.timeout_seconds
    assert client._sdk.max_retries == 0


# --- the reasoning parameter, mapped per switch kind ------------------------------------


def test_reasoning_params_per_kind() -> None:
    assert reasoning_params("thinking", True) == {"reasoning_effort": "medium"}
    assert reasoning_params("thinking", False) == {"reasoning_effort": "none"}
    assert reasoning_params("effort", True) == {"reasoning": {"effort": "medium", "exclude": True}}
    assert reasoning_params("effort", False) == {"reasoning": {"effort": "none", "exclude": True}}
    assert reasoning_params("none", False) == {}
    with pytest.raises(ValueError, match="no reasoning switch"):
        reasoning_params("none", True)


@pytest.mark.parametrize(
    ("model", "on", "provider", "fields"),
    [
        ("deepseek-v4.1-flash", False, "scaleway", {"reasoning_effort": "none"}),
        ("deepseek-v4.1-flash", True, "scaleway", {"reasoning_effort": "medium"}),
        ("qwen3.8-27b", False, "scaleway", {"reasoning_effort": "none"}),
        ("qwen3.8-27b", True, "scaleway", {"reasoning_effort": "medium"}),
        (GPT, True, "openrouter", {"reasoning": {"effort": "medium", "exclude": True}}),
        (GPT, False, "openrouter", {"reasoning": {"effort": "none", "exclude": True}}),
        (CLAUDE, True, "openrouter", {"reasoning": {"effort": "medium", "exclude": True}}),
        (CLAUDE, False, "openrouter", {"reasoning": {"effort": "none", "exclude": True}}),
    ],
)
async def test_router_maps_the_reasoning_switch_per_model_kind(
    settings: Settings, model: str, on: bool, provider: str, fields: dict[str, Any]
) -> None:
    scaleway, openrouter = OpenAIRecorder(), OpenAIRecorder()
    (scaleway if provider == "scaleway" else openrouter).add(fakes.sse(fakes.delta("Ok.")))
    llm = router(settings, scaleway, openrouter)

    await collect(llm, choice=ModelChoice(model, on))

    recorder = scaleway if provider == "scaleway" else openrouter
    [body] = recorder.bodies()
    assert body["model"] == model
    switch_keys = {"reasoning_effort", "reasoning"}
    assert {k: v for k, v in body.items() if k in switch_keys} == fields
    other = openrouter if provider == "scaleway" else scaleway
    assert other.requests == []


async def test_router_without_a_choice_uses_the_configured_default(settings: Settings) -> None:
    scaleway = OpenAIRecorder(fakes.sse(fakes.delta("Ok.")))
    await collect(router(settings, scaleway))
    [body] = scaleway.bodies()
    assert body["model"] == "deepseek-v4.1-flash"
    assert body["reasoning_effort"] == "none"


async def test_router_refuses_external_without_an_openrouter_client(settings: Settings) -> None:
    scaleway = OpenAIRecorder()
    llm = router(settings, scaleway)  # no OPENROUTER_API_KEY: no client
    claude = next(e for e in settings.models.catalogue if e.id == CLAUDE)
    assert not llm.serves(claude)
    with pytest.raises(LLMError) as excinfo:
        await collect(llm, choice=ModelChoice(CLAUDE, False))
    assert excinfo.value.error_code == "model_unavailable"
    assert scaleway.requests == []


async def test_factory_builds_openrouter_only_with_its_key(settings: Settings) -> None:
    from dataclasses import replace

    from pydantic import SecretStr

    claude = next(e for e in settings.models.catalogue if e.id == CLAUDE)
    without = create_llm_router(settings, "Rewrite.")
    assert not without.serves(claude)
    keyed = replace(settings, secrets=replace(settings.secrets, openrouter_api_key=SecretStr("k")))
    with_key = create_llm_router(keyed, "Rewrite.")
    assert with_key.serves(claude)
    await without.aclose()
    await with_key.aclose()
