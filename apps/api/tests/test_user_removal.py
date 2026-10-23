"""P1c-07: resend an invitation, and remove a user with their account data and history.
Over HTTP in OIDC mode, against PostgreSQL as the application and operator roles."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import asyncpg
import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from app.tenancy.termination import KEPT_TABLES, PURGED_TABLES
from app.tenancy.user_removal import (
    KEPT_COLUMNS,
    KNOWN_USER_COLUMNS,
    REMOVED_TABLES,
    unknown_user_columns,
)
from tests.conftest import CONVERSATION_COLUMNS, CONVERSATION_DEFAULTS
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_operator import Console, console, create, owner  # noqa: F401 - fixtures
from tests.test_tenant_admin import add_user, admin_of, as_user, events

pytestmark = pytest.mark.usefixtures("database")

USER_COLUMNS_SQL = (
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE table_schema = 'public' AND (column_name = 'user_id' "
    "OR column_name LIKE '%\\_user\\_id' "
    "OR column_name IN ('created_by', 'proposed_by', 'approved_by')) ORDER BY 1, 2"
)


async def invitation_jobs(admin: asyncpg.Connection, user_id: uuid.UUID) -> int:
    count: int = await admin.fetchval(
        "SELECT count(*) FROM jobs WHERE type = 'send_mail' "
        "AND payload->>'template' = 'invitation' AND payload->>'user_id' = $1",
        str(user_id),
    )
    return count


async def history_for(admin: asyncpg.Connection, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Every kind of row that names the user: a conversation with a message, citation and
    feedback, the user's feedback on another user's answer, a download, a revoked session,
    a sign-in link, an MFA challenge, a prompt version they wrote and a queued mail job."""
    conversation = await admin.fetchval(
        f"INSERT INTO conversations (tenant_id, user_id, title, {CONVERSATION_COLUMNS}) "
        f"VALUES ($1, $2, 'Synthetic', {CONVERSATION_DEFAULTS}) RETURNING id",
        tenant_id,
        user_id,
    )
    answer = await admin.fetchval(
        "INSERT INTO messages (tenant_id, conversation_id, role, content, outcome) "
        "VALUES ($1, $2, 'assistant', 'Synthetic answer [1].', 'answered') RETURNING id",
        tenant_id,
        conversation,
    )
    source = await admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis) "
        "VALUES ('pdf', 'Synthetic report', 'Synthetic Publisher', 'test') RETURNING id"
    )
    await admin.execute(
        "INSERT INTO citations (tenant_id, message_id, marker, source_id, ragflow_chunk_id, "
        "excerpt) VALUES ($1, $2, 1, $3, 'chunk-1', 'Synthetic excerpt.')",
        tenant_id,
        answer,
        source,
    )
    await admin.execute(
        "INSERT INTO feedback (tenant_id, message_id, user_id, rating) VALUES ($1, $2, $3, 'up')",
        tenant_id,
        answer,
        user_id,
    )
    workspace = await admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1 ORDER BY created_at LIMIT 1", tenant_id
    )
    await admin.execute(
        "INSERT INTO downloads (tenant_id, user_id, workspace_id, source_id, token_sha256, "
        "expires_at) VALUES ($1, $2, $3, $4, $5, now() + interval '1 minute')",
        tenant_id,
        user_id,
        workspace,
        source,
        hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
    )
    await admin.execute(
        "INSERT INTO revoked_sessions (tenant_id, token_sha256, user_id, expires_at) "
        "VALUES ($1, $2, $3, now() + interval '1 hour')",
        tenant_id,
        hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        user_id,
    )
    await admin.execute(
        "INSERT INTO sign_in_links (tenant_id, user_id, expires_at, binding_hash) "
        "VALUES ($1, $2, now() + interval '15 minutes', $3)",
        tenant_id,
        user_id,
        hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
    )
    await admin.execute(
        "INSERT INTO mfa_challenges (tenant_id, user_id, expires_at, binding_hash) "
        "VALUES ($1, $2, now() + interval '5 minutes', $3)",
        tenant_id,
        user_id,
        hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
    )
    await admin.execute(
        "INSERT INTO workspace_prompts (tenant_id, workspace_id, version, text, author_user_id) "
        "VALUES ($1, $2, coalesce((SELECT max(version) FROM workspace_prompts "
        "WHERE workspace_id = $2), 0) + 1, 'Synthetic instructions.', $3)",
        tenant_id,
        workspace,
        user_id,
    )
    await admin.execute(
        "INSERT INTO jobs (type, payload, created_by) VALUES ('send_mail', $1::jsonb, $2)",
        json.dumps(
            {"template": "consent_notice", "tenant_id": str(tenant_id), "user_id": str(user_id)}
        ),
        user_id,
    )
    await admin.execute(
        "INSERT INTO audit_events (tenant_id, actor_user_id, event, metadata) "
        "VALUES ($1, $2, 'auth.login', '{}'::jsonb)",
        tenant_id,
        user_id,
    )


async def rows_naming(admin: asyncpg.Connection, user_id: uuid.UUID) -> dict[str, int]:
    """Rows in every table whose user column holds ``user_id`` (information_schema)."""
    found: dict[str, int] = {}
    for table, column in await admin.fetch(USER_COLUMNS_SQL):
        count = await admin.fetchval(
            f'SELECT count(*) FROM "{table}" WHERE "{column}" = $1',
            user_id,
        )
        if count:
            found[f"{table}.{column}"] = count
    users = await admin.fetchval("SELECT count(*) FROM users WHERE id = $1", user_id)
    if users:
        found["users.id"] = users
    jobs = await admin.fetchval(
        "SELECT count(*) FROM jobs WHERE payload->>'user_id' = $1", str(user_id)
    )
    if jobs:
        found["jobs.payload"] = jobs
    return found


# --- what removal knows -------------------------------------------------------------------


async def test_removal_knows_every_column_that_names_a_user(
    admin_conn: asyncpg.Connection,
) -> None:
    listed = {(r["table_name"], r["column_name"]) for r in await admin_conn.fetch(USER_COLUMNS_SQL)}
    assert listed == set(KNOWN_USER_COLUMNS)
    # Its deletions follow termination's table order and keep what termination keeps.
    assert list(REMOVED_TABLES) == [t for t in PURGED_TABLES if t in REMOVED_TABLES]
    assert REMOVED_TABLES[-1] == "users"
    assert {t for t, _ in KEPT_COLUMNS} <= set(KEPT_TABLES)


async def test_an_unknown_user_column_refuses_the_removal(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    await auth.admin.execute("CREATE TABLE p1c07_probe (id int, reviewer_user_id uuid)")
    try:
        response = await browser.delete(f"/api/v1/admin/users/{member.user_id}")
    finally:
        await auth.admin.execute("DROP TABLE p1c07_probe")
    assert response.json() == {"detail": "unknown_user_table"}
    assert await auth.admin.fetchval("SELECT count(*) FROM users WHERE id = $1", member.user_id)


async def test_the_application_role_alone_cannot_delete_users(
    app_conn: asyncpg.Connection, admin_conn: asyncpg.Connection
) -> None:
    """The deletions need the removal role, which the app role takes but does not inherit."""
    await app_conn.execute(f"SET app.tenant_id = '{INTERNAL_TENANT_ID}'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM users WHERE id = $1", uuid.uuid4())
    async with app_conn.transaction():
        await app_conn.execute("SET LOCAL ROLE askspore_user_removal")
        assert await app_conn.fetchval("SELECT count(*) FROM conversations") is not None
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.fetchval("SELECT content FROM messages LIMIT 1")


# --- resend invitation ----------------------------------------------------------------------


async def test_a_tenant_admin_resends_an_invitation_once(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    invited = await add_user(auth.admin, tenant, status="invited")
    assert await invitation_jobs(auth.admin, invited.user_id) == 0

    response = await browser.post(f"/api/v1/admin/users/{invited.user_id}/invitation")

    assert response.status_code == 202, response.text
    assert response.json() == {"user_id": str(invited.user_id), "status": "queued"}
    assert await invitation_jobs(auth.admin, invited.user_id) == 1
    (event,) = await events(auth, "tenant_admin.invitation_resent", tenant.id)
    assert event["actor"] == tenant.user_id and event["after"]["user_id"] == str(invited.user_id)
    # Pressed again while that one waits: still one job, the one already queued.
    again = await browser.post(f"/api/v1/admin/users/{invited.user_id}/invitation")
    assert again.status_code == 202
    assert await invitation_jobs(auth.admin, invited.user_id) == 1


async def test_resend_refuses_an_active_user_and_another_tenants_user(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    active = await add_user(auth.admin, tenant)
    other = await auth.tenant(role="user")
    await auth.admin.execute("UPDATE users SET status = 'invited' WHERE id = $1", other.user_id)

    refused = await browser.post(f"/api/v1/admin/users/{active.user_id}/invitation")
    hidden = await browser.post(f"/api/v1/admin/users/{other.user_id}/invitation")

    assert (refused.status_code, refused.json()) == (422, {"detail": "not_invited"})
    assert hidden.status_code == 404
    assert await invitation_jobs(auth.admin, active.user_id) == 0
    assert await invitation_jobs(auth.admin, other.user_id) == 0


async def test_the_operator_resends_an_invitation_once(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    email = f"admin-{uuid.uuid4().hex[:6]}@client.example"
    invited = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins", json={"email": email, "display_name": "A"}
    )
    user_id = uuid.UUID(invited.json()["user_id"])
    # The first invitation was sent (its job finished).
    await console.auth.admin.execute(
        "UPDATE jobs SET status = 'succeeded' WHERE payload->>'user_id' = $1", str(user_id)
    )

    response = await op.post(f"/api/v1/operator/tenants/{tenant_id}/users/{user_id}/invitation")

    assert response.status_code == 202, response.text
    assert await invitation_jobs(console.auth.admin, user_id) == 2  # the first and this one
    queued = await console.auth.admin.fetchval(
        "SELECT count(*) FROM jobs WHERE status = 'queued' AND payload->>'user_id' = $1",
        str(user_id),
    )
    assert queued == 1
    (event,) = await console.events("operator.invitation_resent", uuid.UUID(tenant_id))
    assert event["operator_id"] == str(await console.operator_id())
    wrong_tenant = await op.post(
        f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/users/{user_id}/invitation"
    )
    assert wrong_tenant.status_code == 404


# --- remove user ------------------------------------------------------------------------------


async def test_removal_leaves_no_row_with_the_users_id_outside_audit_events(
    auth: Auth,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    await auth.idp.provision_user(email=member.email, display_name="M", tenant_id=tenant.id)
    await history_for(auth.admin, tenant.id, member.user_id)
    # Another user's feedback on the member's answer goes with the answer.
    colleague = await add_user(auth.admin, tenant)
    await auth.admin.execute(
        "INSERT INTO feedback (tenant_id, message_id, user_id, rating) SELECT $1, m.id, $2, "
        "'down' FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = $3",
        tenant.id,
        colleague.user_id,
        member.user_id,
    )
    before = await rows_naming(auth.admin, member.user_id)
    assert set(before) >= {
        "conversations.user_id",
        "feedback.user_id",
        "downloads.user_id",
        "revoked_sessions.user_id",
        "sign_in_links.user_id",
        "mfa_challenges.user_id",
        "workspace_prompts.author_user_id",
        "jobs.created_by",
        "jobs.payload",
        "audit_events.actor_user_id",
        "users.id",
    }

    response = await browser.delete(f"/api/v1/admin/users/{member.user_id}")

    assert response.status_code == 204, response.text
    assert await rows_naming(auth.admin, member.user_id) == {
        "audit_events.actor_user_id": before["audit_events.actor_user_id"]
    }
    # The colleague's feedback on the removed answer went with it; the colleague stays.
    assert await rows_naming(auth.admin, colleague.user_id) == {"users.id": 1}
    # The prompt version stays, without its author.
    assert await auth.admin.fetchval(
        "SELECT count(*) FROM workspace_prompts WHERE tenant_id = $1 AND author_user_id IS NULL",
        tenant.id,
    )
    (event,) = await events(auth, "tenant_admin.user_removed", tenant.id)
    assert event["actor"] == tenant.user_id
    assert event["before"] == {"user_id": str(member.user_id), "role": "user", "status": "active"}
    assert event["count"] >= 12
    assert member.email in auth.idp.disabled
    out = capsys.readouterr().out
    assert '"event":"tenant_admin.user_removed"' in out
    assert member.email not in out
    # The removed user's credential no longer opens anything.
    gone = as_user(auth, member.email, tenant.id)
    assert (await gone.get("/api/v1/me")).status_code in (401, 403)
    # The address is free again: the admin can invite it anew.
    invited = await browser.post(
        "/api/v1/admin/users", json={"email": member.email, "display_name": "Back"}
    )
    assert invited.status_code == 201, invited.text
    assert member.email not in auth.idp.disabled


async def test_a_tenant_admin_cannot_remove_another_tenants_user(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    other = await auth.tenant(role="user")
    await history_for(auth.admin, other.id, other.user_id)
    before = await rows_naming(auth.admin, other.user_id)

    response = await browser.delete(f"/api/v1/admin/users/{other.user_id}")

    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})
    assert await rows_naming(auth.admin, other.user_id) == before  # zero rows deleted
    assert other.email not in auth.idp.disabled
    assert await events(auth, "tenant_admin.user_removed", tenant.id) == []
    assert await events(auth, "tenant_admin.user_removed", other.id) == []


async def test_removal_refuses_the_admin_themselves_and_the_last_admin(
    console: Console,  # noqa: F811
) -> None:
    auth_ = console.auth
    tenant, browser = await admin_of(auth_)
    myself = await browser.delete(f"/api/v1/admin/users/{tenant.user_id}")
    assert (myself.status_code, myself.json()) == (422, {"detail": "cannot_remove_self"})

    op = await console.operator()
    last = await op.delete(f"/api/v1/operator/tenants/{tenant.id}/users/{tenant.user_id}")
    assert (last.status_code, last.json()) == (422, {"detail": "last_admin"})
    # A deactivated second admin does not count; an active one does.
    second = await add_user(auth_.admin, tenant, role="tenant_admin", status="deactivated")
    again = await op.delete(f"/api/v1/operator/tenants/{tenant.id}/users/{tenant.user_id}")
    assert again.json() == {"detail": "last_admin"}
    await auth_.admin.execute("UPDATE users SET status = 'active' WHERE id = $1", second.user_id)
    removed = await op.delete(f"/api/v1/operator/tenants/{tenant.id}/users/{tenant.user_id}")
    assert removed.status_code == 204, removed.text
    assert not await auth_.admin.fetchval(
        "SELECT count(*) FROM users WHERE id = $1", tenant.user_id
    )


async def test_the_operator_removes_any_tenants_user_but_no_platform_role(
    console: Console,  # noqa: F811
    owner: Any,  # noqa: F811
) -> None:
    op = await console.operator()
    tenant = await console.auth.tenant(role="user")
    await history_for(console.auth.admin, tenant.id, tenant.user_id)

    response = await op.delete(f"/api/v1/operator/tenants/{tenant.id}/users/{tenant.user_id}")

    assert response.status_code == 204, response.text
    assert await rows_naming(console.auth.admin, tenant.user_id) == {
        "audit_events.actor_user_id": 1
    }
    (event,) = await console.events("operator.user_removed", tenant.id)
    assert event["operator_id"] == str(await console.operator_id())
    assert event["actor"] is None

    # The operator themselves, and an internal user with a content role, are refused.
    operator_id = await console.operator_id()
    themselves = await op.delete(
        f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/users/{operator_id}"
    )
    assert themselves.json() == {"detail": "cannot_remove_self"}
    editor = await console.auth.admin.fetchval(
        "SELECT id FROM users WHERE tenant_id = $1 AND lower(email) = 'analyst@example.org'",
        INTERNAL_TENANT_ID,
    )
    await console.auth.admin.execute(
        "INSERT INTO content_roles (tenant_id, user_id, role) VALUES ($1, $2, 'content_editor') "
        "ON CONFLICT DO NOTHING",
        INTERNAL_TENANT_ID,
        editor,
    )
    try:
        refused = await op.delete(f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/users/{editor}")
    finally:
        await console.auth.admin.execute("DELETE FROM content_roles WHERE user_id = $1", editor)
    assert (refused.status_code, refused.json()) == (422, {"detail": "platform_role"})
    # A user named in the source register keeps their provenance: refused too.
    source = await console.auth.admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, proposed_by) "
        "VALUES ('pdf', 'Synthetic', 'Synthetic Publisher', 'test', $1) RETURNING id",
        editor,
    )
    try:
        author = await op.delete(f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/users/{editor}")
    finally:
        await console.auth.admin.execute("DELETE FROM sources WHERE id = $1", source)
    assert author.json() == {"detail": "register_author"}
    missing = await op.delete(f"/api/v1/operator/tenants/{uuid.uuid4()}/users/{editor}")
    assert missing.status_code == 404


async def test_a_provider_failure_rolls_the_removal_back(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    await history_for(auth.admin, tenant.id, member.user_id)
    before = await rows_naming(auth.admin, member.user_id)
    auth.idp.fail_disable = True
    await auth.idp.provision_user(email=member.email, display_name="M", tenant_id=tenant.id)

    response = await browser.delete(f"/api/v1/admin/users/{member.user_id}")

    assert (response.status_code, response.json()) == (502, {"detail": "provider_not_updated"})
    assert await rows_naming(auth.admin, member.user_id) == before


async def test_a_plain_user_cannot_remove_or_resend(auth: Auth) -> None:  # noqa: F811
    tenant = await auth.tenant(role="user")
    member = await add_user(auth.admin, tenant)
    browser = as_user(auth, tenant.email, tenant.id)
    for method, path in (
        ("DELETE", f"/api/v1/admin/users/{member.user_id}"),
        ("POST", f"/api/v1/admin/users/{member.user_id}/invitation"),
        ("DELETE", f"/api/v1/operator/tenants/{tenant.id}/users/{member.user_id}"),
    ):
        assert (await browser.request(method, path)).status_code == 403
    assert await rows_naming(auth.admin, member.user_id) == {"users.id": 1}


async def test_unknown_user_columns_is_empty_on_the_schema(auth: Auth) -> None:  # noqa: F811
    from sqlalchemy import text

    async with auth.app.state.db_factory() as session:
        await session.execute(text("SET ROLE askspore_user_removal"))
        assert await unknown_user_columns(session) == set()
