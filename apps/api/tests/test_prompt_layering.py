"""P1a-06: prompt layering through the orchestrator, and the general-knowledge mode.

The system message the model receives is exactly the mode's template with the
workspace's active instructions in their slot; the code path adds nothing else, and
in particular no tenant, user, workspace or dataset identifier."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import TokenEvent
from app.chat.prompts import active_prompt, render_system
from app.core.config import Settings
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import DATASETS, TAGS, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, completion, delta, sse
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_orchestrator import done_of, orchestrator, run

pytestmark = pytest.mark.usefixtures("database")

INSTRUCTIONS = "Prefer the most recent sources. Use British spelling & short paragraphs."
# The active corpus-only version, and P1c-13's candidate (not active until the release
# session's live eval switches it): both must layer the same way and carry no identifier.
CORPUS_ONLY_VERSIONS = [None, "v6"]


def _with_corpus_only(settings: Settings, version: str | None) -> Settings:
    if version is None:
        return settings
    prompts = settings.models.prompts.model_copy(update={"corpus_only": version})
    return replace(settings, models=settings.models.model_copy(update={"prompts": prompts}))


async def _save_instructions(world: World, workspace_id: uuid.UUID, text: str) -> uuid.UUID:
    prompt_id: uuid.UUID = await world.admin.fetchval(
        "INSERT INTO workspace_prompts (tenant_id, workspace_id, version, text, author_user_id) "
        "VALUES ($1, $2, coalesce((SELECT max(version) FROM workspace_prompts "
        "WHERE workspace_id = $2), 0) + 1, $3, $4) RETURNING id",
        INTERNAL_TENANT_ID,
        workspace_id,
        text,
        world.user_id,
    )
    return prompt_id


def _messages(recorder: Recorder, index: int = 0) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = json.loads(recorder.requests[index].content)["messages"]
    return messages


@pytest.mark.parametrize("version", CORPUS_ONLY_VERSIONS)
async def test_system_message_is_the_rendered_template_and_carries_no_identifiers(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis, version: str | None
) -> None:
    settings = _with_corpus_only(settings, version)
    if version is not None:
        assert active_prompt(settings, "corpus_only").ref == f"corpus_only/{version}"
    workspace = await world.new_workspace(list(TAGS), slug="ws-zebra-quartz")
    await world.admin.execute(
        "UPDATE workspaces SET name = 'Zebra Quartz Desk' WHERE id = $1", workspace
    )
    prompt_id = await _save_instructions(world, workspace, INSTRUCTIONS)
    conversation = await world.new_conversation(workspace_id=workspace)
    chunks = chunks_for(world)
    recorder = Recorder(
        sse(delta("Grew [1].")), completion("standalone query"), sse(delta("Slowdown [2]."))
    )
    orch = orchestrator(settings, engine, FakeRetriever(chunks), recorder)
    first = await run(orch, world, "How did capacity change?", conversation)
    await run(orch, world, "And next year?", conversation)

    expected = render_system(active_prompt(settings, "corpus_only"), INSTRUCTIONS)
    for answer_request in (0, 2):
        system = _messages(recorder, answer_request)[0]
        assert system == {"role": "system", "content": expected}
    assert "Use British spelling &amp; short paragraphs." in expected

    display = await world.admin.fetchrow(
        "SELECT u.display_name AS user_name, t.display_name AS tenant_name "
        "FROM users u JOIN tenants t ON t.id = u.tenant_id WHERE u.id = $1",
        world.user_id,
    )
    identifiers = {
        "tenant_id": str(INTERNAL_TENANT_ID),
        "tenant_slug": "internal",
        "tenant_name": display["tenant_name"],
        "user_id": str(world.user_id),
        "user_email": world.user_email,
        "user_name": display["user_name"],
        "conversation_id": str(conversation),
        "message_id": str(done_of(first).message_id),
        "workspace_id": str(workspace),
        "workspace_slug": "ws-zebra-quartz",
        "workspace_name": "Zebra Quartz Desk",
        "workspace_prompt_id": str(prompt_id),
        **{f"tag:{t}": t for t in TAGS},
        **{f"dataset:{d}": d for d in DATASETS.values()},
        **{f"document:{d}": d for d in world.sources},
        **{f"source:{d}": str(s) for d, s in world.sources.items()},
        **{f"chunk:{c.chunk_id}": c.chunk_id for c in chunks},
    }
    for request in recorder.requests:
        wire = (
            request.content.decode()
            + str(request.url)
            + json.dumps({k: v for k, v in request.headers.items() if k != "authorization"})
        )
        assert [name for name, value in identifiers.items() if value in wire] == []


@pytest.mark.parametrize("version", CORPUS_ONLY_VERSIONS)
async def test_without_instructions_the_slot_is_absent(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis, version: str | None
) -> None:
    settings = _with_corpus_only(settings, version)
    recorder = Recorder(sse(delta("Grew [1].")))
    await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    system = _messages(recorder)[0]["content"]
    assert system == render_system(active_prompt(settings, "corpus_only"), "")
    assert "workspace_instructions" not in system


async def test_cache_misses_when_the_workspace_instructions_change(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    workspace = await world.new_workspace(list(TAGS))
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("One [1].")), sse(delta("One [1].")), sse(delta("Two [1].")))
    orch = orchestrator(settings, engine, retriever, recorder)
    ask = lambda: world.new_conversation(workspace_id=workspace)  # noqa: E731

    await run(orch, world, "Capacity?", await ask())
    hit = await run(orch, world, "Capacity?", await ask())
    assert done_of(hit).cached

    await _save_instructions(world, workspace, "Answer in bullet points.")
    miss = await run(orch, world, "Capacity?", await ask())
    assert not done_of(miss).cached and len(retriever.calls) == 2
    assert "Answer in bullet points." in _messages(recorder, 1)[0]["content"]
    audit = await world.admin.fetchval(
        "SELECT metadata->>'instructions_version' FROM audit_events "
        "WHERE metadata->>'message_id' = $1",
        str(done_of(miss).message_id),
    )
    assert audit == "1"


# --- the general-knowledge answer mode ----------------------------------------------------


async def test_general_knowledge_answers_without_a_package(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    empty = await world.new_workspace([])
    conversation = await world.new_conversation(workspace_id=empty, mode="general_knowledge")
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("From general knowledge, capacity usually grows.")))
    events = await run(
        orchestrator(settings, engine, retriever, recorder), world, "Q?", conversation
    )

    assert retriever.calls == []  # no datasets: nothing to retrieve from
    messages = _messages(recorder)
    assert messages[0]["content"] == render_system(active_prompt(settings, "general_knowledge"), "")
    assert "<context>\n\n</context>" in messages[-1]["content"]
    done = done_of(events)
    assert (done.abstained, done.unsupported) == (False, False)
    row = await world.admin.fetchrow(
        "SELECT mode, outcome FROM messages WHERE id = $1", done.message_id
    )
    assert dict(row) == {"mode": "general_knowledge", "outcome": "answered"}
    audit = await world.admin.fetchval(
        "SELECT metadata FROM audit_events WHERE metadata->>'message_id' = $1",
        str(done.message_id),
    )
    assert json.loads(audit)["prompt"] == "general_knowledge/v2"


async def test_general_knowledge_cites_the_corpus_and_keeps_uncited_text(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    conversation = await world.new_conversation(mode="general_knowledge")
    recorder = Recorder(sse(delta("Capacity grew [1]. Prices tend to fall as markets mature.")))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder),
        world,
        "Capacity and prices?",
        conversation,
    )
    done = done_of(events)
    assert not done.unsupported and not done.abstained
    assert "<passage " in _messages(recorder)[-1]["content"]


async def test_general_knowledge_streams_an_uncited_answer_unchanged(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    # The corpus-only citation check (findings section 11, G6) does not apply here.
    conversation = await world.new_conversation(mode="general_knowledge")
    recorder = Recorder(sse(delta("Prices tend "), delta("to fall as markets mature.")))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder),
        world,
        "Prices?",
        conversation,
    )
    assert [e.text for e in events if isinstance(e, TokenEvent)] == [
        "Prices tend ",
        "to fall as markets mature.",
    ]
    assert not done_of(events).unsupported


async def test_corpus_only_still_abstains_where_general_knowledge_would_answer(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    empty = await world.new_workspace([])
    recorder = Recorder()
    events = await run(
        orchestrator(settings, engine, FakeRetriever(), recorder),
        world,
        "Q?",
        await world.new_conversation(workspace_id=empty),
    )
    assert done_of(events).abstained and recorder.requests == []
