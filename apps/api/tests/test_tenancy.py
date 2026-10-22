"""P1a-01: tenants, users and entitlements; the request context and its fail-closed
default. Against PostgreSQL as the application role, so grants and RLS apply."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import asyncpg
import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import db_session
from app.chat.orchestrator import ChatContext, DoneEvent, Orchestrator
from app.core.config import Settings
from app.core.db import session_factory
from app.tenancy.context import resolve_user
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.chat_fixtures import World, chunks_for
from tests.conftest import CONVERSATION_COLUMNS, CONVERSATION_DEFAULTS
from tests.fakes import FakeRedis, FakeRetriever, router
from tests.fakes import OpenAIRecorder as Recorder

pytestmark = pytest.mark.usefixtures("database")


@dataclass
class Tenant:
    id: uuid.UUID
    user_id: uuid.UUID
    email: str


async def make_tenant(
    admin: asyncpg.Connection,
    *,
    status: str = "active",
    user_status: str = "active",
    role: str = "user",
    domain: str = "client.example",
) -> Tenant:
    """A tenant with one user, an entitlements row and one workspace without tags
    (arranged as the owner). Its login policy row comes from revision 0020's trigger."""
    tenant_id = uuid.uuid4()
    email = f"user-{tenant_id.hex[:8]}@{domain}"
    await admin.execute(
        "INSERT INTO tenants (id, slug, display_name, verified_domains, status) "
        "VALUES ($1, $2, 'Synthetic Client', ARRAY[$4], $3)",
        tenant_id,
        f"c-{tenant_id.hex[:12]}",
        status,
        domain,
    )
    await admin.execute(
        "INSERT INTO tenant_entitlements (tenant_id, enabled_models) "
        "VALUES ($1, ARRAY['deepseek-v4.1-flash'])",
        tenant_id,
    )
    user_id = await admin.fetchval(
        "INSERT INTO users (tenant_id, email, display_name, role, status) "
        "VALUES ($1, $2, 'Synthetic User', $3, $4) RETURNING id",
        tenant_id,
        email,
        role,
        user_status,
    )
    await admin.execute(
        "INSERT INTO workspaces (tenant_id, slug, name, default_model) "
        "VALUES ($1, 'default', 'Default', 'deepseek-v4.1-flash')",
        tenant_id,
    )
    return Tenant(tenant_id, user_id, email)


async def _scope(conn: asyncpg.Connection, tenant_id: uuid.UUID | None) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant_id or ""))


# --- schema ----------------------------------------------------------------------------


async def test_internal_tenant_is_a_row_with_entitlements(admin_conn: asyncpg.Connection) -> None:
    tenant = await admin_conn.fetchrow(
        "SELECT slug, display_name, status, verified_domains FROM tenants WHERE id = $1",
        INTERNAL_TENANT_ID,
    )
    assert tenant is not None
    assert (tenant["slug"], tenant["status"], tenant["verified_domains"]) == (
        "internal",
        "active",
        [],
    )
    entitlements = await admin_conn.fetchrow(
        "SELECT * FROM tenant_entitlements WHERE tenant_id = $1", INTERNAL_TENANT_ID
    )
    assert entitlements is not None
    assert entitlements["answer_modes"] == ["corpus_only"]
    assert entitlements["enabled_models"] == ["deepseek-v4.1-flash"]
    assert entitlements["external_models_enabled"] is False
    policy = await admin_conn.fetchrow(
        "SELECT * FROM tenant_login_policy WHERE tenant_id = $1", INTERNAL_TENANT_ID
    )
    assert policy is not None and policy["sign_in_links_enabled"] is True


async def test_seeded_users_are_active_users(admin_conn: asyncpg.Connection) -> None:
    rows = await admin_conn.fetch(
        "SELECT role, status, last_login_at FROM users WHERE tenant_id = $1", INTERNAL_TENANT_ID
    )
    assert rows and all(
        (r["role"], r["status"], r["last_login_at"]) == ("user", "active", None) for r in rows
    )


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE users SET role = 'operator' WHERE tenant_id = $1", "role_valid"),
        ("UPDATE users SET status = 'deleted' WHERE tenant_id = $1", "status_valid"),
        ("UPDATE users SET last_login_method = 'password' WHERE tenant_id = $1", "login_method"),
        ("UPDATE tenants SET status = 'gone' WHERE id = $1", "status_valid"),
        ("UPDATE tenants SET verified_domains = ARRAY['Client.Example'] WHERE id = $1", "domains"),
        ("UPDATE tenants SET slug = 'Bad Slug' WHERE id = $1", "slug_format"),
        (
            "UPDATE tenant_entitlements SET answer_modes = ARRAY['web_search', 'corpus_only'] "
            "WHERE tenant_id = $1",
            "answer_modes_valid",
        ),
        (
            "UPDATE tenant_entitlements SET answer_modes = ARRAY['general_knowledge'] "
            "WHERE tenant_id = $1",
            "answer_modes_valid",
        ),
        (
            "UPDATE tenant_entitlements SET external_spend_cap_cents = -1 WHERE tenant_id = $1",
            "spend_cap",
        ),
    ],
)
async def test_check_constraints(
    admin_conn: asyncpg.Connection, statement: str, constraint: str
) -> None:
    tenant = await make_tenant(admin_conn)
    with pytest.raises(asyncpg.CheckViolationError, match=constraint):
        await admin_conn.execute(statement, tenant.id)


# --- RLS: cross-tenant reads return nothing -----------------------------------------


@pytest.mark.parametrize(
    "query",
    ["SELECT id FROM users", "SELECT tenant_id FROM tenant_entitlements", "SELECT id FROM tenants"],
)
async def test_cross_tenant_read_returns_nothing(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection, query: str
) -> None:
    a = await make_tenant(admin_conn)
    b = await make_tenant(admin_conn)
    await _scope(app_conn, a.id)
    seen = {row[0] for row in await app_conn.fetch(query)}
    assert seen and seen <= {a.id, a.user_id}  # positive control: A sees its own rows
    assert not seen & {b.id, b.user_id}
    by_id = await app_conn.fetchval(
        "SELECT count(*) FROM users WHERE id = $1 OR tenant_id = $2", b.user_id, b.id
    )
    assert by_id == 0  # even naming B's rows directly returns nothing


async def test_no_tenant_context_reads_nothing(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    await make_tenant(admin_conn)
    for table in ("tenants", "users", "tenant_entitlements"):
        assert await app_conn.fetchval(f"SELECT count(*) FROM {table}") == 0


async def test_app_role_cannot_change_entitlements_or_create_tenants(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    a = await make_tenant(admin_conn)
    await _scope(app_conn, a.id)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE tenant_entitlements SET external_models_enabled = true")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute(
            "INSERT INTO tenants (id, slug, display_name) VALUES ($1, 'x-new', 'X')", a.id
        )


# --- request context -------------------------------------------------------------------


async def test_resolve_user_finds_the_user_only_inside_its_tenant(
    admin_conn: asyncpg.Connection, engine: AsyncEngine
) -> None:
    a = await make_tenant(admin_conn, role="tenant_admin")
    b = await make_tenant(admin_conn)
    factory = session_factory(engine)
    context = await resolve_user(factory, a.id, a.email.upper())
    assert context is not None
    assert (context.tenant_id, context.user_id, context.role) == (a.id, a.user_id, "tenant_admin")
    # A's email under B's tenant: invisible, whatever the email.
    assert await resolve_user(factory, b.id, a.email) is None


@pytest.mark.parametrize(
    ("tenant_status", "user_status"),
    [("suspended", "active"), ("active", "deactivated"), ("active", "invited")],
)
async def test_resolve_user_refuses_inactive(
    admin_conn: asyncpg.Connection, engine: AsyncEngine, tenant_status: str, user_status: str
) -> None:
    t = await make_tenant(admin_conn, status=tenant_status, user_status=user_status)
    assert await resolve_user(session_factory(engine), t.id, t.email) is None


async def test_invited_user_resolves_only_when_allowed(
    admin_conn: asyncpg.Connection, engine: AsyncEngine
) -> None:
    t = await make_tenant(admin_conn, user_status="invited")
    context = await resolve_user(session_factory(engine), t.id, t.email, allow_invited=True)
    assert context is not None and context.status == "invited"


@pytest.fixture
async def bare_app(engine: AsyncEngine) -> AsyncIterator[tuple[httpx.AsyncClient, list[str]]]:
    """A route behind db_session with no authentication middleware at all."""
    opened: list[str] = []
    factory = session_factory(engine)

    def counting_factory() -> AsyncSession:
        opened.append("session")
        return factory()

    app = FastAPI()
    app.state.db_factory = counting_factory

    @app.get("/probe")
    async def probe(session: AsyncSession = Depends(db_session)) -> dict[str, int]:
        return {"users": int(await session.scalar(text("SELECT count(*) FROM users")) or 0)}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, opened


async def test_request_without_tenant_context_fails_closed(
    bare_app: tuple[httpx.AsyncClient, list[str]],
) -> None:
    http, opened = bare_app
    response = await http.get("/probe", headers={"X-Tenant-Id": str(INTERNAL_TENANT_ID)})
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}
    assert opened == []  # refused before any transaction was opened


# --- a client tenant's package is its workspaces' tags (P1a-04 replaced the A5 stub) -----


async def test_client_tenant_retrieves_nothing_before_its_workspace_has_tags(
    settings: Settings,
    engine: AsyncEngine,
    world: World,
    redis: FakeRedis,
    admin_conn: asyncpg.Connection,
) -> None:
    client = await make_tenant(admin_conn)
    conversation = await admin_conn.fetchval(
        f"INSERT INTO conversations (tenant_id, user_id, {CONVERSATION_COLUMNS}) "
        f"VALUES ($1, $2, {CONVERSATION_DEFAULTS}) RETURNING id",
        client.id,
        client.user_id,
    )
    retriever = FakeRetriever(chunks_for(world))
    recorder = Recorder()
    orchestrator = Orchestrator(
        settings=settings,
        db_factory=session_factory(engine),
        retriever=retriever,
        llm=router(settings, recorder),
    )
    events = await orchestrator.answer(
        ChatContext(tenant_id=client.id, user_id=client.user_id), conversation, "Capacity?"
    )
    done = [e async for e in events][-1]
    assert isinstance(done, DoneEvent) and done.abstained
    assert retriever.calls == []  # no retrieval, so no dataset ID was ever sent
    assert recorder.requests == []
