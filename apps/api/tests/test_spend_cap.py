"""P1a-10: usage ledger, the 80 percent operator notice and the 100 percent spend cap,
against PostgreSQL with recorded (mocked) Scaleway and OpenRouter transports."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import DoneEvent, ErrorEvent, Orchestrator
from app.chat.selection import SPEND_CAP_NOTICE, choose_for_new_conversation
from app.core.config import Settings
from app.core.db import session_factory, tenant_session
from app.llm.catalogue import ModelChoice
from app.tenancy.entitlements import ModelRefused
from app.tenancy.models import INTERNAL_TENANT_ID
from app.usage.ledger import month_of
from tests.chat_fixtures import DATASETS, USAGE, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, OpenAIRecorder, completion, delta, router, sse
from tests.test_model_catalogue import CLAUDE, DEEPSEEK, fixed_choice, internal_entitlement

__all__ = ["internal_entitlement"]  # fixture reused from the catalogue tests

# The internal tenant's seeded workspace (revision 0007): DeepSeek, reasoning off.
WORKSPACE_DEFAULT = ModelChoice(DEEPSEEK, False)
MONTH = month_of()
LAST_MONTH = (MONTH - timedelta(days=1)).replace(day=1)
# USAGE (900 in, 40 out) on Claude at the repository's catalogue prices, in cents.
CLAUDE_ANSWER_CENTS = Decimal(900 * 500 + 40 * 2500) / 1_000_000


@pytest.fixture
async def ledger(world: World) -> AsyncIterator[Any]:
    """Empty spend state for the internal tenant; ``ledger(model, cents, month)`` adds."""

    async def clear() -> None:
        for table in ("usage_ledger", "spend_notices"):
            await world.admin.execute(
                f"DELETE FROM {table} WHERE tenant_id = $1", INTERNAL_TENANT_ID
            )
        await world.admin.execute(
            "DELETE FROM operator_notices WHERE tenant_id = $1 AND kind LIKE 'spend.%'",
            INTERNAL_TENANT_ID,
        )

    async def add(model: str, cents: str, month: date = MONTH) -> None:
        await world.admin.execute(
            "INSERT INTO usage_ledger (tenant_id, month, model, tokens_in, tokens_out, cost_cents) "
            "VALUES ($1, $2, $3, 1, 1, $4::numeric)",
            INTERNAL_TENANT_ID,
            month,
            model,
            cents,
        )

    await clear()
    yield add
    await clear()


def orchestrator(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    scaleway: OpenAIRecorder,
    openrouter: OpenAIRecorder | None,
) -> Orchestrator:
    return Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, scaleway, openrouter),
    )


async def ask(orch: Orchestrator, world: World, question: str = "Capacity?") -> list[Any]:
    cid = await world.new_conversation()
    return [event async for event in await orch.answer(world.ctx, cid, question)]


async def notices(world: World) -> list[str]:
    rows = await world.admin.fetch(
        "SELECT kind FROM operator_notices WHERE tenant_id = $1 AND kind LIKE 'spend.%' "
        "ORDER BY kind",
        INTERNAL_TENANT_ID,
    )
    return [r["kind"] for r in rows]


# --- usage ledger ---------------------------------------------------------------------


async def test_rewrite_and_answer_usage_are_priced_into_the_ledger(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis, ledger: Any
) -> None:
    scaleway = OpenAIRecorder(completion("synthetic capacity 2025"), sse(delta("Grew [1].", USAGE)))
    orch = orchestrator(settings, engine, world, scaleway, None)
    cid = await world.new_conversation()
    await world.admin.execute(
        "INSERT INTO messages (tenant_id, conversation_id, role, content) "
        "VALUES ($1, $2, 'user', 'Earlier synthetic question?')",
        INTERNAL_TENANT_ID,
        cid,
    )
    events = [e async for e in await orch.answer(world.ctx, cid, "And in 2025?")]
    assert isinstance(events[-1], DoneEvent)

    row = await world.admin.fetchrow(
        "SELECT month, tokens_in, tokens_out, cost_cents FROM usage_ledger "
        "WHERE tenant_id = $1 AND model = $2",
        INTERNAL_TENANT_ID,
        DEEPSEEK,
    )
    assert row is not None
    # rewrite 40 + 8 (fixture completion) and answer 900 + 40, both on the default model
    assert (row["month"], row["tokens_in"], row["tokens_out"]) == (MONTH, 940, 48)
    assert row["cost_cents"] == Decimal(940 * 20 + 48 * 80) / 1_000_000


async def test_external_answer_goes_through_openrouter_and_is_priced(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=10_000)
    await fixed_choice(world, ModelChoice(CLAUDE, False))
    scaleway, openrouter = OpenAIRecorder(), OpenAIRecorder(sse(delta("Grew [1].", USAGE)))
    events = await ask(orchestrator(settings, engine, world, scaleway, openrouter), world)

    assert isinstance(events[-1], DoneEvent)
    assert scaleway.requests == []
    [request] = openrouter.requests
    body = json.loads(request.content)
    assert body["model"] == CLAUDE
    assert body["provider"] == {"zdr": True, "data_collection": "deny"}
    wire = request.content.decode() + str(request.url) + str(dict(request.headers))
    identifiers = [
        str(INTERNAL_TENANT_ID),
        str(world.user_id),
        world.user_email,
        *DATASETS.values(),
        *world.sources,
        *(str(s) for s in world.sources.values()),
    ]
    for value in identifiers:
        assert value not in wire
    cost = await world.admin.fetchval(
        "SELECT cost_cents FROM usage_ledger WHERE tenant_id = $1 AND model = $2",
        INTERNAL_TENANT_ID,
        CLAUDE,
    )
    assert cost == CLAUDE_ANSWER_CENTS


# --- 80 percent: one operator notice per month ----------------------------------------


async def test_80_percent_notice_is_written_once_per_month(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, ModelChoice(CLAUDE, False))
    await ledger(CLAUDE, "79.6")  # one answer (0.55 cents) crosses 80 percent
    await ledger(CLAUDE, "500", LAST_MONTH)  # last month never counts

    for n in range(3):
        openrouter = OpenAIRecorder(sse(delta(f"Grew [1] ({n}).", USAGE)))
        orch = orchestrator(settings, engine, world, OpenAIRecorder(), openrouter)
        events = await ask(orch, world, f"Capacity {n}?")
        assert isinstance(events[-1], DoneEvent)
        assert await notices(world) == ["spend.cap_80"]

    metadata = await world.admin.fetchval(
        "SELECT metadata FROM operator_notices WHERE tenant_id = $1 AND kind = 'spend.cap_80'",
        INTERNAL_TENANT_ID,
    )
    assert json.loads(metadata) == {
        "month": MONTH.strftime("%Y-%m"),
        "threshold_percent": 80,
        "cap_cents": 100,
        "spent_cents": 80,
    }
    assert (
        await world.admin.fetchval(
            "SELECT count(*) FROM spend_notices WHERE tenant_id = $1 AND month = $2",
            INTERNAL_TENANT_ID,
            MONTH,
        )
        == 1
    )


async def test_crossing_100_percent_writes_its_own_notice_once(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, ModelChoice(CLAUDE, False))
    await ledger(CLAUDE, "99.9")
    openrouter = OpenAIRecorder(sse(delta("Grew [1].", USAGE)))
    await ask(orchestrator(settings, engine, world, OpenAIRecorder(), openrouter), world)
    assert await notices(world) == ["spend.cap_100", "spend.cap_80"]


async def test_eu_usage_does_not_count_towards_the_cap(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await ledger(DEEPSEEK, "5000")
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        selection = await choose_for_new_conversation(
            session,
            settings,
            INTERNAL_TENANT_ID,
            world.user_id,
            workspace_default=WORKSPACE_DEFAULT,
            model=CLAUDE,
            reasoning=True,
        )
    assert selection.choice == ModelChoice(CLAUDE, True) and selection.notice is None


# --- 100 percent: fall back for new conversations, refuse existing ones -----------------


async def test_cap_reached_new_conversation_falls_back_and_audits(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await ledger(CLAUDE, "100")
    started = datetime.now(UTC)
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        selection = await choose_for_new_conversation(
            session,
            settings,
            INTERNAL_TENANT_ID,
            world.user_id,
            workspace_default=WORKSPACE_DEFAULT,
            model=CLAUDE,
            reasoning=True,
        )

    # The default model, keeping reasoning on (DeepSeek has a thinking switch).
    assert selection.choice == ModelChoice(DEEPSEEK, True)
    assert selection.notice == SPEND_CAP_NOTICE
    assert selection.notice_text is not None and "DeepSeek V4.1 Flash" in selection.notice_text
    audit = await world.admin.fetchrow(
        "SELECT actor_user_id, metadata FROM audit_events "
        "WHERE tenant_id = $1 AND event = 'model.fallback' AND created_at >= $2",
        INTERNAL_TENANT_ID,
        started,
    )
    assert audit is not None and audit["actor_user_id"] == world.user_id
    assert json.loads(audit["metadata"]) == {
        "model": DEEPSEEK,
        "reasoning": True,
        "requested_model": CLAUDE,
        "error_code": "spend_cap_reached",
    }


async def test_below_cap_new_conversation_keeps_its_choice(
    settings: Settings, engine: AsyncEngine, world: World, ledger: Any, internal_entitlement: Any
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await ledger(CLAUDE, "99.99")
    await ledger(CLAUDE, "1000", LAST_MONTH)
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        selection = await choose_for_new_conversation(
            session,
            settings,
            INTERNAL_TENANT_ID,
            world.user_id,
            workspace_default=WORKSPACE_DEFAULT,
            model=CLAUDE,
            reasoning=False,
        )
        default = await choose_for_new_conversation(
            session,
            settings,
            INTERNAL_TENANT_ID,
            world.user_id,
            workspace_default=WORKSPACE_DEFAULT,
        )
    assert selection.choice == ModelChoice(CLAUDE, False) and selection.notice is None
    assert default.choice == ModelChoice(DEEPSEEK, False)


async def test_new_conversation_refuses_what_the_tenant_may_not_use(
    settings: Settings, engine: AsyncEngine, world: World, internal_entitlement: Any
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE])  # external models not entitled
    async with tenant_session(session_factory(engine), INTERNAL_TENANT_ID) as session:
        with pytest.raises(ModelRefused) as excinfo:
            await choose_for_new_conversation(
                session,
                settings,
                INTERNAL_TENANT_ID,
                world.user_id,
                workspace_default=WORKSPACE_DEFAULT,
                model=CLAUDE,
                reasoning=False,
            )
    assert excinfo.value.code == "external_not_entitled"


async def test_cap_reached_refuses_an_existing_external_conversation(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await ledger(CLAUDE, "100")
    await fixed_choice(world, ModelChoice(CLAUDE, False))
    scaleway, openrouter = OpenAIRecorder(), OpenAIRecorder()
    events = await ask(orchestrator(settings, engine, world, scaleway, openrouter), world)
    assert events == [ErrorEvent("spend_cap_reached")]
    assert scaleway.requests == [] and openrouter.requests == []


async def test_external_model_without_openrouter_key_fails_closed(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    ledger: Any,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, CLAUDE], external=True, cap=100)
    await fixed_choice(world, ModelChoice(CLAUDE, False))
    scaleway = OpenAIRecorder()
    events = await ask(orchestrator(settings, engine, world, scaleway, None), world)
    assert events == [ErrorEvent("model_unavailable")]
    assert scaleway.requests == []
