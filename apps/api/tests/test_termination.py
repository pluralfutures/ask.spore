"""P1b-14: the termination purge of one tenant and its certificate of deletion."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.core import cache
from app.core.db import create_engine, session_factory
from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.termination import KEPT_TABLES, TerminationError, terminate_tenant
from tests.conftest import MigratedDatabase
from tests.fakes import FakeRedis
from tests.test_retention_purge import download, history, revoked
from tests.test_tenancy import Tenant, make_tenant

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
async def owner(database: MigratedDatabase) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.sqlalchemy_url)
    yield session_factory(engine)
    await engine.dispose()


@pytest.fixture
def redis() -> AsyncIterator[FakeRedis]:
    fake = FakeRedis()
    cache.configure(fake)
    yield fake  # type: ignore[misc]
    cache.configure(None)


async def tenant_tables(admin: asyncpg.Connection) -> list[str]:
    rows = await admin.fetch(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'tenant_id' ORDER BY table_name"
    )
    return [r["table_name"] for r in rows]


async def counts(admin: asyncpg.Connection, tenant_id: uuid.UUID) -> dict[str, int]:
    return {
        table: await admin.fetchval(
            f"SELECT count(*) FROM {table} WHERE tenant_id = $1",
            tenant_id,
        )
        for table in await tenant_tables(admin)
    }


async def populate(admin: asyncpg.Connection, tenant: Tenant, redis: FakeRedis) -> None:
    """History, sessions, downloads, settings, a prompt, a notice, usage, an audit event,
    a mail job and cached answers for ``tenant``."""
    await history(admin, tenant, age_days=2)
    await history(admin, tenant, age_days=40)
    await revoked(admin, tenant, expired=False)
    await download(admin, tenant, age_days=3)
    await admin.execute(
        "INSERT INTO tenant_settings (tenant_id, retention_days) VALUES ($1, 7)", tenant.id
    )
    workspace = await admin.fetchval("SELECT id FROM workspaces WHERE tenant_id = $1", tenant.id)
    await admin.execute(
        "INSERT INTO workspace_prompts (tenant_id, workspace_id, version, text, author_user_id) "
        "VALUES ($1, $2, 1, 'Synthetic instructions.', $3)",
        tenant.id,
        workspace,
        tenant.user_id,
    )
    await admin.execute(
        "INSERT INTO operator_notices (tenant_id, kind) VALUES ($1, 'spend.cap_80')", tenant.id
    )
    await admin.execute(
        "INSERT INTO usage_ledger (tenant_id, month, model, tokens_in, tokens_out, cost_cents) "
        "VALUES ($1, '2026-10-01', 'deepseek-v4.1-flash', 10, 2, 0.5)",
        tenant.id,
    )
    await admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event) VALUES ($1, $2, 'test.event')",
        tenant.id,
        tenant.user_id,
    )
    await admin.execute(
        "INSERT INTO jobs (type, payload) VALUES ('send_mail', $1::jsonb)",
        json.dumps(
            {"template": "invitation", "tenant_id": str(tenant.id), "user_id": str(tenant.user_id)}
        ),
    )
    for n in range(3):
        await cache.set(tenant.id, f"answer:corpus_only:{n}", "{}", 60)


async def test_termination_leaves_no_rows_for_the_tenant_and_writes_the_certificate(
    admin_conn: asyncpg.Connection,
    owner: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    tmp_path: Path,
) -> None:
    gone, other = await make_tenant(admin_conn), await make_tenant(admin_conn)
    await populate(admin_conn, gone, redis)
    await populate(admin_conn, other, redis)
    # P2B-05: a cached workspace summary goes with the rest of the tenant's cache.
    await cache.set(gone.id, f"workspace_summary:{uuid.uuid4()}", "{}", 60)
    other_before = await counts(admin_conn, other.id)
    gone_before = await counts(admin_conn, gone.id)
    slug = await admin_conn.fetchval("SELECT slug FROM tenants WHERE id = $1", gone.id)

    done = await terminate_tenant(owner, slug=slug, confirm=slug, content_root=tmp_path)

    after = await counts(admin_conn, gone.id)
    assert {t: n for t, n in after.items() if n} == {
        t: gone_before[t] for t in KEPT_TABLES if gone_before.get(t)
    }
    assert set(after) - set(KEPT_TABLES) and all(
        after[t] == 0 for t in after if t not in KEPT_TABLES
    )
    assert await counts(admin_conn, other.id) == other_before  # none missing for others
    tenant = await admin_conn.fetchrow(
        "SELECT status, verified_domains FROM tenants WHERE id = $1", gone.id
    )
    assert (tenant["status"], tenant["verified_domains"]) == ("suspended", [])
    assert not await admin_conn.fetchval(
        "SELECT count(*) FROM jobs WHERE payload->>'tenant_id' = $1", str(gone.id)
    )
    assert await admin_conn.fetchval(
        "SELECT count(*) FROM jobs WHERE payload->>'tenant_id' = $1", str(other.id)
    )
    assert not [k for k in redis.store if k.startswith(f"t:{gone.id}:")]
    assert len([k for k in redis.store if k.startswith(f"t:{other.id}:")]) == 3

    # The certificate's figures are the rows that were there.
    body = json.loads(done.certificate_path.read_text())
    assert done.certificate_path.parent == tmp_path / "certificates"
    assert body["certificate_number"] == done.certificate_number
    assert body["client"]["slug"] == slug
    assert body["date_of_deletion"] == datetime.now(UTC).date().isoformat()
    assert body["method"] == "Automated termination purge (P1b-14)"
    deleted = body["deleted"]
    assert deleted["user_accounts_application"] == gone_before["users"] == 1
    assert deleted["conversations"] == gone_before["conversations"] == 2
    assert deleted["messages"] == gone_before["messages"] == 4
    assert deleted["feedback_entries"] == gone_before["feedback"] == 2
    assert deleted["download_records"] == gone_before["downloads"] == 1
    assert deleted["workspaces_and_settings"] == (
        gone_before["workspaces"]
        + gone_before["workspace_prompts"]
        + gone_before["tenant_settings"]
        + gone_before["tenant_login_policy"]
        + gone_before["tenant_entitlements"]
    )
    assert deleted["cached_answers_removed"] == 4  # three answers and the P2B-05 summary
    assert deleted["jobs"] == 1
    assert deleted["user_accounts_identity_service"] is None  # manual step
    assert body["table_counts"] == {t: gone_before[t] for t in body["table_counts"]}
    assert body["retained"]["audit_records"]["count"] == gone_before["audit_events"]
    assert body["retained"]["usage_and_spend"]["usage_ledger_rows"] == 1
    assert "Authentik" in body["manual_steps"][0]
    # No personal data in the certificate: no address, no question or answer text.
    text = done.certificate_path.read_text()
    assert gone.email not in text and "Synthetic question" not in text

    # Audited at the platform level, with the certificate's number.
    event = await admin_conn.fetchrow(
        "SELECT metadata FROM audit_events WHERE tenant_id = $1 AND event = 'tenant.purged' "
        "ORDER BY created_at DESC LIMIT 1",
        INTERNAL_TENANT_ID,
    )
    metadata = json.loads(event["metadata"])
    assert metadata["certificate"] == done.certificate_number
    assert metadata["after"] == {"status": "suspended", "verified_domains": []}
    assert metadata["count"] == done.total


@pytest.mark.parametrize(
    ("slug", "confirm", "code"),
    [
        ("internal", "internal", "internal_tenant"),
        ("no-such-tenant", "no-such-tenant", "no_tenant"),
        ("x", "y", "confirmation_mismatch"),
    ],
)
async def test_termination_refuses(
    owner: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    tmp_path: Path,
    slug: str,
    confirm: str,
    code: str,
) -> None:
    with pytest.raises(TerminationError) as refused:
        await terminate_tenant(owner, slug=slug, confirm=confirm, content_root=tmp_path)
    assert refused.value.code == code
    assert not (tmp_path / "certificates").exists()


async def test_termination_refuses_while_a_tenant_table_is_unknown(
    admin_conn: asyncpg.Connection,
    owner: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    tmp_path: Path,
) -> None:
    tenant = await make_tenant(admin_conn)
    slug = await admin_conn.fetchval("SELECT slug FROM tenants WHERE id = $1", tenant.id)
    await admin_conn.execute("CREATE TABLE synthetic_new_table (tenant_id uuid)")
    try:
        with pytest.raises(TerminationError) as refused:
            await terminate_tenant(owner, slug=slug, confirm=slug, content_root=tmp_path)
    finally:
        await admin_conn.execute("DROP TABLE synthetic_new_table")
    assert refused.value.code == "unknown_tenant_table"
    assert (await counts(admin_conn, tenant.id))["users"] == 1


async def test_a_failed_audit_write_leaves_everything_and_no_certificate(
    admin_conn: asyncpg.Connection,
    owner: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await make_tenant(admin_conn)
    slug = await admin_conn.fetchval("SELECT slug FROM tenants WHERE id = $1", tenant.id)

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr("app.tenancy.termination.record", fail)
    with pytest.raises(RuntimeError):
        await terminate_tenant(owner, slug=slug, confirm=slug, content_root=tmp_path)
    assert (await counts(admin_conn, tenant.id))["users"] == 1
    assert list((tmp_path / "certificates").iterdir()) == []


def test_cli_tenant_purge_needs_the_slug_twice() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["tenant", "purge", "--slug", "c"])
    args = cli.build_parser().parse_args(["tenant", "purge", "--slug", "c", "--confirm", "c"])
    assert (args.slug, args.confirm) == ("c", "c")
