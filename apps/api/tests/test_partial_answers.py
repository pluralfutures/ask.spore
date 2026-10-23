"""P1c-09: chat history completeness. A cut-off answer keeps its note after a reload; an
answer the user stopped, the client left or the model broke off mid-stream is kept with
its question, flagged partial; a tenant that keeps no history still keeps no row."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx2
import pytest

from app.chat.orchestrator import DoneEvent, ErrorEvent, TokenEvent
from tests.chat_fixtures import World
from tests.fakes import FakeRedis, delta, sse
from tests.test_api import Harness, api
from tests.test_reasoning import CUT_OFF_STREAM
from tests.test_retention_purge import internal_history, no_history

__all__ = ["api", "no_history"]  # fixtures, imported for their use here

QUESTION = "What grew in 2025?"


def broken_stream(*texts: str) -> httpx2.Response:
    """An answer stream that sends ``texts`` and then breaks (a read error mid-body)."""

    async def body() -> AsyncIterator[bytes]:
        for text in texts:
            yield f"data: {json.dumps(delta(text))}\n\n".encode()
        raise httpx2.ReadError("synthetic connection reset")

    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body())


def hanging_stream(text: str, sent: asyncio.Event) -> httpx2.Response:
    """An answer stream that sends ``text`` and then waits forever (a stalled model)."""

    async def body() -> AsyncIterator[bytes]:
        yield f"data: {json.dumps(delta(text))}\n\n".encode()
        sent.set()
        await asyncio.Event().wait()

    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body())


async def stored(api: Harness, conversation: str) -> list[dict[str, Any]]:
    response = await api.request("GET", f"/conversations/{conversation}")
    assert response.status_code == 200, response.text
    messages: list[dict[str, Any]] = response.json()["messages"]
    return messages


async def fresh(api: Harness, world: World, admin: asyncpg.Connection) -> str:
    await admin.execute("DELETE FROM conversations WHERE user_id = $1", world.user_id)
    return await api.conversation()


async def test_a_cut_off_answer_keeps_its_note_after_a_reload(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    conversation = await fresh(api, world, admin_conn)
    api.recorder.add(CUT_OFF_STREAM)
    response = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": QUESTION}
    )
    done = [e for e in response.text.split("\n\n") if e.startswith("event: done")]
    assert done and '"truncated": true' in done[0]

    question, answer = await stored(api, conversation)
    assert (question["role"], question["truncated"], question["partial"]) == ("user", False, False)
    assert (answer["role"], answer["truncated"], answer["partial"]) == ("assistant", True, False)
    assert answer["content"].startswith("Capacity grew")
    # A complete answer carries neither flag.
    await api.ask(conversation, "And in 2024?", "It grew too [1].", rewrite="Growth in 2024?")
    assert [(m["truncated"], m["partial"]) for m in (await stored(api, conversation))[2:]] == [
        (False, False),
        (False, False),
    ]


async def test_a_stopped_answer_is_stored_partial(
    api: Harness, world: World, admin_conn: asyncpg.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    """The web app's "stop" aborts the request: the stream closes after what was shown."""
    conversation = await fresh(api, world, admin_conn)
    api.recorder.add(sse(delta("Capacity grew [1]"), delta(" by twelve percent"), delta(".")))
    orchestrator = api.app.state.orchestrator

    events = await orchestrator.answer(world.ctx, uuid.UUID(conversation), QUESTION)
    first = await events.__anext__()
    assert isinstance(first, TokenEvent)
    await events.aclose()  # stop: the client closes the stream after the first token

    question, answer = await stored(api, conversation)
    assert (question["role"], question["content"]) == ("user", QUESTION)
    assert answer["partial"] is True and answer["truncated"] is False
    assert answer["content"] == first.text == "Capacity grew [1]"
    assert [c["marker"] for c in answer["citations"]] == [1]
    assert answer["unsupported"] is False
    audit = await admin_conn.fetchval(
        "SELECT metadata FROM audit_events WHERE event = 'chat.query' "
        "AND metadata->>'conversation_id' = $1",
        conversation,
    )
    assert json.loads(audit)["status"] == "partial"
    assert json.loads(audit)["error_code"] == "stopped"
    out = capsys.readouterr().out
    assert '"status":"partial"' in out
    assert "Capacity grew" not in out and QUESTION not in out  # metadata only
    # The conversation stays usable, and its next answer is complete.
    events = await api.ask(conversation, "And in 2024?", "It grew too [1].", rewrite="2024?")
    assert events[-1][0] == "done"


async def test_a_disconnect_stores_the_partial_answer(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    """The server cancels the response task when the client goes away (Starlette); the
    turn is stored by a shielded task, whatever the cancellation does next."""
    conversation = await fresh(api, world, admin_conn)
    sent = asyncio.Event()
    api.recorder.replies.append(hanging_stream("Capacity grew [1]", sent))
    orchestrator = api.app.state.orchestrator
    shown: list[Any] = []

    async def client() -> None:
        async for event in await orchestrator.answer(world.ctx, uuid.UUID(conversation), QUESTION):
            shown.append(event)

    task = asyncio.create_task(client())
    await asyncio.wait_for(sent.wait(), 5)
    for _ in range(50):
        if shown:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):  # the shielded store finishes on its own
        if await admin_conn.fetchval(
            "SELECT count(*) FROM messages WHERE conversation_id = $1", uuid.UUID(conversation)
        ):
            break
        await asyncio.sleep(0.02)

    assert [type(e).__name__ for e in shown] == ["TokenEvent"]
    question, answer = await stored(api, conversation)
    assert question["content"] == QUESTION
    assert (answer["content"], answer["partial"]) == ("Capacity grew [1]", True)


async def test_a_corpus_only_answer_stopped_before_its_first_citation_keeps_no_text(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    """Uncited text is held back and never shown; stopped then, nothing of it is stored."""
    conversation = await fresh(api, world, admin_conn)
    api.recorder.replies.append(broken_stream("Uncited held text", " still uncited"))

    events = await api.ask(conversation, QUESTION)

    assert events[-1][0] == "error"
    assert all(name != "token" for name, _ in events)
    question, answer = await stored(api, conversation)
    assert question["content"] == QUESTION
    assert (answer["content"], answer["partial"], answer["citations"]) == ("", True, [])
    assert answer["unsupported"] is True
    assert "Uncited" not in json.dumps(await stored(api, conversation))


async def test_a_model_failure_mid_stream_keeps_the_question_and_the_partial_answer(
    api: Harness, world: World, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    conversation = await fresh(api, world, admin_conn)
    api.recorder.replies.append(broken_stream("Capacity grew [1]", " by twelve"))

    events = await api.ask(conversation, QUESTION)

    names = [name for name, _ in events]
    assert names[-1] == "error" and "token" in names
    question, answer = await stored(api, conversation)
    assert question["content"] == QUESTION
    assert answer["partial"] is True
    assert answer["content"] == "Capacity grew [1] by twelve"
    assert redis.store == {}  # a partial answer is never cached
    # One audit event for the turn, with the model's error code.
    rows = await admin_conn.fetch(
        "SELECT metadata FROM audit_events WHERE event = 'chat.query' "
        "AND metadata->>'conversation_id' = $1",
        conversation,
    )
    assert [json.loads(r["metadata"])["status"] for r in rows] == ["partial"]


async def test_a_failure_before_the_answer_starts_stores_nothing(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    conversation = await fresh(api, world, admin_conn)
    api.retriever.error = RuntimeError("synthetic outage")

    events = await api.ask(conversation, QUESTION)

    assert events[-1] == ("error", {"error_code": "retrieval_unavailable"})
    assert await stored(api, conversation) == []


@pytest.mark.usefixtures("no_history")
async def test_no_history_leaves_no_row_when_stopped(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    conversation = await fresh(api, world, admin_conn)
    api.recorder.add(sse(delta("Capacity grew [1]"), delta(" by twelve percent.")))
    orchestrator = api.app.state.orchestrator

    events = await orchestrator.answer(world.ctx, uuid.UUID(conversation), QUESTION)
    assert isinstance(await events.__anext__(), TokenEvent)
    await events.aclose()

    assert await internal_history(admin_conn, world.user_id) == {
        "conversations": 0,
        "messages": 0,
        "citations": 0,
    }


@pytest.mark.usefixtures("no_history")
async def test_no_history_leaves_no_row_when_the_model_fails_mid_stream(
    api: Harness, world: World, admin_conn: asyncpg.Connection
) -> None:
    conversation = await fresh(api, world, admin_conn)
    api.recorder.replies.append(broken_stream("Capacity grew [1]", " by twelve"))
    orchestrator = api.app.state.orchestrator

    events = [e async for e in await orchestrator.answer(world.ctx, uuid.UUID(conversation), "Q?")]

    assert isinstance(events[-1], ErrorEvent)
    assert not any(isinstance(e, DoneEvent) for e in events)
    assert await internal_history(admin_conn, world.user_id) == {
        "conversations": 0,
        "messages": 0,
        "citations": 0,
    }
