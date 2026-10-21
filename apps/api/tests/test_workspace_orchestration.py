"""P1a-05: workspace-scoped orchestration. Package enforcement per workspace
(architecture §8), the workspace-aware cache key, and the audit trail of workspace,
model and reasoning. Against PostgreSQL, a fake retriever and a recorded transport."""

from __future__ import annotations

import dataclasses
import json
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import DEFAULT_CONFIG_DIR, Settings, load_settings
from app.retrieval.types import RetrievedChunk
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import DATASETS, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, delta, sse
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_config import ENV
from tests.test_model_catalogue import DEEPSEEK, QWEN, internal_entitlement
from tests.test_orchestrator import done_of, orchestrator, run, text_of

__all__ = ["internal_entitlement"]  # fixture reused from the catalogue tests

pytestmark = pytest.mark.usefixtures("database")


class CorpusRetriever(FakeRetriever):
    """Behaves like RAGFlow: returns only chunks of the datasets it is asked for."""

    async def retrieve(
        self, *, dataset_ids: list[str], query: str, top_k: int, similarity_threshold: float
    ) -> list[RetrievedChunk]:
        found = await super().retrieve(
            dataset_ids=dataset_ids,
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        return [c for c in found if c.dataset_id in dataset_ids]


def b_only_chunks(world: World) -> list[RetrievedChunk]:
    """Chunks that match the question, all in the analysis dataset (workspace B)."""
    doc_b = list(world.sources)[1]  # the analysis deck (tests.chat_fixtures)
    return [
        RetrievedChunk(
            chunk_id=f"chunk-{uuid.uuid4().hex[:10]}",
            document_id=doc_b,
            dataset_id=DATASETS["sample-analysis"],
            text="Our synthetic deck expects a slowdown in 2026.",
            score=0.9,
            page_or_slide=2,
        )
    ]


async def _two_workspaces(world: World) -> tuple[uuid.UUID, uuid.UUID]:
    return (
        await world.new_workspace(["sample-reports"], slug="ws-a-reports"),
        await world.new_workspace(["sample-analysis"], slug="ws-b-analysis"),
    )


# --- package enforcement, per workspace ---------------------------------------------------


async def test_query_matching_only_workspace_b_returns_nothing_in_workspace_a(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    a, b = await _two_workspaces(world)
    retriever = CorpusRetriever(b_only_chunks(world))
    recorder = Recorder(sse(delta("Slowdown [1].")))
    orch = orchestrator(settings, engine, retriever, recorder)

    in_a = await run(orch, world, "Slowdown in 2026?", await world.new_conversation(workspace_id=a))
    assert retriever.calls[0]["dataset_ids"] == [DATASETS["sample-reports"]]
    assert done_of(in_a).abstained and recorder.requests == []

    # The same question in workspace B finds it: the documents exist, A cannot see them.
    in_b = await run(orch, world, "Slowdown in 2026?", await world.new_conversation(workspace_id=b))
    assert retriever.calls[1]["dataset_ids"] == [DATASETS["sample-analysis"]]
    assert text_of(in_b) == "Slowdown [1]." and not done_of(in_b).abstained


async def test_chunks_from_outside_the_workspace_are_dropped_even_if_returned(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    """Defence in depth: a retriever that ignored the dataset IDs still leaks nothing."""
    a, _ = await _two_workspaces(world)
    retriever = FakeRetriever(b_only_chunks(world))  # returns B's chunk whatever it is asked
    recorder = Recorder()
    events = await run(
        orchestrator(settings, engine, retriever, recorder),
        world,
        "Slowdown in 2026?",
        await world.new_conversation(workspace_id=a),
    )
    assert done_of(events).abstained and recorder.requests == []


# --- cache key ----------------------------------------------------------------------------


def _settings_with_prompt_version(settings: Settings, tmp_path: Path, version: str) -> Settings:
    """The repository configuration, with the active corpus-only prompt renamed."""
    config = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, config)
    prompts = config / "prompts" / "corpus_only"
    active = settings.models.prompts.corpus_only
    shutil.copy(prompts / f"{active}.md", prompts / f"{version}.md")
    toml = config / "models.toml"
    text = toml.read_text(encoding="utf-8")
    toml.write_text(
        text.replace(f'corpus_only = "{active}"', f'corpus_only = "{version}"'), encoding="utf-8"
    )
    changed = load_settings(environ=ENV, config_dir=config)
    assert changed.models.prompts.corpus_only == version
    return changed


async def _ask_twice(
    world: World,
    first: tuple[Settings, uuid.UUID],
    second: tuple[Settings, uuid.UUID],
    engine: AsyncEngine,
    chunks: Sequence[RetrievedChunk],
) -> tuple[FakeRetriever, bool]:
    retriever = FakeRetriever(chunks)
    recorder = Recorder(sse(delta("Grew [1].")), sse(delta("Grew [1].")))
    await run(orchestrator(first[0], engine, retriever, recorder), world, "Capacity?", first[1])
    events = await run(
        orchestrator(second[0], engine, retriever, recorder), world, "Capacity?", second[1]
    )
    return retriever, done_of(events).cached


async def test_cache_misses_on_a_prompt_version_change(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis, tmp_path: Path
) -> None:
    changed = _settings_with_prompt_version(settings, tmp_path, "v99")
    retriever, cached = await _ask_twice(
        world,
        (settings, await world.new_conversation()),
        (changed, await world.new_conversation()),
        engine,
        chunks_for(world),
    )
    assert not cached and len(retriever.calls) == 2
    assert len(redis.store) == 2


@pytest.mark.parametrize(
    "change",
    ["workspace", "reasoning", "top_k", "similarity_threshold", "max_context_tokens"],
)
async def test_cache_misses_when_anything_in_the_key_changes(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    change: str,
    internal_entitlement: Any,
) -> None:
    second_settings = settings
    if change == "reasoning":  # a model that may reason: DeepSeek offers off only
        await internal_entitlement([DEEPSEEK, QWEN])
        world.model = QWEN
    second = await world.new_conversation()
    if change == "workspace":
        # Same tags, same datasets: still a different workspace, so a different answer
        # may follow once its instructions differ.
        same_tags = await world.new_workspace(["sample-analysis", "sample-reports", "sample-web"])
        second = await world.new_conversation(workspace_id=same_tags)
    elif change == "reasoning":
        second = await world.new_conversation(reasoning=True)
    else:
        chat = settings.models.chat
        value = {"top_k": 8, "similarity_threshold": 0.3, "max_context_tokens": 5000}[change]
        models = settings.models.model_copy(
            update={"chat": chat.model_copy(update={change: value})}
        )
        second_settings = dataclasses.replace(settings, models=models)
    retriever, cached = await _ask_twice(
        world,
        (settings, await world.new_conversation()),
        (second_settings, second),
        engine,
        chunks_for(world),
    )
    assert not cached and len(retriever.calls) == 2


async def test_same_settings_still_hit_the_cache(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    retriever, cached = await _ask_twice(
        world,
        (settings, await world.new_conversation()),
        (settings, await world.new_conversation()),
        engine,
        chunks_for(world),
    )
    assert cached and len(retriever.calls) == 1
    (key,) = redis.store
    assert key.startswith(f"t:{INTERNAL_TENANT_ID}:answer:corpus_only:")


# --- audit and persistence ----------------------------------------------------------------


async def test_audit_and_messages_record_workspace_model_and_reasoning(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    world.model = QWEN  # a model that may reason: DeepSeek offers off only
    workspace = await world.new_workspace(["sample-reports", "sample-analysis"])
    conversation = await world.new_conversation(workspace_id=workspace, reasoning=True)
    events = await run(
        orchestrator(
            settings, engine, FakeRetriever(chunks_for(world)), Recorder(sse(delta("Grew [1].")))
        ),
        world,
        "Capacity?",
        conversation,
    )
    done = done_of(events)
    metadata = json.loads(
        await world.admin.fetchval(
            "SELECT metadata FROM audit_events WHERE metadata->>'message_id' = $1",
            str(done.message_id),
        )
    )
    assert metadata["workspace_id"] == str(workspace)
    assert metadata["reasoning"] is True
    assert metadata["model"] == QWEN  # what the (recorded) provider served
    assert metadata["mode"] == "corpus_only"
    rows = await world.admin.fetch(
        "SELECT role, mode, model, reasoning FROM messages WHERE conversation_id = $1 "
        "ORDER BY created_at",
        conversation,
    )
    assert [tuple(r) for r in rows] == [
        ("user", "corpus_only", None, None),
        ("assistant", "corpus_only", QWEN, True),
    ]


async def test_abstention_audit_names_the_conversations_model(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    empty = await world.new_workspace([])
    conversation = await world.new_conversation(workspace_id=empty)
    events = await run(
        orchestrator(settings, engine, FakeRetriever(), Recorder()), world, "Q?", conversation
    )
    metadata = json.loads(
        await world.admin.fetchval(
            "SELECT metadata FROM audit_events WHERE metadata->>'message_id' = $1",
            str(done_of(events).message_id),
        )
    )
    assert (metadata["outcome"], metadata["model"], metadata["workspace_id"]) == (
        "abstained",
        "deepseek-v4.1-flash",
        str(empty),
    )
