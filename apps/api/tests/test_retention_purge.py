"""P1b-14: the retention purge job, its role, and a retention of 0 days ("no history").

Against PostgreSQL: the purge runs as ``askspore_retention`` with each tenant's RLS
scope, so these tests also prove what that role cannot reach.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app import cli
from app.content import worker
from app.content.jobs import claim
from app.core.db import RETENTION_ROLE, session_factory, tenant_role_session
from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.purge import (
    PurgeCounts,
    _purge_tenant,
    purge_retention,
    schedule_purge,
)
from tests.chat_fixtures import World
from tests.fakes import FakeRedis, delta, sse
from tests.test_api import Harness, api
from tests.test_tenancy import Tenant, make_tenant

__all__ = ["api"]  # the fixture, imported for its use here

pytestmark = pytest.mark.usefixtures("database")

TOKEN_HASH = "ab" * 32


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker:  # type: ignore[type-arg]
    return session_factory(engine)


async def history(
    admin: asyncpg.Connection, tenant: Tenant, *, age_days: int, retention_days: int = 30
) -> uuid.UUID:
    """A conversation ``age_days`` old with a question, an answer, a citation and
    feedback; it expires ``retention_days`` after it was created (arranged as owner)."""
    workspace = await admin.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", tenant.id)
    conversation: uuid.UUID = await admin.fetchval(
        "INSERT INTO conversations (tenant_id, user_id, created_at, expires_at, workspace_id, "
        "mode, model, reasoning) VALUES ($1, $2, now() - make_interval(days => $3), "
        "now() - make_interval(days => $3) + make_interval(days => $4), $5, 'corpus_only', "
        "'deepseek-v4.1-flash', false) RETURNING id",
        tenant.id,
        tenant.user_id,
        age_days,
        retention_days,
        workspace,
    )
    await admin.execute(
        "INSERT INTO messages (tenant_id, conversation_id, role, content) "
        "VALUES ($1, $2, 'user', 'Synthetic question?')",
        tenant.id,
        conversation,
    )
    answer = await admin.fetchval(
        "INSERT INTO messages (tenant_id, conversation_id, role, content, outcome) "
        "VALUES ($1, $2, 'assistant', 'Synthetic answer [1].', 'answered') RETURNING id",
        tenant.id,
        conversation,
    )
    source = await admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis) "
        "VALUES ('pdf', 'Synthetic report', 'Synthetic Publisher', 'test') RETURNING id"
    )
    await admin.execute(
        "INSERT INTO citations (tenant_id, message_id, marker, source_id, ragflow_chunk_id, "
        "excerpt) VALUES ($1, $2, 1, $3, 'chunk-1', 'Synthetic excerpt.')",
        tenant.id,
        answer,
        source,
    )
    await admin.execute(
        "INSERT INTO feedback (tenant_id, message_id, user_id, rating) VALUES ($1, $2, $3, 'up')",
        tenant.id,
        answer,
        tenant.user_id,
    )
    return conversation


async def revoked(admin: asyncpg.Connection, tenant: Tenant, *, expired: bool) -> str:
    digest = uuid.uuid4().hex * 2
    await admin.execute(
        "INSERT INTO revoked_sessions (tenant_id, token_sha256, user_id, expires_at) "
        "VALUES ($1, $2, $3, now() + $4 * interval '1 hour')",
        tenant.id,
        digest,
        tenant.user_id,
        -1 if expired else 1,
    )
    return digest


async def download(admin: asyncpg.Connection, tenant: Tenant, *, age_days: int) -> uuid.UUID:
    workspace = await admin.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", tenant.id)
    source = await admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis) "
        "VALUES ('pdf', 'Synthetic report', 'Synthetic Publisher', 'test') RETURNING id"
    )
    row: uuid.UUID = await admin.fetchval(
        "INSERT INTO downloads (tenant_id, user_id, workspace_id, source_id, token_sha256, "
        "created_at, expires_at) VALUES ($1, $2, $3, $4, $5, now() - make_interval(days => $6), "
        "now() - make_interval(days => $6) + interval '1 minute') RETURNING id",
        tenant.id,
        tenant.user_id,
        workspace,
        source,
        uuid.uuid4().hex * 2,
        age_days,
    )
    return row


async def rows(admin: asyncpg.Connection, tenant_id: uuid.UUID) -> dict[str, int]:
    counts = {}
    for table in (
        "conversations",
        "messages",
        "citations",
        "feedback",
        "revoked_sessions",
        "downloads",
    ):
        counts[table] = await admin.fetchval(
            f"SELECT count(*) FROM {table} WHERE tenant_id = $1", tenant_id
        )
    return counts


@pytest.fixture
async def two_tenants(admin_conn: asyncpg.Connection) -> AsyncIterator[tuple[Tenant, Tenant]]:
    yield await make_tenant(admin_conn), await make_tenant(admin_conn)


async def test_purge_deletes_exactly_the_expired_rows(
    admin_conn: asyncpg.Connection,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, b = two_tenants
    gone = await history(admin_conn, a, age_days=31)
    shortened = await history(admin_conn, a, age_days=8, retention_days=7)
    kept = await history(admin_conn, a, age_days=29)
    await revoked(admin_conn, a, expired=True)
    live_revocation = await revoked(admin_conn, a, expired=False)
    old_download = await download(admin_conn, a, age_days=91)
    recent_download = await download(admin_conn, a, age_days=89)
    await history(admin_conn, b, age_days=40)
    await revoked(admin_conn, b, expired=True)
    await download(admin_conn, b, age_days=100)
    downloads_audit = await admin_conn.fetchval("SELECT count(*) FROM audit_events")

    purged = {p.tenant_id: p.counts for p in await purge_retention(factory, downloads_days=90)}

    assert purged[a.id] == PurgeCounts(
        citations=2,
        feedback=2,
        messages=4,
        conversations=2,
        revoked_sessions=1,
        downloads=1,
    )
    assert purged[b.id].total == 1 + 1 + 2 + 1 + 1 + 1
    remaining = {r["id"] for r in await admin_conn.fetch("SELECT id FROM conversations")}
    assert kept in remaining and gone not in remaining and shortened not in remaining
    assert await rows(admin_conn, a.id) == {
        "conversations": 1,
        "messages": 2,
        "citations": 1,
        "feedback": 1,
        "revoked_sessions": 1,
        "downloads": 1,
    }
    assert await admin_conn.fetchval(
        "SELECT token_sha256 FROM revoked_sessions WHERE tenant_id = $1", a.id
    ) == (live_revocation)
    downloads = {r["id"] for r in await admin_conn.fetch("SELECT id FROM downloads")}
    assert recent_download in downloads and old_download not in downloads
    assert await rows(admin_conn, b.id) == dict.fromkeys(
        ("conversations", "messages", "citations", "feedback", "revoked_sessions", "downloads"), 0
    )
    # Audit events stay (the download audit events among them): the table is append-only.
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_events") == downloads_audit


async def test_a_tenant_scoped_purge_reaches_only_that_tenant(
    admin_conn: asyncpg.Connection,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, b = two_tenants
    await history(admin_conn, a, age_days=31)
    await history(admin_conn, b, age_days=31)
    await revoked(admin_conn, b, expired=True)
    await download(admin_conn, b, age_days=120)
    before_b = await rows(admin_conn, b.id)

    async with tenant_role_session(factory, RETENTION_ROLE, a.id) as session:
        counts = await _purge_tenant(session, 90, dry_run=False)

    assert counts.conversations == 1
    assert (await rows(admin_conn, a.id))["conversations"] == 0
    assert await rows(admin_conn, b.id) == before_b  # RLS: another tenant's rows untouched


async def test_dry_run_counts_and_deletes_nothing(
    admin_conn: asyncpg.Connection,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, _ = two_tenants
    await history(admin_conn, a, age_days=31)
    before = await rows(admin_conn, a.id)

    due = {
        p.tenant_id: p.counts
        for p in await purge_retention(factory, downloads_days=90, dry_run=True)
    }

    assert due[a.id].conversations == 1 and due[a.id].messages == 2
    assert await rows(admin_conn, a.id) == before


async def test_the_retention_role_reads_no_content_and_needs_a_tenant(
    admin_conn: asyncpg.Connection, two_tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = two_tenants
    await history(admin_conn, a, age_days=31)
    conn = admin_conn
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE askspore_app")
        await conn.execute(f"SET LOCAL ROLE {RETENTION_ROLE}")
        for column, table in (
            ("content", "messages"),
            ("excerpt", "citations"),
            ("comment", "feedback"),
            ("title", "conversations"),
            ("email", "users"),
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await conn.fetch(f"SELECT {column} FROM {table}")
        # No tenant scope: the policies match no row, so nothing can be deleted.
        assert await conn.execute("DELETE FROM conversations") == "DELETE 0"
        for table in ("users", "audit_events", "tenant_settings", "workspaces"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await conn.execute(f"DELETE FROM {table}")
    assert (await rows(admin_conn, a.id))["conversations"] == 1


async def test_the_application_role_does_not_inherit_the_retention_role(
    app_conn: asyncpg.Connection,
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM revoked_sessions")


async def test_the_worker_queues_one_purge_a_day_and_runs_it(
    admin_conn: asyncpg.Connection,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    two_tenants: tuple[Tenant, Tenant],
    capsys: pytest.CaptureFixture[str],
) -> None:
    a, _ = two_tenants
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'purge_retention'")
    await history(admin_conn, a, age_days=31)

    first = await schedule_purge(factory)
    assert first is not None
    assert await schedule_purge(factory) is None  # one a day

    ctx = worker.Context(
        factory=factory,
        client=None,  # type: ignore[arg-type]
        tags={},
        content_root=Path("/nonexistent"),
        downloads_retention_days=90,
    )
    while (job := await claim(factory)) is not None and job.id != first:
        await admin_conn.execute("UPDATE jobs SET status = 'failed' WHERE id = $1", job.id)
    if job is not None:  # put it back for run_once
        await admin_conn.execute(
            "UPDATE jobs SET status = 'queued', attempts = 0 WHERE id = $1", job.id
        )
    assert await worker.run_once(factory, worker.handlers(ctx)) is True
    status = await admin_conn.fetchval("SELECT status FROM jobs WHERE id = $1", first)
    assert status == "succeeded"
    assert (await rows(admin_conn, a.id))["conversations"] == 0
    out = capsys.readouterr().out
    assert '"event":"retention.purged"' in out and f'"tenant_id":"{a.id}"' in out
    assert "Synthetic" not in out  # counts only

    # A day later the next one is queued.
    await admin_conn.execute(
        "UPDATE jobs SET created_at = now() - interval '25 hours' WHERE id = $1", first
    )
    assert await schedule_purge(factory) is not None
    await admin_conn.execute("DELETE FROM jobs WHERE type = 'purge_retention'")


def test_cli_purge_needs_a_mode() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["purge"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["purge", "--dry-run", "--run"])
    args = cli.build_parser().parse_args(["purge", "--run", "--wait"])
    assert args.run and args.wait


# --- retention 0: no history ---------------------------------------------------------


@pytest.fixture
async def no_history(admin_conn: asyncpg.Connection) -> AsyncIterator[None]:
    await admin_conn.execute(
        "INSERT INTO tenant_settings (tenant_id, retention_days) VALUES ($1, 0) "
        "ON CONFLICT (tenant_id) DO UPDATE SET retention_days = 0",
        INTERNAL_TENANT_ID,
    )
    yield
    await admin_conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", INTERNAL_TENANT_ID)


async def internal_history(admin: asyncpg.Connection, user_id: uuid.UUID) -> dict[str, int]:
    counts = {}
    for table, where in (
        ("conversations", "user_id = $1"),
        ("messages", "conversation_id IN (SELECT id FROM conversations WHERE user_id = $1)"),
    ):
        counts[table] = await admin.fetchval(f"SELECT count(*) FROM {table} WHERE {where}", user_id)
    counts["citations"] = await admin.fetchval(
        "SELECT count(*) FROM citations WHERE message_id IN (SELECT m.id FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id WHERE c.user_id = $1)",
        user_id,
    )
    return counts


@pytest.mark.usefixtures("no_history")
async def test_zero_retention_leaves_no_rows_after_the_answer(
    api: Harness, world: World, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    await admin_conn.execute("DELETE FROM conversations WHERE user_id = $1", world.user_id)
    created = await api.request("POST", "/conversations")
    assert created.status_code == 201
    body = created.json()
    assert body["no_history"] is True
    conversation = body["id"]
    # Hidden from every read route from the start.
    assert (await api.request("GET", "/conversations")).json() == []
    assert (await api.request("GET", f"/conversations/{conversation}")).status_code == 404

    events = await api.ask(conversation, "What grew in 2025?", "Capacity grew [1].")

    assert [name for name, _ in events][-1] == "done"
    assert await internal_history(admin_conn, world.user_id) == {
        "conversations": 0,
        "messages": 0,
        "citations": 0,
    }
    assert redis.store == {}  # nothing cached for a tenant that keeps no history
    # The audit trail still records that a question was asked (metadata only).
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM audit_events WHERE event = 'chat.query' "
        "AND metadata->>'conversation_id' = $1",
        conversation,
    )
    # The conversation took its one question: asking again finds nothing.
    again = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "And then?"}
    )
    assert again.status_code == 404


@pytest.mark.usefixtures("no_history")
async def test_zero_retention_deletes_after_a_failed_answer_too(
    api: Harness, world: World, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    await admin_conn.execute("DELETE FROM conversations WHERE user_id = $1", world.user_id)
    conversation = (await api.request("POST", "/conversations")).json()["id"]
    api.retriever.error = RuntimeError("synthetic outage")

    events = await api.ask(conversation, "What grew in 2025?")

    assert events[-1] == ("error", {"error_code": "retrieval_unavailable"})
    assert (await internal_history(admin_conn, world.user_id))["conversations"] == 0


@pytest.mark.usefixtures("no_history")
async def test_zero_retention_deletes_when_the_client_leaves_mid_answer(
    api: Harness, world: World, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    await admin_conn.execute("DELETE FROM conversations WHERE user_id = $1", world.user_id)
    conversation = (await api.request("POST", "/conversations")).json()["id"]
    api.recorder.add(sse(delta("Capacity grew [1]."), delta(" And then some.")))
    orchestrator = api.app.state.orchestrator

    events = await orchestrator.answer(world.ctx, uuid.UUID(conversation), "What grew in 2025?")
    first = await events.__anext__()
    await events.aclose()  # the client left after the first event

    assert type(first).__name__ != "DoneEvent"
    assert (await internal_history(admin_conn, world.user_id))["conversations"] == 0


@pytest.mark.usefixtures("no_history")
async def test_a_stale_no_history_conversation_takes_no_question(
    api: Harness, world: World, admin_conn: asyncpg.Connection, redis: FakeRedis
) -> None:
    conversation = (await api.request("POST", "/conversations")).json()["id"]
    await admin_conn.execute(
        "UPDATE conversations SET created_at = now() - interval '11 minutes', "
        "expires_at = now() - interval '11 minutes' WHERE id = $1",
        uuid.UUID(conversation),
    )
    response = await api.request(
        "POST", f"/conversations/{conversation}/messages", json={"question": "Late?"}
    )
    assert response.status_code == 404
    await admin_conn.execute("DELETE FROM conversations WHERE id = $1", uuid.UUID(conversation))


async def test_the_purge_leaves_a_streaming_no_history_conversation_alone(
    admin_conn: asyncpg.Connection,
    factory: async_sessionmaker,  # type: ignore[type-arg]
    two_tenants: tuple[Tenant, Tenant],
) -> None:
    a, _ = two_tenants
    fresh = await history(admin_conn, a, age_days=0, retention_days=0)
    await purge_retention(factory, downloads_days=90)
    assert await admin_conn.fetchval("SELECT count(*) FROM conversations WHERE id = $1", fresh)
    await admin_conn.execute(
        "UPDATE conversations SET created_at = now() - interval '11 minutes', "
        "expires_at = now() - interval '11 minutes' WHERE id = $1",
        fresh,
    )
    await purge_retention(factory, downloads_days=90)
    assert not await admin_conn.fetchval("SELECT count(*) FROM conversations WHERE id = $1", fresh)
