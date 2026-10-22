"""P1b-17 (owner decision 2 of Oct 22, 2026): failover when the EU provider is down.

Every tenant keeps the EU-only fallback (the other EU provider, ``[llm] eu_failover``);
only a tenant with the external-models entitlement (acceptance on file, spend cap set
and not reached) may fail over to OpenRouter, with zero-data-retention routing and its
usage counted against the cap. Against PostgreSQL with recorded (mocked) transports."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import DoneEvent, ErrorEvent, Orchestrator
from app.core.config import DEFAULT_CONFIG_DIR, ConfigError, Settings, load_settings
from app.core.db import session_factory
from app.llm.catalogue import ModelChoice
from app.llm.factory import LLMRouter
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import USAGE, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, OpenAIRecorder, delta, error, sse
from tests.test_config import ENV
from tests.test_model_catalogue import CLAUDE, DEEPSEEK, fixed_choice, internal_entitlement
from tests.test_spend_cap import expected_cents, ledger

__all__ = ["internal_entitlement", "ledger"]  # fixtures reused

DOWN = (error(503), error(503))
EU_CHOICE = ModelChoice(DEEPSEEK, False)
EXTERNAL_CHOICE = ModelChoice(CLAUDE, False)  # the client's own retry on 5xx, then the failure


def orchestrator(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    scaleway: OpenAIRecorder,
    openrouter: OpenAIRecorder,
    eu_backup: OpenAIRecorder | None = None,
) -> Orchestrator:
    models = settings.models
    assert models.scaleway is not None and models.openrouter is not None
    llm = LLMRouter(
        settings,
        scaleway.scaleway(models.scaleway, "Rewrite."),
        openrouter.openrouter(models.openrouter),
        # A second Scaleway client stands in for the other EU provider: the router only
        # needs a client that answers.
        eu_backup=eu_backup.scaleway(models.scaleway, "Rewrite.") if eu_backup else None,
    )
    return Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=llm,
    )


async def ask(orch: Orchestrator, world: World, question: str = "Capacity?") -> list[Any]:
    cid = await world.new_conversation()
    return [event async for event in await orch.answer(world.ctx, cid, question)]


async def last_audit(world: World) -> dict[str, Any]:
    raw = await world.admin.fetchval(
        "SELECT metadata FROM audit_events WHERE tenant_id = $1 AND event = 'chat.query' "
        "ORDER BY created_at DESC LIMIT 1",
        INTERNAL_TENANT_ID,
    )
    metadata: dict[str, Any] = json.loads(raw)
    return metadata


async def ledger_cents(world: World, model: str) -> Decimal:
    value = await world.admin.fetchval(
        "SELECT cost_cents FROM usage_ledger WHERE tenant_id = $1 AND model = $2",
        INTERNAL_TENANT_ID,
        model,
    )
    return Decimal(value or 0)


@pytest.mark.parametrize(
    ("models", "external", "cap", "spent"),
    [
        ([DEEPSEEK, CLAUDE], False, None, None),  # the model enabled, no entitlement
        ([DEEPSEEK], False, None, None),
        ([DEEPSEEK], True, 100, None),  # entitled, but no external model enabled
        ([DEEPSEEK, CLAUDE], True, 100, "100"),  # entitled, cap reached
        ([DEEPSEEK, CLAUDE], True, 0, None),  # entitled, a zero cap
    ],
)
async def test_a_tenant_not_entitled_never_reaches_openrouter_on_failover(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
    models: list[str],
    external: bool,
    cap: int | None,
    spent: str | None,
) -> None:
    await internal_entitlement(models, external=external, cap=cap)
    if spent is not None:
        await ledger(CLAUDE, spent)
    await fixed_choice(world, EU_CHOICE)
    scaleway = OpenAIRecorder(*DOWN)
    openrouter = OpenAIRecorder()  # no replies: any request would fail the test
    events = await ask(orchestrator(settings, engine, world, scaleway, openrouter), world)
    assert events == [ErrorEvent("llm_5xx")]
    assert openrouter.requests == []
    assert len(scaleway.requests) == 2


async def test_an_entitled_tenant_fails_over_to_openrouter_with_zdr_and_the_cap(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, EU_CHOICE)
    await ledger(CLAUDE, "79.6")  # the failover's cost crosses 80 percent
    scaleway = OpenAIRecorder(*DOWN)
    openrouter = OpenAIRecorder(sse(delta("Grew [1].", USAGE)))
    events = await ask(orchestrator(settings, engine, world, scaleway, openrouter), world)

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert (done.model, done.failover, done.cached) == (CLAUDE, "external", False)
    (body,) = openrouter.bodies()
    assert body["model"] == CLAUDE
    assert body["provider"]["zdr"] is True and body["provider"]["data_collection"] == "deny"
    assert "reasoning" not in body or body["reasoning"].get("effort") == "none"
    # Counted against the cap: priced into the ledger under the external model, and the
    # 80 percent notice follows.
    assert await ledger_cents(world, CLAUDE) == Decimal("79.6") + expected_cents(
        settings, CLAUDE, USAGE["prompt_tokens"], USAGE["completion_tokens"]
    )
    kinds = await world.admin.fetch(
        "SELECT kind FROM operator_notices WHERE tenant_id = $1 AND kind = 'spend.cap_80'",
        INTERNAL_TENANT_ID,
    )
    assert len(kinds) == 1
    audit = await last_audit(world)
    assert (audit["failover"], audit["model"], audit["status"]) == ("external", CLAUDE, "ok")
    assert redis.store == {}  # a failover's answer is not cached under the EU model's key
    message_model = await world.admin.fetchval(
        "SELECT model FROM messages WHERE id = $1", done.message_id
    )
    assert message_model == CLAUDE


async def test_the_eu_backup_answers_before_openrouter(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, EU_CHOICE)
    backup = OpenAIRecorder(sse(delta("Grew [1].", USAGE)))
    openrouter = OpenAIRecorder()
    orch = orchestrator(settings, engine, world, OpenAIRecorder(*DOWN), openrouter, backup)
    done = (await ask(orch, world))[-1]
    assert isinstance(done, DoneEvent) and done.failover == "eu"
    assert openrouter.requests == [] and len(backup.requests) == 1


async def test_openrouter_follows_when_the_eu_backup_is_down_too(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, EU_CHOICE)
    openrouter = OpenAIRecorder(sse(delta("Grew [1].", USAGE)))
    orch = orchestrator(
        settings, engine, world, OpenAIRecorder(*DOWN), openrouter, OpenAIRecorder(*DOWN)
    )
    done = (await ask(orch, world))[-1]
    assert isinstance(done, DoneEvent) and done.failover == "external"
    assert len(openrouter.requests) == 1


async def test_without_entitlement_only_the_eu_backup_answers(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=False)
    await fixed_choice(world, EU_CHOICE)
    openrouter = OpenAIRecorder()
    orch = orchestrator(
        settings, engine, world, OpenAIRecorder(*DOWN), openrouter, OpenAIRecorder(*DOWN)
    )
    assert await ask(orch, world) == [ErrorEvent("llm_5xx")]
    assert openrouter.requests == []


async def test_a_refusal_does_not_fail_over(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    """A 400 is the call's fault, not the provider's: no other provider gets it."""
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, EU_CHOICE)
    backup, openrouter = OpenAIRecorder(), OpenAIRecorder()
    orch = orchestrator(settings, engine, world, OpenAIRecorder(error(400)), openrouter, backup)
    assert await ask(orch, world) == [ErrorEvent("llm_4xx")]
    assert openrouter.requests == [] and backup.requests == []


async def test_an_external_conversation_does_not_fail_over(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, EXTERNAL_CHOICE)
    scaleway, backup = OpenAIRecorder(), OpenAIRecorder()
    orch = orchestrator(settings, engine, world, scaleway, OpenAIRecorder(*DOWN), backup)
    assert await ask(orch, world) == [ErrorEvent("llm_5xx")]
    assert scaleway.requests == [] and backup.requests == []


def test_eu_failover_needs_the_other_providers_key(tmp_path: Path) -> None:
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    toml = config / "models.toml"
    text = toml.read_text(encoding="utf-8")
    assert "eu_failover = false\n" in text  # the repository default
    toml.write_text(text.replace("eu_failover = false\n", "eu_failover = true\n"), encoding="utf-8")
    assert load_settings(environ=ENV, config_dir=config).models.llm.eu_failover
    env = {k: v for k, v in ENV.items() if k != "MISTRAL_API_KEY"}
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=env, config_dir=config)
    assert any("MISTRAL_API_KEY" in p for p in excinfo.value.problems)


def test_history_marks_a_backups_answer(settings: Settings) -> None:
    from types import SimpleNamespace

    from app.api.v1 import _failover
    from app.chat.models import Message

    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    def message(role: str, model: str | None) -> Message:
        return Message(role=role, model=model)

    assert _failover(request, DEEPSEEK, message("assistant", DEEPSEEK)) is None
    assert _failover(request, DEEPSEEK, message("assistant", CLAUDE)) == "external"
    assert _failover(request, DEEPSEEK, message("assistant", "mistral-medium-2604")) == "eu"
    assert _failover(request, DEEPSEEK, message("user", None)) is None
    assert _failover(request, DEEPSEEK, message("assistant", None)) is None
