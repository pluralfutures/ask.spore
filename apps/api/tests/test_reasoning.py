"""P1a-11: the reasoning switch. Reasoning text in a stream is discarded: it reaches
neither the user, the database, the cache, the audit trail nor the logs; the answer
carries the badge data (model and reasoning flag)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.chat.models import Message
from app.chat.orchestrator import DoneEvent, Orchestrator, TokenEvent
from app.core.config import Settings, load_settings
from app.core.db import session_factory
from app.llm.catalogue import ModelChoice
from app.llm.reasoning import ThinkFilter
from app.tenancy.entitlements import ModelEntitlement, ModelRefused, check_choice
from tests.chat_fixtures import TAGS, USAGE, World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, OpenAIRecorder, router, sse
from tests.test_api import Harness, api
from tests.test_config import ENV, write_config
from tests.test_model_catalogue import CLAUDE, DEEPSEEK, fixed_choice
from tests.test_openrouter import CONFIG as OPENROUTER

__all__ = ["api"]  # fixture reused from the API tests

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
        "System.", [], [], "Capacity?", ModelChoice(DEEPSEEK, True)
    )
    text = "".join([part async for part in stream])
    assert text == "Capacity grew [1] in 2025."
    assert stream.usage is not None and stream.usage.tokens_out == USAGE["completion_tokens"]
    assert "reasoning_effort" not in recorder.bodies()[0]  # thinking on: provider default


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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixed_choice(monkeypatch, ModelChoice(DEEPSEEK, True))
    recorder = OpenAIRecorder(SCALEWAY_REASONING_STREAM)
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, recorder),
        package_tags=TAGS,
    )
    capsys.readouterr()
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    logged = capsys.readouterr()

    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == (
        "Capacity grew [1] in 2025."
    )
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert (done.model, done.reasoning) == (DEEPSEEK, True)
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
    assert json.loads(audit)["model"] == DEEPSEEK


@pytest.mark.skipif(
    not hasattr(Message, "reasoning"), reason="messages.reasoning arrives with P1a-04"
)
async def test_reasoning_is_stored_on_the_message(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_choice(monkeypatch, ModelChoice(DEEPSEEK, True))
    orch = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, OpenAIRecorder(SCALEWAY_REASONING_STREAM)),
        package_tags=TAGS,
    )
    events = [e async for e in await orch.answer(world.ctx, world.conversation_id, "Capacity?")]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    reasoning = await world.admin.fetchval(
        "SELECT reasoning FROM messages WHERE id = $1", done.message_id
    )
    assert reasoning is True


# --- badge data in the API response -------------------------------------------------------


async def test_badge_data_in_stream_and_conversation(
    api: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_choice(monkeypatch, ModelChoice(DEEPSEEK, True))
    conversation = await api.conversation()
    api.recorder.add(SCALEWAY_REASONING_STREAM)
    response = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "Capacity?"}
    )
    assert response.status_code == 200
    assert_no_reasoning(response.text)
    done = json.loads(response.text.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert (done["model"], done["reasoning"]) == (DEEPSEEK, True)

    detail = (await api.request("GET", f"/conversations/{conversation}")).json()
    assert_no_reasoning(json.dumps(detail))
    user, assistant = detail["messages"]
    assert (user["model"], user["reasoning"]) == (None, None)
    assert assistant["model"] == DEEPSEEK
    expected = True if hasattr(Message, "reasoning") else None  # column from P1a-04
    assert assistant["reasoning"] is expected


# --- a model without a switch ------------------------------------------------------------


def test_reasoning_on_a_model_without_a_switch_is_refused(tmp_path: Any) -> None:
    mistral = load_settings(environ=ENV, config_dir=write_config(tmp_path))
    ent = ModelEntitlement(("mistral-large-2512",), False, None)
    assert check_choice(mistral, ent, ModelChoice("mistral-large-2512", False)).id
    with pytest.raises(ModelRefused) as excinfo:
        check_choice(mistral, ent, ModelChoice("mistral-large-2512", True))
    assert excinfo.value.code == "reasoning_unsupported"
