"""P0-14: chat orchestrator, against PostgreSQL, a fake retriever, a fake cache and a
recorded (mocked) Mistral transport. No live calls."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import (
    ABSTENTION_TEXT,
    ChatContext,
    ChatEvent,
    CitationsEvent,
    ConversationNotFound,
    DoneEvent,
    ErrorEvent,
    Orchestrator,
    TokenEvent,
)
from app.core import cache
from app.core.config import Settings
from app.core.db import session_factory
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import DATASETS, TAGS, USAGE, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, Recorder, completion, delta, error, sse


def orchestrator(
    settings: Settings, engine: AsyncEngine, retriever: FakeRetriever, recorder: Recorder
) -> Orchestrator:
    return Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=retriever,
        llm=recorder.client(rewrite_system="Rewrite."),
        package_tags=TAGS,
    )


async def run(
    orch: Orchestrator, world: World, question: str, cid: uuid.UUID | None = None
) -> list[ChatEvent]:
    events = await orch.answer(world.ctx, cid or world.conversation_id, question)
    return [event async for event in events]


def text_of(events: list[ChatEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TokenEvent))


def done_of(events: list[ChatEvent]) -> DoneEvent:
    done = events[-1]
    assert isinstance(done, DoneEvent), events
    return done


def citations_of(events: list[ChatEvent]) -> CitationsEvent:
    found = [e for e in events if isinstance(e, CitationsEvent)]
    assert len(found) == 1
    return found[0]


# --- happy path, persistence, ordering -------------------------------------------------


async def test_answer_streams_maps_citations_and_persists(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(
        sse(delta("Capacity grew [1]"), delta(" while a slowdown [2]."), delta("", USAGE))
    )
    events = await run(
        orchestrator(settings, engine, retriever, recorder), world, "How did capacity change?"
    )

    # tokens, then exactly one citations event, then done
    kinds = [type(e).__name__ for e in events]
    assert kinds[-2:] == ["CitationsEvent", "DoneEvent"]
    assert set(kinds[:-2]) == {"TokenEvent"}
    assert text_of(events) == "Capacity grew [1] while a slowdown [2]."
    citations = citations_of(events).citations
    assert [(c.marker, c.publisher, c.page_or_slide) for c in citations] == [
        (1, "Synthetic Institute", 4),
        (2, "Our Analysis Team", 2),
    ]
    done = done_of(events)
    assert (done.unsupported, done.abstained, done.cached) == (False, False, False)
    assert (done.tokens_in, done.tokens_out) == (900, 40)

    rows = await world.admin.fetch(
        "SELECT role, content, outcome, model, tokens_in FROM messages "
        "WHERE conversation_id = $1 ORDER BY created_at",
        world.conversation_id,
    )
    assert [(r["role"], r["outcome"]) for r in rows] == [("user", None), ("assistant", "answered")]
    assert rows[0]["content"] == "How did capacity change?"
    assert rows[1]["content"] == "Capacity grew [1] while a slowdown [2]."
    assert rows[1]["model"] == "mistral-large-2512"
    stored = await world.admin.fetch(
        "SELECT marker, source_id, ragflow_chunk_id, page_or_slide FROM citations "
        "WHERE message_id = $1 ORDER BY marker",
        done.message_id,
    )
    assert [r["source_id"] for r in stored] == list(world.sources.values())
    title = await world.admin.fetchval(
        "SELECT title FROM conversations WHERE id = $1", world.conversation_id
    )
    assert title == "How did capacity change?"


async def test_retrieves_from_every_package_dataset_with_config_parameters(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("Grew [1].")))
    await run(orchestrator(settings, engine, retriever, recorder), world, "Capacity?")
    assert retriever.calls == [
        {
            "dataset_ids": sorted(DATASETS.values()),
            "query": "Capacity?",
            "top_k": 10,
            "similarity_threshold": settings.models.chat.similarity_threshold,
        }
    ]
    # First question: no history, so no rewrite call; one generation request only.
    assert len(recorder.requests) == 1


async def test_follow_up_is_rewritten_with_history(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(
        sse(delta("Grew [1].")),
        completion("synthetic capacity growth Germany 2025"),
        sse(delta("In Germany [1].")),
    )
    orch = orchestrator(settings, engine, retriever, recorder)
    await run(orch, world, "How did capacity change?")
    await run(orch, world, "And in Germany?")
    assert retriever.calls[1]["query"] == "synthetic capacity growth Germany 2025"
    rewrite_body, answer_body = (json.loads(r.content) for r in recorder.requests[1:])
    assert rewrite_body["model"] == "mistral-small-2603"
    roles = [m["role"] for m in answer_body["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
    # Earlier answers go back without their stale [n] markers.
    assert answer_body["messages"][2]["content"] == "Grew ."


# --- abstention ------------------------------------------------------------------------


async def test_abstains_without_llm_call_when_nothing_passes_threshold(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world, score=0.15))  # below the 0.2 threshold
    recorder = Recorder()  # any request would fail: the queue is empty
    events = await run(orchestrator(settings, engine, retriever, recorder), world, "Unrelated?")
    assert recorder.requests == []
    assert text_of(events) == ABSTENTION_TEXT
    assert citations_of(events).citations == []
    done = done_of(events)
    assert (done.abstained, done.unsupported, done.tokens_in) == (True, False, 0)
    outcome = await world.admin.fetchval(
        "SELECT outcome FROM messages WHERE id = $1", done.message_id
    )
    assert outcome == "abstained"


async def test_abstains_when_retrieval_returns_nothing(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder()
    events = await run(orchestrator(settings, engine, FakeRetriever([]), recorder), world, "Q?")
    assert recorder.requests == []
    assert done_of(events).abstained


async def test_abstains_when_package_has_no_synced_dataset(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder()
    orch = orchestrator(settings, engine, retriever, recorder)
    orch._tags = ("not-yet-synced",)
    events = await run(orch, world, "Q?")
    assert retriever.calls == [] and recorder.requests == []
    assert done_of(events).abstained


# --- citation mapping ------------------------------------------------------------------


async def test_dangling_markers_are_dropped_from_stream_and_storage(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder(sse(delta("Grew [1][7"), delta("] and [0], see [2, 9].")))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    assert text_of(events) == "Grew [1] and , see [2]."
    assert [c.marker for c in citations_of(events).citations] == [1, 2]
    stored = await world.admin.fetchval(
        "SELECT content FROM messages WHERE id = $1", done_of(events).message_id
    )
    assert stored == "Grew [1] and , see [2]."


async def test_answer_without_valid_citation_is_flagged_unsupported(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder(sse(delta("Probably about 12 percent [5].")))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    done = done_of(events)
    assert done.unsupported and not done.abstained
    assert citations_of(events).citations == []
    outcome = await world.admin.fetchval(
        "SELECT outcome FROM messages WHERE id = $1", done.message_id
    )
    assert outcome == "unsupported"


# --- cache -----------------------------------------------------------------------------


async def test_cache_hit_returns_stored_answer_without_retrieval_or_llm(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("Capacity grew [1].", USAGE)))
    orch = orchestrator(settings, engine, retriever, recorder)
    first = await run(orch, world, "How did capacity change?")

    second_conversation = await world.new_conversation()
    second = await run(orch, world, "  how did CAPACITY change ", second_conversation)

    assert len(retriever.calls) == 1 and len(recorder.requests) == 1
    assert text_of(second) == text_of(first) == "Capacity grew [1]."
    assert citations_of(second).citations == citations_of(first).citations
    done = done_of(second)
    assert done.cached and (done.tokens_in, done.tokens_out) == (0, 0)
    # The cached answer is persisted in the new conversation like any other.
    stored = await world.admin.fetchval(
        "SELECT count(*) FROM citations WHERE message_id = $1", done.message_id
    )
    assert stored == 1
    # Keys are tenant-prefixed (app.core.cache) and carry the TTL from config.
    assert list(redis.store) == [next(iter(redis.store))]
    key = next(iter(redis.store))
    assert key.startswith(f"t:{INTERNAL_TENANT_ID}:answer:corpus_only:")
    assert redis.ttls[key] == settings.models.chat.cache_ttl_seconds
    assert "capacity" not in key  # the query is hashed into the key


async def test_corpus_change_invalidates_the_cache(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder(sse(delta("Old [1].")), sse(delta("New [1].")))
    orch = orchestrator(settings, engine, retriever, recorder)
    await run(orch, world, "Capacity?")
    await world.admin.execute(
        "UPDATE sources SET ragflow_document_ids = ragflow_document_ids || '[]'::jsonb, "
        "status = 'ingesting' WHERE id = $1",
        next(iter(world.sources.values())),
    )
    events = await run(orch, world, "Capacity?", await world.new_conversation())
    assert text_of(events) == "New [1]."
    assert len(retriever.calls) == 2


async def test_cache_is_not_shared_across_tenants(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder(sse(delta("Grew [1].")))
    await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    (key,) = redis.store
    other_tenant = uuid.uuid4()
    logical = key.split(":", 2)[2]
    assert await cache.get(other_tenant, logical) is None


async def test_unavailable_cache_is_a_miss_not_a_failure(
    settings: Settings, engine: AsyncEngine, world: World
) -> None:
    cache.configure(None)  # get/set raise "cache is not configured"
    recorder = Recorder(sse(delta("Grew [1].")))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    assert not done_of(events).cached


# --- audit -----------------------------------------------------------------------------


async def test_audit_event_written_with_metadata_only(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    question = "What did the synthetic outlook say about capacity?"
    recorder = Recorder(sse(delta("Capacity grew [1].", USAGE)))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, question
    )
    done = done_of(events)
    row = await world.admin.fetchrow(
        "SELECT tenant_id, actor_user_id, event, metadata FROM audit_events "
        "WHERE metadata->>'message_id' = $1",
        str(done.message_id),
    )
    assert row is not None
    assert (row["tenant_id"], row["actor_user_id"], row["event"]) == (
        INTERNAL_TENANT_ID,
        world.user_id,
        "chat.query",
    )
    metadata = json.loads(row["metadata"])
    assert metadata["mode"] == "corpus_only"
    assert metadata["outcome"] == "answered"
    assert metadata["prompt"] == "corpus_only/v1"
    assert metadata["cited_chunk_ids"] == [citations_of(events).citations[0].chunk_id]
    assert metadata["cited_source_ids"] == [str(next(iter(world.sources.values())))]
    serialised = json.dumps(metadata)
    for text in (question, "Capacity grew", "Synthetic capacity grew by 12 percent"):
        assert text not in serialised


async def test_llm_failure_reports_error_and_audits_without_persisting(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder(error(503), error(503))
    events = await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, "Q?"
    )
    assert events[-1] == ErrorEvent("llm_5xx")
    count = await world.admin.fetchval(
        "SELECT count(*) FROM messages WHERE conversation_id = $1", world.conversation_id
    )
    assert count == 0
    audit = await world.admin.fetchval(
        "SELECT metadata->>'error_code' FROM audit_events WHERE metadata->>'conversation_id' = $1",
        str(world.conversation_id),
    )
    assert audit == "llm_5xx"
    assert redis.store == {}


async def test_retrieval_failure_reports_error_without_llm_call(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    recorder = Recorder()
    retriever = FakeRetriever(error=RuntimeError("ragflow down: synthetic detail"))
    events = await run(orchestrator(settings, engine, retriever, recorder), world, "Q?")
    assert events == [ErrorEvent("retrieval_unavailable")]
    assert recorder.requests == []


# --- isolation and minimisation --------------------------------------------------------


async def test_other_users_and_expired_conversations_are_not_found(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    orch = orchestrator(settings, engine, FakeRetriever(), Recorder())
    other_user = await world.admin.fetchval(
        "SELECT id FROM users WHERE email = 'editor@example.org'"
    )
    with pytest.raises(ConversationNotFound):
        await orch.answer(ChatContext(INTERNAL_TENANT_ID, other_user), world.conversation_id, "Q?")
    with pytest.raises(ConversationNotFound):
        await orch.answer(world.ctx, await world.new_conversation(expired=True), "Q?")
    with pytest.raises(ConversationNotFound):
        # Another tenant's context sees nothing under RLS.
        await orch.answer(ChatContext(uuid.uuid4(), world.user_id), world.conversation_id, "Q?")


async def test_nothing_sent_to_mistral_identifies_tenant_user_conversation_or_package(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    chunks = chunks_for(world)
    recorder = Recorder(
        sse(delta("Grew [1].")),
        completion("standalone query"),
        sse(delta("Slowdown [2].")),
    )
    orch = orchestrator(settings, engine, FakeRetriever(chunks), recorder)
    first = await run(orch, world, "How did capacity change?")
    await run(orch, world, "And next year?")
    assert len(recorder.requests) == 3

    identifiers = {
        "tenant_id": str(INTERNAL_TENANT_ID),
        "tenant_slug": "internal",
        "user_id": str(world.user_id),
        "user_email": world.user_email,
        "conversation_id": str(world.conversation_id),
        "message_id": str(done_of(first).message_id),
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
        leaked = [name for name, value in identifiers.items() if value in wire]
        assert leaked == []


async def test_log_lines_carry_no_question_answer_or_chunk_text(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    capsys: pytest.CaptureFixture[str],
) -> None:
    question = "Which synthetic secret phrase appears in the outlook?"
    recorder = Recorder(sse(delta("The phrase is turquoise-heron [1].")))
    await run(
        orchestrator(settings, engine, FakeRetriever(chunks_for(world)), recorder), world, question
    )
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line]
    assert [line["event"] for line in lines] == ["chat.answer"]
    for text in (question, "turquoise-heron", "Synthetic capacity grew"):
        assert text not in out
