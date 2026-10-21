"""P0-15: /api/v1 endpoints over HTTP, against PostgreSQL with fake retrieval and a
recorded (mocked) Mistral transport."""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import current_tenant_id, db_session
from app.chat.orchestrator import ErrorEvent, Orchestrator
from app.core.config import Settings
from app.core.db import session_factory, set_tenant
from scripts.export_openapi import OPENAPI_PATH, render
from tests.chat_fixtures import World, chunks_for
from tests.fakes import FakeRedis, FakeRetriever, completion, delta, router, sse
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_phase0_auth import TOKEN

ANALYST = "analyst@example.org"
EDITOR = "editor@example.org"


class Harness:
    def __init__(self, app: FastAPI, http: httpx.AsyncClient, world: World) -> None:
        self.app = app
        self.http = http
        self.world = world
        self.retriever = FakeRetriever(chunks_for(world))
        self.recorder = Recorder()

    def wire(self, settings: Settings, engine: AsyncEngine) -> None:
        self.app.state.orchestrator = Orchestrator(
            settings=settings,
            db_factory=self.app.state.db_factory,
            retriever=self.retriever,
            llm=router(settings, self.recorder),
        )

    async def request(
        self, method: str, path: str, *, email: str = ANALYST, **kw: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {TOKEN}", "X-User-Email": email}
        return await self.http.request(method, f"/api/v1{path}", headers=headers, **kw)

    async def conversation(self, email: str = ANALYST) -> str:
        response = await self.request("POST", "/conversations", email=email)
        assert response.status_code == 201
        conversation_id: str = response.json()["id"]
        return conversation_id

    async def ask(
        self, conversation_id: str, question: str, *reply: str, rewrite: str | None = None
    ) -> list[tuple[str, Any]]:
        """Ask; ``rewrite`` is the mocked rewrite reply, needed for follow-up questions."""
        if rewrite is not None:
            self.recorder.add(completion(rewrite))
        if reply:
            self.recorder.add(sse(*(delta(r) for r in reply)))
        response = await self.request(
            "POST", f"/conversations/{conversation_id}/messages", json={"question": question}
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_sse(response.text)


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


class _Settings:
    def __init__(self, real: Settings) -> None:
        from pydantic import SecretStr

        from app.core.config import Secrets

        self.models = real.models
        self.config_dir = real.config_dir
        self.secrets = Secrets(
            mistral_api_key=SecretStr("unused"),
            ragflow_api_key=SecretStr("unused"),
            database_url=SecretStr("unused"),
            redis_url=SecretStr("unused"),
            phase0_bearer_token=SecretStr(TOKEN),
        )


@pytest.fixture
async def api(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis
) -> AsyncIterator[Harness]:
    from app.main import create_app

    app = create_app()
    app.state.settings = _Settings(settings)
    app.state.db_factory = session_factory(engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        harness = Harness(app, http, world)
        harness.wire(settings, engine)
        yield harness


ROUTES = [
    ("GET", "/healthz"),
    ("POST", "/conversations"),
    ("GET", "/conversations"),
    ("GET", f"/conversations/{uuid.uuid4()}"),
    ("DELETE", f"/conversations/{uuid.uuid4()}"),
    ("POST", f"/conversations/{uuid.uuid4()}/messages"),
    ("POST", f"/messages/{uuid.uuid4()}/feedback"),
    ("GET", f"/sources/{uuid.uuid4()}"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("token", [None, "wrong-token-0123456789abcdef0123"])
async def test_every_route_requires_auth(
    api: Harness, method: str, path: str, token: str | None
) -> None:
    headers = {"X-User-Email": ANALYST}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await api.http.request(method, f"/api/v1{path}", headers=headers, json={})
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


async def test_healthz(api: Harness) -> None:
    response = await api.request("GET", "/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


async def test_create_and_list_conversations(api: Harness) -> None:
    response = await api.request("POST", "/conversations")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "title",
        "created_at",
        "expires_at",
        "workspace_id",
        "mode",
        "model",
        "reasoning",
        "notice",
        "notice_text",
    }
    assert (body["notice"], body["notice_text"]) == (None, None)
    created = datetime.fromisoformat(body["created_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=29, hours=23) < expires - created <= timedelta(days=30)

    editors = await api.conversation(email=EDITOR)
    listed = await api.request("GET", "/conversations")
    ids = [c["id"] for c in listed.json()]
    assert body["id"] in ids
    assert editors not in ids  # another user's conversations are never listed
    expired = await api.world.new_conversation(expired=True)
    assert str(expired) not in [
        c["id"] for c in (await api.request("GET", "/conversations")).json()
    ]


async def test_ask_streams_tokens_then_citations_then_done(api: Harness) -> None:
    conversation = await api.conversation()
    events = await api.ask(conversation, "How did capacity change?", "Capacity grew ", "[1].")
    names = [name for name, _ in events]
    assert names[-2:] == ["citations", "done"]
    assert set(names[:-2]) == {"token"} and len(names) >= 3
    assert "".join(d["text"] for n, d in events if n == "token") == "Capacity grew [1]."
    citations = events[-2][1]["citations"]
    assert [c["marker"] for c in citations] == [1]
    assert set(citations[0]) == {
        "marker", "source_id", "chunk_id", "page_or_slide", "excerpt",
        "publisher", "title", "published_on", "canonical_url", "type",
    }  # fmt: skip
    done = events[-1][1]
    assert set(done) == {
        "message_id",
        "unsupported",
        "abstained",
        "cached",
        "tokens_in",
        "tokens_out",
        "model",
        "reasoning",
        "truncated",
    }
    assert done["truncated"] is False
    # Badge data (P1a-11): the tenant default, reasoning off.
    assert (done["model"], done["reasoning"]) == ("deepseek-v4.1-flash", False)
    assert done["unsupported"] is False


async def test_get_conversation_returns_messages_and_citations(api: Harness) -> None:
    conversation = await api.conversation()
    await api.ask(conversation, "How did capacity change?", "Capacity grew [1].")
    response = await api.request("GET", f"/conversations/{conversation}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "How did capacity change?"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    answer = body["messages"][1]
    assert answer["content"] == "Capacity grew [1]."
    assert (answer["unsupported"], answer["abstained"]) == (False, False)
    assert answer["citations"][0]["publisher"] == "Synthetic Institute"
    assert answer["citations"][0]["published_on"] == "2026-03-01"
    # Header data (P1a-12): workspace label and the model's display name.
    assert body["workspace_name"] == "Research"
    assert body["model_display_name"] == "DeepSeek V4.1 Flash"


async def test_ask_abstention_and_unsupported_states_survive_reload(api: Harness) -> None:
    conversation = await api.conversation()
    await api.ask(conversation, "Unsupported?", "No markers here.")
    api.retriever.chunks = []
    events = await api.ask(conversation, "Nothing relevant?", rewrite="nothing relevant")
    assert events[-1][1]["abstained"] is True
    messages = (await api.request("GET", f"/conversations/{conversation}")).json()["messages"]
    flags = [(m["unsupported"], m["abstained"]) for m in messages if m["role"] == "assistant"]
    assert flags == [(True, False), (False, True)]


async def test_ask_rejects_client_supplied_dataset_ids(api: Harness) -> None:
    conversation = await api.conversation()
    response = await api.request(
        "POST",
        f"/conversations/{conversation}/messages",
        json={"question": "Q?", "dataset_ids": ["ds-other-tenant"]},
    )
    assert response.status_code == 422
    assert api.retriever.calls == []


@pytest.mark.parametrize(
    "body",
    [{}, {"question": ""}, {"question": "x" * 4001}, {"question": "Why?\u0000"}],
)
async def test_ask_validates_question(api: Harness, body: dict[str, Any]) -> None:
    conversation = await api.conversation()
    response = await api.request("POST", f"/conversations/{conversation}/messages", json=body)
    assert response.status_code == 422


async def test_other_users_conversation_is_not_found(api: Harness) -> None:
    editors = await api.conversation(email=EDITOR)
    for method, path, kw in [
        ("GET", f"/conversations/{editors}", {}),
        ("DELETE", f"/conversations/{editors}", {}),
        ("POST", f"/conversations/{editors}/messages", {"json": {"question": "Q?"}}),
    ]:
        response = await api.request(method, path, **kw)
        assert response.status_code == 404, (method, path)
    assert api.retriever.calls == []


async def test_ask_without_retriever_is_503(api: Harness) -> None:
    conversation = await api.conversation()
    del api.app.state.orchestrator
    response = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "Q?"}
    )
    assert response.status_code == 503


async def test_delete_is_a_hard_delete(api: Harness) -> None:
    conversation = await api.conversation()
    events = await api.ask(conversation, "Q?", "Grew [1].")
    message_id = events[-1][1]["message_id"]
    await api.request("POST", f"/messages/{message_id}/feedback", json={"rating": "up"})

    response = await api.request("DELETE", f"/conversations/{conversation}")
    assert response.status_code == 204
    assert (await api.request("GET", f"/conversations/{conversation}")).status_code == 404
    admin = api.world.admin
    for table, column in [("messages", "conversation_id"), ("conversations", "id")]:
        count = await admin.fetchval(
            f"SELECT count(*) FROM {table} WHERE {column} = $1", uuid.UUID(conversation)
        )
        assert count == 0, table
    for table in ("citations", "feedback"):
        count = await admin.fetchval(
            f"SELECT count(*) FROM {table} WHERE message_id = $1", uuid.UUID(message_id)
        )
        assert count == 0, table
    assert (await api.request("DELETE", f"/conversations/{conversation}")).status_code == 404


async def test_conversation_older_than_30_days_is_not_returned_by_any_read_route(
    api: Harness,
) -> None:
    """P1a-16: read-time expiry, pending the Phase 1b purge job. A conversation with a
    message, a citation and feedback, aged past 30 days, is gone from every route that
    reads conversations or messages, though its rows are still in the database."""
    conversation = await api.conversation()
    events = await api.ask(conversation, "Q?", "Grew [1].")
    message_id = events[-1][1]["message_id"]
    rated = await api.request("POST", f"/messages/{message_id}/feedback", json={"rating": "up"})
    assert rated.status_code == 200
    assert (await api.request("GET", f"/conversations/{conversation}")).status_code == 200

    admin = api.world.admin
    await admin.execute(
        "UPDATE conversations SET created_at = now() - interval '31 days', "
        "expires_at = now() - interval '1 day' WHERE id = $1",
        uuid.UUID(conversation),
    )

    listed = await api.request("GET", "/conversations")
    assert conversation not in [c["id"] for c in listed.json()]
    assert (await api.request("GET", f"/conversations/{conversation}")).status_code == 404
    asked = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "Q?"}
    )
    assert asked.status_code == 404
    rated = await api.request("POST", f"/messages/{message_id}/feedback", json={"rating": "down"})
    assert rated.status_code == 404
    count = await admin.fetchval(
        "SELECT count(*) FROM messages WHERE conversation_id = $1", uuid.UUID(conversation)
    )
    assert count == 2  # hidden at read time, not purged


def _no_commit_on_dependency_exit(app: FastAPI) -> None:
    """Swap ``db_session`` for one whose exit rolls back instead of committing, so a
    write is visible afterwards only if the handler committed it itself (C5)."""

    async def session_without_exit_commit(request: Request) -> AsyncIterator[AsyncSession]:
        async with request.app.state.db_factory() as session:
            await session.begin()
            await set_tenant(session, current_tenant_id(request))
            try:
                yield session
            finally:
                await session.rollback()

    app.dependency_overrides[db_session] = session_without_exit_commit


async def test_writes_are_committed_before_the_response(api: Harness) -> None:
    """C5: create, ask, feedback and delete back to back; each write is visible to an
    independent connection as soon as its response arrives."""
    _no_commit_on_dependency_exit(api.app)
    admin = api.world.admin

    conversation = await api.conversation()
    cid = uuid.UUID(conversation)
    assert await admin.fetchval("SELECT count(*) FROM conversations WHERE id = $1", cid) == 1

    events = await api.ask(conversation, "Q?", "Grew [1].")
    assert events[-1][0] == "done"
    message_id = uuid.UUID(events[-1][1]["message_id"])

    feedback = await api.request("POST", f"/messages/{message_id}/feedback", json={"rating": "up"})
    assert feedback.status_code == 200
    assert await admin.fetchval("SELECT count(*) FROM feedback WHERE message_id = $1", message_id)

    response = await api.request("DELETE", f"/conversations/{conversation}")
    assert response.status_code == 204
    assert await admin.fetchval("SELECT count(*) FROM conversations WHERE id = $1", cid) == 0
    deleted = await admin.fetchval(
        "SELECT count(*) FROM audit_events WHERE event = 'conversation.deleted' "
        "AND metadata->>'conversation_id' = $1",
        conversation,
    )
    assert deleted == 1


async def test_answer_is_committed_before_done_is_sent(api: Harness) -> None:
    """C5: when the client reads ``done`` the message row is already committed."""
    conversation = await api.conversation()
    api.recorder.add(sse(delta("Grew [1].")))
    headers = {"Authorization": f"Bearer {TOKEN}", "X-User-Email": ANALYST}
    seen_at_done = None
    async with api.http.stream(
        "POST",
        f"/api/v1/conversations/{conversation}/messages",
        json={"question": "Q?"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            if "event: done" in buffer and seen_at_done is None:
                seen_at_done = await api.world.admin.fetchval(
                    "SELECT count(*) FROM messages WHERE conversation_id = $1 "
                    "AND role = 'assistant'",
                    uuid.UUID(conversation),
                )
    assert seen_at_done == 1


async def test_feedback_upserts_per_user(api: Harness) -> None:
    conversation = await api.conversation()
    events = await api.ask(conversation, "Q?", "Grew [1].")
    message_id = events[-1][1]["message_id"]
    first = await api.request("POST", f"/messages/{message_id}/feedback", json={"rating": "up"})
    assert first.status_code == 200
    assert first.json() == {"message_id": message_id, "rating": "up", "comment": None}
    second = await api.request(
        "POST", f"/messages/{message_id}/feedback", json={"rating": "down", "comment": "Too vague"}
    )
    assert second.json()["rating"] == "down"
    rows = await api.world.admin.fetch(
        "SELECT rating, comment FROM feedback WHERE message_id = $1", uuid.UUID(message_id)
    )
    assert [(r["rating"], r["comment"]) for r in rows] == [("down", "Too vague")]


async def test_feedback_only_on_own_assistant_messages(api: Harness) -> None:
    conversation = await api.conversation()
    await api.ask(conversation, "Q?", "Grew [1].")
    detail = (await api.request("GET", f"/conversations/{conversation}")).json()
    user_message = detail["messages"][0]["id"]
    answer = detail["messages"][1]["id"]
    assert (
        await api.request("POST", f"/messages/{user_message}/feedback", json={"rating": "up"})
    ).status_code == 404
    other = await api.request(
        "POST", f"/messages/{answer}/feedback", email=EDITOR, json={"rating": "up"}
    )
    assert other.status_code == 404
    bad = await api.request("POST", f"/messages/{answer}/feedback", json={"rating": "meh"})
    assert bad.status_code == 422


SECRET = "synthetic-question-7f3a about capacity"
FAIL_WRITES = """
CREATE FUNCTION fail_write() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'synthetic write failure'; END $$;
CREATE TRIGGER fail_write BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION fail_write();
"""


@contextlib.asynccontextmanager
async def _failing_writes(world: World, table: str) -> AsyncIterator[None]:
    """Every insert into ``table`` fails with a non-integrity database error."""
    await world.admin.execute(FAIL_WRITES.format(table=table))
    try:
        yield
    finally:
        await world.admin.execute(f"DROP TRIGGER fail_write ON {table}; DROP FUNCTION fail_write()")


def _assert_no_text(capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    out, err = capfd.readouterr()
    assert SECRET not in out and SECRET not in err and SECRET not in caplog.text
    return out


async def test_feedback_comment_with_control_characters_is_refused(api: Harness) -> None:
    events = await api.ask(await api.conversation(), "Q?", "Grew [1].")
    message_id = events[-1][1]["message_id"]
    response = await api.request(
        "POST", f"/messages/{message_id}/feedback", json={"rating": "up", "comment": "a\u0000"}
    )
    assert response.status_code == 422


async def test_engine_error_carries_no_parameter_values(engine: AsyncEngine) -> None:
    """The app's engine (hide_parameters): PostgreSQL rejects the NUL, and the error's
    message names no bound value."""
    async with engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            await connection.execute(text("SELECT CAST(:v AS text)"), {"v": f"{SECRET}\x00"})
    assert SECRET not in str(caught.value)
    assert "[parameters:" not in str(caught.value)


async def test_nul_question_that_reaches_postgres_leaves_no_text(
    api: Harness, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """The reviewer's case, past the schema: PostgreSQL refuses the NUL in the stored
    question; the turn ends with an error code and the text is logged nowhere."""
    api.recorder.add(sse(delta("Grew [1].")))
    orchestrator: Orchestrator = api.app.state.orchestrator
    conversation = uuid.UUID(await api.conversation())
    events = [
        e async for e in await orchestrator.answer(api.world.ctx, conversation, f"{SECRET}\x00")
    ]
    assert events[-1] == ErrorEvent("database_error")
    out = _assert_no_text(capfd, caplog)
    assert '"error_code":"database_error"' in out
    count = await api.world.admin.fetchval(
        "SELECT count(*) FROM messages WHERE conversation_id = $1", conversation
    )
    assert count == 0


async def test_failing_answer_write_is_an_error_event_without_text(
    api: Harness, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    conversation = await api.conversation()
    async with _failing_writes(api.world, "messages"):
        events = await api.ask(conversation, SECRET, "Grew [1].")
    assert events[-1] == ("error", {"error_code": "database_error"})
    out = _assert_no_text(capfd, caplog)
    assert '"event":"chat.answer"' in out and '"error_code":"database_error"' in out


async def test_failing_feedback_write_is_a_500_code_without_text(
    api: Harness, capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    events = await api.ask(await api.conversation(), "Q?", "Grew [1].")
    message_id = events[-1][1]["message_id"]
    async with _failing_writes(api.world, "feedback"):
        response = await api.request(
            "POST", f"/messages/{message_id}/feedback", json={"rating": "up", "comment": SECRET}
        )
    assert response.status_code == 500
    assert response.json()["detail"] == "database_error"
    assert SECRET not in response.text
    out = _assert_no_text(capfd, caplog)
    (line,) = [json.loads(x) for x in out.splitlines() if '"api.error"' in x]
    assert line["route"] == "/api/v1/messages/{message_id}/feedback"
    assert line["error_code"] == "database_error"


async def test_source_provenance(api: Harness) -> None:
    source_id = next(iter(api.world.sources.values()))
    response = await api.request("GET", f"/sources/{source_id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(source_id),
        "title": "Synthetic Outlook 2026",
        "publisher": "Synthetic Institute",
        "published_on": "2026-03-01",
        "canonical_url": "https://example.org/report",
        "type": "pdf",
        "withdrawn": False,
    }


async def test_source_outside_package_is_not_found(api: Harness) -> None:
    outside = await api.world.admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, tags) "
        "VALUES ('pdf', 'Other package', 'Elsewhere', 'synthetic', ARRAY['client-other']) "
        "RETURNING id"
    )
    assert (await api.request("GET", f"/sources/{outside}")).status_code == 404
    assert (await api.request("GET", f"/sources/{uuid.uuid4()}")).status_code == 404


def test_committed_openapi_schema_is_current() -> None:
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(), (
        "apps/api/openapi.json is stale: run `uv run python -m scripts.export_openapi`"
    )


def test_openapi_documents_the_sse_payloads() -> None:
    schema = json.loads(render())
    components = schema["components"]["schemas"]
    assert set(components["ChatStreamEvents"]["properties"]) == {
        "token",
        "citations",
        "done",
        "error",
    }
    for body in ("AskIn", "FeedbackIn"):
        assert components[body]["additionalProperties"] is False
        assert not {"dataset_ids", "document_ids", "tenant_id"} & set(
            components[body]["properties"]
        )
