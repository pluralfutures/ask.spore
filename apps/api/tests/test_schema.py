"""P0-05 schema v1: isolation and append-only controls, proven against PostgreSQL."""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from types import ModuleType

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import create_engine, session_factory, tenant_session
from app.models import Base
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import API_DIR, MigratedDatabase, migrate

pytestmark = pytest.mark.usefixtures("database")


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "m0001", API_DIR / "alembic" / "versions" / "0001_schema_v1.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Tenant-scoped tables created after schema v1, each with RLS from its first migration.
LATER_TENANT_TABLES = ("tenant_entitlements",)
TENANT_TABLES: tuple[str, ...] = (*_migration().TENANT_TABLES, *LATER_TENANT_TABLES)
ALL_SCOPED = (*TENANT_TABLES, "tenants")


async def _scope(conn: asyncpg.Connection, tenant_id: uuid.UUID | None) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant_id or ""))


@pytest.fixture
async def populated(admin_conn: asyncpg.Connection) -> AsyncIterator[dict[str, uuid.UUID]]:
    """One row in every tenant-scoped table for the internal tenant, plus an empty tenant."""
    other = uuid.uuid4()
    await admin_conn.execute(
        "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Other')",
        other,
        f"o-{other.hex}",
    )
    user = await admin_conn.fetchval(
        "SELECT id FROM users WHERE tenant_id = $1 LIMIT 1", INTERNAL_TENANT_ID
    )
    source = await admin_conn.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis) "
        "VALUES ('pdf', 'Synthetic report', 'Synthetic Publisher', 'test') RETURNING id"
    )
    conversation = await admin_conn.fetchval(
        "INSERT INTO conversations (tenant_id, user_id, title) VALUES ($1, $2, 't') RETURNING id",
        INTERNAL_TENANT_ID,
        user,
    )
    message = await admin_conn.fetchval(
        "INSERT INTO messages (tenant_id, conversation_id, role, content) "
        "VALUES ($1, $2, 'assistant', 'synthetic answer [1]') RETURNING id",
        INTERNAL_TENANT_ID,
        conversation,
    )
    await admin_conn.execute(
        "INSERT INTO citations (tenant_id, message_id, marker, source_id, ragflow_chunk_id, "
        "excerpt) VALUES ($1, $2, 1, $3, 'chunk-1', 'synthetic excerpt')",
        INTERNAL_TENANT_ID,
        message,
        source,
    )
    await admin_conn.execute(
        "INSERT INTO feedback (tenant_id, message_id, user_id, rating) VALUES ($1, $2, $3, 'up')",
        INTERNAL_TENANT_ID,
        message,
        user,
    )
    await admin_conn.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event) VALUES ($1, $2, 'test.event')",
        INTERNAL_TENANT_ID,
        user,
    )
    yield {"other": other, "user": user, "conversation": conversation, "message": message}
    # Cleanup bypasses the append-only trigger only by dropping nothing: audit rows stay,
    # and the other tenant stays referenced by nothing. Chat rows are removed.
    await admin_conn.execute("DELETE FROM conversations WHERE id = $1", conversation)
    await admin_conn.execute("DELETE FROM sources WHERE id = $1", source)


async def test_tenant_tables_list_is_complete(admin_conn: asyncpg.Connection) -> None:
    rows = await admin_conn.fetch(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
    )
    assert {r["table_name"] for r in rows} == set(TENANT_TABLES)


@pytest.mark.parametrize("table", ALL_SCOPED)
async def test_table_has_forced_rls_policy_and_tenant_first_index(
    admin_conn: asyncpg.Connection, table: str
) -> None:
    rls = await admin_conn.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = $1", table
    )
    assert rls is not None and rls["relrowsecurity"] and rls["relforcerowsecurity"]

    policies = await admin_conn.fetch(
        "SELECT qual, with_check FROM pg_policies WHERE tablename = $1", table
    )
    assert len(policies) == 1
    assert "current_setting('app.tenant_id'" in policies[0]["qual"]
    assert policies[0]["qual"] == policies[0]["with_check"]

    first_columns = await admin_conn.fetch(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indrelid "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0] "
        "WHERE c.relname = $1",
        table,
    )
    expected = "id" if table == "tenants" else "tenant_id"
    assert expected in {r["attname"] for r in first_columns}


@pytest.mark.parametrize("table", ALL_SCOPED)
async def test_other_tenant_sees_zero_rows(
    app_conn: asyncpg.Connection, populated: dict[str, uuid.UUID], table: str
) -> None:
    await _scope(app_conn, INTERNAL_TENANT_ID)
    assert await app_conn.fetchval(f"SELECT count(*) FROM {table}") > 0  # positive control

    await _scope(app_conn, populated["other"])
    if table == "tenants":
        # The other tenant sees only its own row, never the internal tenant's.
        rows = await app_conn.fetch("SELECT id FROM tenants")
        assert [r["id"] for r in rows] == [populated["other"]]
    else:
        assert await app_conn.fetchval(f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("table", ALL_SCOPED)
async def test_no_tenant_set_sees_zero_rows(
    app_conn: asyncpg.Connection, populated: dict[str, uuid.UUID], table: str
) -> None:
    assert await app_conn.fetchval(f"SELECT count(*) FROM {table}") == 0
    await _scope(app_conn, None)  # empty string, as after RESET
    assert await app_conn.fetchval(f"SELECT count(*) FROM {table}") == 0


async def test_cannot_write_rows_for_another_tenant(
    app_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    await _scope(app_conn, populated["other"])
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await app_conn.execute(
            "INSERT INTO conversations (tenant_id, user_id) VALUES ($1, $2)",
            INTERNAL_TENANT_ID,
            populated["user"],
        )


async def test_cannot_move_rows_to_another_tenant(
    app_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    await _scope(app_conn, INTERNAL_TENANT_ID)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await app_conn.execute(
            "UPDATE conversations SET tenant_id = $1 WHERE id = $2",
            populated["other"],
            populated["conversation"],
        )


async def test_child_row_cannot_reference_other_tenants_parent(
    admin_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    # Even the owner, bypassing RLS, cannot attach a message to another tenant's conversation.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await admin_conn.execute(
            "INSERT INTO messages (tenant_id, conversation_id, role, content) "
            "VALUES ($1, $2, 'user', 'x')",
            populated["other"],
            populated["conversation"],
        )


async def test_audit_rows_cannot_be_updated_or_deleted_by_app(
    app_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    await _scope(app_conn, INTERNAL_TENANT_ID)
    await app_conn.execute(
        "INSERT INTO audit_events (tenant_id, event) VALUES ($1, 'test.insert')",
        INTERNAL_TENANT_ID,
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE audit_events SET event = 'tampered'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM audit_events")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("TRUNCATE audit_events")


async def test_audit_rows_cannot_be_updated_or_deleted_by_owner(
    admin_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    for statement in (
        "UPDATE audit_events SET event = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="append-only"):
            await admin_conn.execute(statement)
    assert (
        await admin_conn.fetchval("SELECT count(*) FROM audit_events WHERE event = 'tampered'") == 0
    )


async def test_app_role_cannot_bypass_rls(admin_conn: asyncpg.Connection) -> None:
    role = await admin_conn.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'askspore_app'"
    )
    assert role is not None and not role["rolsuper"] and not role["rolbypassrls"]
    owner = await admin_conn.fetchval(
        "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'conversations'"
    )
    assert owner != "askspore_app"


async def test_conversation_retention_capped_at_30_days(
    admin_conn: asyncpg.Connection, populated: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="retention_cap"):
        await admin_conn.execute(
            "INSERT INTO conversations (tenant_id, user_id, expires_at) "
            "VALUES ($1, $2, now() + interval '31 days')",
            INTERNAL_TENANT_ID,
            populated["user"],
        )
    expires_in = await admin_conn.fetchval(
        "SELECT expires_at - created_at FROM conversations WHERE id = $1", populated["conversation"]
    )
    assert expires_in.days == 30


async def test_seeded_internal_tenant_and_users(admin_conn: asyncpg.Connection) -> None:
    tenant = await admin_conn.fetchrow("SELECT id, slug FROM tenants WHERE slug = 'internal'")
    assert tenant is not None and tenant["id"] == INTERNAL_TENANT_ID
    assert str(INTERNAL_TENANT_ID) == _migration().INTERNAL_TENANT_ID
    users = await admin_conn.fetch(
        "SELECT email, display_name FROM users WHERE tenant_id = $1 ORDER BY email",
        INTERNAL_TENANT_ID,
    )
    assert [(u["email"], u["display_name"]) for u in users] == [
        ("analyst@example.org", "Test Analyst"),
        ("editor@example.org", "Test Editor"),
    ]


async def test_models_match_migration(database: MigratedDatabase) -> None:
    engine = create_async_engine(database.sqlalchemy_url)

    def diff(connection: Connection) -> list[object]:
        return list(compare_metadata(MigrationContext.configure(connection), Base.metadata))

    async with engine.connect() as connection:
        assert await connection.run_sync(diff) == []
    await engine.dispose()


async def test_tenant_session_sets_transaction_local_tenant(database: MigratedDatabase) -> None:
    engine = create_engine(database.sqlalchemy_url)
    factory = session_factory(engine)
    async with tenant_session(factory, INTERNAL_TENANT_ID) as session:
        value = await session.scalar(text("SELECT current_setting('app.tenant_id', true)"))
        assert value == str(INTERNAL_TENANT_ID)
    async with factory() as session:
        value = await session.scalar(text("SELECT current_setting('app.tenant_id', true)"))
        assert value in (None, "")
    await engine.dispose()


def test_downgrade_and_upgrade_round_trip(database: MigratedDatabase) -> None:
    migrate(database, "base", down=True)
    migrate(database)
