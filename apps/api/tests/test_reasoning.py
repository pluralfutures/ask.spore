"""P1a-11: the reasoning switch. Reasoning text in a stream is discarded: it reaches
neither the user, the database, the cache, the audit trail nor the logs; the answer
carries the badge data (model and reasoning flag)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.orchestrator import DoneEvent, ErrorEvent, Orchestrator, TokenEvent
from app.core.config import Settings, load_settings
from app.core.db import session_factory
from app.llm import catalogue
from app.llm.catalogue import ModelChoice
from app.llm.mistral import ANSWER_MAX_TOKENS, REASONING_MAX_TOKENS, LLMError
from app.llm.reasoning import ThinkFilter
from app.tenancy.entitlements import ModelEntitlement, ModelRefused, check_choice
from tests.chat_fixtures import USAGE, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, OpenAIRecorder, router, sse
from tests.test_api import Harness, api
from tests.test_config import ENV, write_config
from tests.test_model_catalogue import CLAUDE, DEEPSEEK, QWEN, fixed_choice, internal_entitlement
from tests.test_openrouter import CONFIG as OPENROUTER

__all__ = ["api", "internal_entitlement"]  # fixtures reused from other test modules

# Synthetic reasoning text: none of it may appear anywhere but the mocked provider reply.
SECRETS = (
    "SECRET-REASONING-FIELD-alpha",
    "SECRET-INLINE-THINK-beta",
    "SECRET-REASONING-FIELD-gamma",
    "SECRET-OPENROUTER-REASONING-delta",
    "SECRET-OPENROUTER-DETAILS-epsilon",
)


def chunk(delta: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "cmpl-r",
        "object": "chat.completion.chunk",
        "model": "synthetic",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    if usage is not None:
        data["usage"] = usage
        data["choices"][0]["finish_reason"] = "stop"
    return data


# Scaleway-style: a separate reasoning_content field, and thinking inline in content,
# its tags split across deltas.
SCALEWAY_REASONING_STREAM = sse(
    chunk({"role": "assistant", "reasoning_content": SECRETS[0]}),
    chunk({"content": f"<think>{SECRETS[1]}</th"}),
    chunk({"content": "ink>Capacity grew [1]"}),
    chunk({"reasoning_content": SECRETS[2], "content": " in 2025."}),
    chunk({}, USAGE),
)
# OpenRouter-style: reasoning and reasoning_details fields.
OPENROUTER_REASONING_STREAM = sse(
    chunk(
        {
            "role": "assistant",
            "reasoning": SECRETS[3],
            "reasoning_details": [{"type": "reasoning.text", "text": SECRETS[4]}],
        }
    ),
    chunk({"content": "Capacity grew [1]."}),
    chunk({}, USAGE),
)


def ending(finish_reason: str) -> dict[str, Any]:
    data = chunk({}, USAGE)
    data["choices"][0]["finish_reason"] = finish_reason
    return data


# The output budget ran out: during hidden reasoning (no answer text), or mid-answer.
REASONING_ONLY_STREAM = sse(
    chunk({"role": "assistant", "reasoning_content": SECRETS[0]}), ending("length")
)
CUT_OFF_STREAM = sse(
    chunk({"role": "assistant", "content": "Capacity grew [1] and"}), ending("length")
)


def assert_no_reasoning(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


# --- the filter -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deltas", "expected"),
    [
        (["Plain answer."], "Plain answer."),
        (["<think>x</think>Answer."], "Answer."),
        (["<thi", "nk>x</thi", "nk>Ans", "wer."], "Answer."),
        (["A <think>x</think>b <think>y</think>c"], "A b c"),
        (["Answer <th"], "Answer <th"),  # a partial tag at the end was answer text
        (["Answer <think>never closed"], "Answer "),
        (["a < b and c <t> d"], "a < b and c <t> d"),
    ],
)
def test_think_filter(deltas: list[str], expected: str) -> None:
    flt = ThinkFilter()
    out = "".join(flt.feed(d) for d in deltas) + flt.flush()
    assert out == expected


# --- streams yield only answer text ----------------------------------------------------


async def test_scaleway_stream_with_reasoning_yields_only_the_answer(settings: Settings) -> None:
    recorder = OpenAIRecorder(SCALEWAY_REASONING_STREAM)
    stream = await router(settings, recorder).answer(
        "System.", [], [], "Capacity?", ModelChoice(QWEN, True)
    )
    text = "".join([part async for part in stream])
    assert text == "Capacity grew [1] in 2025."
    assert stream.usage is not None and stream.usage.tokens_out == USAGE["completion_tokens"]
    assert recorder.bodies()[0]["reasoning_effort"] == "medium"  # thinking on (findings C26)
    assert stream.finish_reason == "stop"


async def test_openrouter_stream_with_reasoning_yields_only_the_answer() -> None:
    recorder = OpenAIRecorder(OPENROUTER_REASONING_STREAM)
    stream = await recorder.openrouter(OPENROUTER).answer(
        "System.", [], [], "Capacity?", model=CLAUDE, reasoning={"reasoning": {"effort": "medium"}}
    )
    assert "".join([part async for part in stream]) == "Capacity grew [1]."


# --- the orchestrator persists, caches, audits and logs no reasoning --------------------


async def test_reasoning_is_never_persisted_cached_audited_or_logged(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    capsys: pytest.CaptureFixture[str],
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    await fixed_choice(world, ModelChoice(QWEN, True))
    recorder = OpenAIRecorder(SCALEWAY_REASONING_STREAM)
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, recorder),
    )
    capsys.readouterr()
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    logged = capsys.readouterr()

    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == (
        "Capacity grew [1] in 2025."
    )
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert (done.model, done.reasoning) == (QWEN, True)
    assert_no_reasoning(logged.out + logged.err)
    assert_no_reasoning(json.dumps(redis.store))
    stored = await world.admin.fetch(
        "SELECT m::text AS row FROM messages m WHERE conversation_id = $1",
        world.conversation_id,
    )
    assert len(stored) == 2
    for row in stored:
        assert_no_reasoning(row["row"])
    audit = await world.admin.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'chat.query' "
        "AND metadata->>'conversation_id' = $1",
        str(world.conversation_id),
    )
    assert_no_reasoning(audit)
    assert json.loads(audit)["reasoning"] is True
    assert json.loads(audit)["model"] == QWEN


async def test_reasoning_is_stored_on_the_message(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    await fixed_choice(world, ModelChoice(QWEN, True))
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, OpenAIRecorder(SCALEWAY_REASONING_STREAM)),
    )
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    reasoning = await world.admin.fetchval(
        "SELECT reasoning FROM messages WHERE id = $1", done.message_id
    )
    assert reasoning is True


# --- the output budget: room for reasoning, and a cut-off answer is not passed as whole ---


@pytest.mark.parametrize(
    ("model", "on", "budget"),
    [
        (DEEPSEEK, False, ANSWER_MAX_TOKENS),
        (QWEN, True, ANSWER_MAX_TOKENS + REASONING_MAX_TOKENS),
    ],
)
async def test_reasoning_on_gets_room_for_reasoning_tokens(
    settings: Settings, model: str, on: bool, budget: int
) -> None:
    recorder = OpenAIRecorder(SCALEWAY_REASONING_STREAM)
    stream = await router(settings, recorder).answer(
        "System.", [], [], "Capacity?", ModelChoice(model, on)
    )
    [part async for part in stream]
    assert recorder.bodies()[0]["max_tokens"] == budget


async def test_budget_spent_on_reasoning_alone_is_an_error_not_unsupported(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    internal_entitlement: Any,
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    await fixed_choice(world, ModelChoice(QWEN, True))
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, OpenAIRecorder(REASONING_ONLY_STREAM)),
    )
    spent_sql = "SELECT coalesce(sum(tokens_out), 0) FROM usage_ledger WHERE tenant_id = $1"
    before = await world.admin.fetchval(spent_sql, world.ctx.tenant_id)
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].error_code == "answer_cut_off"
    assert not any(isinstance(e, DoneEvent) for e in events)
    answers = await world.admin.fetchval(
        "SELECT count(*) FROM messages WHERE conversation_id = $1 AND role = 'assistant'",
        world.conversation_id,
    )
    assert answers == 0
    # The tokens were spent, so they are counted.
    after = await world.admin.fetchval(spent_sql, world.ctx.tenant_id)
    assert after - before == USAGE["completion_tokens"]


async def test_cut_off_answer_is_marked_truncated_and_not_cached(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> None:
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, OpenAIRecorder(CUT_OFF_STREAM)),
    )
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.truncated is True
    assert done.unsupported is False
    assert "Capacity grew" not in json.dumps(redis.store)


# --- badge data in the API response -------------------------------------------------------


async def test_badge_data_in_stream_and_conversation(
    api: Harness, internal_entitlement: Any
) -> None:
    await internal_entitlement([DEEPSEEK, QWEN])
    created = await api.request("POST", "/conversations", json={"model": QWEN, "reasoning": True})
    assert created.status_code == 201, created.text
    assert (created.json()["model"], created.json()["reasoning"]) == (QWEN, True)
    conversation = created.json()["id"]
    api.recorder.add(SCALEWAY_REASONING_STREAM)
    response = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "Capacity?"}
    )
    assert response.status_code == 200
    assert_no_reasoning(response.text)
    done = json.loads(response.text.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert (done["model"], done["reasoning"]) == (QWEN, True)

    detail = (await api.request("GET", f"/conversations/{conversation}")).json()
    assert_no_reasoning(json.dumps(detail))
    user, assistant = detail["messages"]
    assert (user["model"], user["reasoning"]) == (None, None)
    assert (assistant["model"], assistant["reasoning"]) == (QWEN, True)


# --- DeepSeek: reasoning off only (owner decision, Oct 21, 2026) -------------------------


def test_deepseek_offers_reasoning_off_only(settings: Settings) -> None:
    deepseek = catalogue.entry(settings, DEEPSEEK)
    qwen = catalogue.entry(settings, QWEN)
    assert deepseek is not None and qwen is not None
    assert (deepseek.reasoning, deepseek.can_reason) == ("thinking", False)
    assert qwen.can_reason is True
    ent = ModelEntitlement((DEEPSEEK, QWEN), False, None)
    with pytest.raises(ModelRefused) as excinfo:
        check_choice(settings, ent, ModelChoice(DEEPSEEK, True))
    assert excinfo.value.code == "reasoning_unsupported"


async def test_deepseek_off_still_sends_reasoning_none_and_on_is_refused(
    settings: Settings,
) -> None:
    recorder = OpenAIRecorder(SCALEWAY_REASONING_STREAM)
    llm = router(settings, recorder)
    stream = await llm.answer("System.", [], [], "Capacity?", ModelChoice(DEEPSEEK, False))
    [part async for part in stream]
    # DeepSeek reasons by default, so off must be sent explicitly.
    assert recorder.bodies()[0]["reasoning_effort"] == "none"
    with pytest.raises(LLMError) as excinfo:
        await llm.answer("System.", [], [], "Capacity?", ModelChoice(DEEPSEEK, True))
    assert excinfo.value.error_code == "reasoning_unsupported"
    assert len(recorder.requests) == 1  # nothing went out for the refused call


# --- a model without a switch ------------------------------------------------------------


def test_reasoning_on_a_model_without_a_switch_is_refused(tmp_path: Any) -> None:
    mistral = load_settings(environ=ENV, config_dir=write_config(tmp_path))
    ent = ModelEntitlement(("mistral-large-2512",), False, None)
    assert check_choice(mistral, ent, ModelChoice("mistral-large-2512", False)).id
    with pytest.raises(ModelRefused) as excinfo:
        check_choice(mistral, ent, ModelChoice("mistral-large-2512", True))
    assert excinfo.value.code == "reasoning_unsupported"
