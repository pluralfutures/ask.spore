"""P2A-08: time-boxed support access. Over HTTP in OIDC mode, against PostgreSQL.

Negative cases first: every operator read without an open grant of this tenant, for
this scope and this conversation, is a 404 (no grant, expired, revoked, another
conversation, another tenant, the wrong scope); the database refuses the same reads to
the support role on its own; the operator writes nothing through a grant; nothing of
the viewed conversation reaches a log line, a refusal or an audit event. Then the
tenant admin's side: granting, the list with its states and the operator's reads, the
revocation, and the daily purge closing expired grants."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import pytest

from app.core.db import RETENTION_ROLE, tenant_role_session
from app.support.access import close_expired
from app.tenancy.purge import purge_retention
from tests.conftest import CONVERSATION_COLUMNS, CONVERSATION_DEFAULTS
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_operator import Console, console, owner  # noqa: F401 - fixtures
from tests.test_tenancy import Tenant
from tests.test_tenant_admin import add_user, admin_of, as_user

pytestmark = pytest.mark.usefixtures("database")

# Synthetic and unique, so their absence from logs is meaningful.
QUESTION = "Synthetic support question about kelp-fed shrimp yields {}?"
ANSWER = "Synthetic support answer about tidal aquaculture {} [1]."
EXCERPT = "Synthetic support excerpt on estuary nutrient loads {}."
NOTE = "Synthetic note: please check why answers cite nothing {}."


class Support:
    def __init__(self, harness: Console) -> None:
        self.console = harness
        self.auth = harness.auth
        self.admin = harness.auth.admin

    async def conversation(self, tenant: Tenant, user_id: uuid.UUID | None = None) -> uuid.UUID:
        """A conversation with one question, one cited answer, and texts unique to it."""
        tag = uuid.uuid4().hex[:10]
        conversation: uuid.UUID = await self.admin.fetchval(
            f"INSERT INTO conversations (tenant_id, user_id, title, {CONVERSATION_COLUMNS}) "
            f"VALUES ($1, $2, 'Synthetic title {tag}', {CONVERSATION_DEFAULTS}) RETURNING id",
            tenant.id,
            user_id or tenant.user_id,
        )
        await self.admin.execute(
            "INSERT INTO messages (tenant_id, conversation_id, role, content, created_at) "
            "VALUES ($1, $2, 'user', $3, now() - interval '1 second')",
            tenant.id,
            conversation,
            QUESTION.format(tag),
        )
        message = await self.admin.fetchval(
            "INSERT INTO messages (tenant_id, conversation_id, role, content) "
            "VALUES ($1, $2, 'assistant', $3) RETURNING id",
            tenant.id,
            conversation,
            ANSWER.format(tag),
        )
        source = await self.admin.fetchval(
            "INSERT INTO sources (type, title, publisher, licence_basis) "
            "VALUES ('pdf', 'Synthetic Estuary Report', 'Synthetic Institute', 'test') "
            "RETURNING id"
        )
        await self.admin.execute(
            "INSERT INTO citations (tenant_id, message_id, marker, source_id, ragflow_chunk_id, "
            "page_or_slide, excerpt) VALUES ($1, $2, 1, $3, 'chunk-synthetic', 4, $4)",
            tenant.id,
            message,
            source,
            EXCERPT.format(tag),
        )
        return conversation

    async def texts(self, conversation: uuid.UUID) -> list[str]:
        rows = await self.admin.fetch(
            "SELECT content FROM messages WHERE conversation_id = $1", conversation
        )
        excerpts = await self.admin.fetch(
            "SELECT c.excerpt FROM citations c JOIN messages m ON m.id = c.message_id "
            "WHERE m.conversation_id = $1",
            conversation,
        )
        return [r["content"] for r in rows] + [r["excerpt"] for r in excerpts]

    async def grant(
        self,
        browser: httpx.AsyncClient,
        *,
        scope: str = "conversation",
        conversation: uuid.UUID | None = None,
        minutes: int = 60,
        note: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "scope": scope,
            "duration_minutes": minutes,
            "note": note or NOTE.format(uuid.uuid4().hex[:6]),
        }
        if conversation is not None:
            body["conversation_id"] = str(conversation)
        response = await browser.post("/api/v1/admin/support-grants", json=body)
        assert response.status_code == 201, response.text
        granted: dict[str, Any] = response.json()
        return granted

    async def expire(self, grant_id: str) -> None:
        """Move a grant's window into the past (as the owner; the trigger allows nothing
        else, so the row is rewritten with the trigger off for this test only)."""
        await self.admin.execute("ALTER TABLE support_grants DISABLE TRIGGER support_grants_guard")
        try:
            await self.admin.execute(
                "UPDATE support_grants SET created_at = created_at - interval '5 hours', "
                "expires_at = expires_at - interval '5 hours' WHERE id = $1",
                uuid.UUID(grant_id),
            )
        finally:
            await self.admin.execute(
                "ALTER TABLE support_grants ENABLE TRIGGER support_grants_guard"
            )


@pytest.fixture
def support(console: Console) -> Support:  # noqa: F811
    return Support(console)


def conversation_path(tenant_id: Any, grant_id: Any, conversation_id: Any) -> str:
    return (
        f"/api/v1/operator/tenants/{tenant_id}/support-grants/{grant_id}"
        f"/conversations/{conversation_id}"
    )


def settings_path(tenant_id: Any, grant_id: Any) -> str:
    return f"/api/v1/operator/tenants/{tenant_id}/support-grants/{grant_id}/settings"


def meta(event: dict[str, Any]) -> dict[str, Any]:
    """An event's metadata, without the actor ``Console.events`` adds."""
    return {k: v for k, v in event.items() if k != "actor"}


def not_found(response: httpx.Response) -> bool:
    return response.status_code == 404 and response.json() == {"detail": "not_found"}


# --- operator reads: refused (negative cases first) ------------------------------------


async def test_without_a_grant_every_operator_read_is_not_found(support: Support) -> None:
    tenant, _ = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    op = await support.console.operator()
    assert not_found(await op.get(conversation_path(tenant.id, uuid.uuid4(), conversation)))
    assert not_found(await op.get(settings_path(tenant.id, uuid.uuid4())))
    assert (await op.get(f"/api/v1/operator/tenants/{tenant.id}/support-grants")).json() == []
    assert await support.console.events("operator.support_viewed", tenant.id) == []


async def test_an_expired_grant_is_not_found(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    grant = await support.grant(admin, conversation=conversation, minutes=15)
    settings = await support.grant(admin, scope="settings", minutes=15)
    await support.expire(grant["id"])
    await support.expire(settings["id"])
    op = await support.console.operator()
    assert not_found(await op.get(conversation_path(tenant.id, grant["id"], conversation)))
    assert not_found(await op.get(settings_path(tenant.id, settings["id"])))
    assert (await op.get(f"/api/v1/operator/tenants/{tenant.id}/support-grants")).json() == []
    states = {g["id"]: g["state"] for g in (await admin.get("/api/v1/admin/support-grants")).json()}
    assert states == {grant["id"]: "expired", settings["id"]: "expired"}


async def test_a_grant_for_another_conversation_is_not_found(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    granted = await support.conversation(tenant)
    other = await support.conversation(tenant)  # the admin's own too, but not granted
    member = await add_user(support.admin, tenant)
    members = await support.conversation(tenant, member.user_id)
    grant = await support.grant(admin, conversation=granted)
    op = await support.console.operator()
    for conversation in (other, members, uuid.uuid4()):
        assert not_found(await op.get(conversation_path(tenant.id, grant["id"], conversation)))
    # The scope is checked too: a conversation grant opens no settings, and back.
    assert not_found(await op.get(settings_path(tenant.id, grant["id"])))
    settings = await support.grant(admin, scope="settings")
    assert not_found(await op.get(conversation_path(tenant.id, settings["id"], granted)))
    assert await support.console.events("operator.support_viewed", tenant.id) == []


async def test_a_grant_of_another_tenant_is_not_found(support: Support) -> None:
    a, _ = await admin_of(support.auth)
    b, b_admin = await admin_of(support.auth)
    b_conversation = await support.conversation(b)
    grant = await support.grant(b_admin, conversation=b_conversation)
    settings = await support.grant(b_admin, scope="settings")
    op = await support.console.operator()
    # B's grant named under A's page: not found, and nothing of B is read or audited.
    assert not_found(await op.get(conversation_path(a.id, grant["id"], b_conversation)))
    assert not_found(await op.get(settings_path(a.id, settings["id"])))
    assert (await op.get(f"/api/v1/operator/tenants/{a.id}/support-grants")).json() == []
    assert await support.console.events("operator.support_viewed", a.id) == []
    assert await support.console.events("operator.support_viewed", b.id) == []
    # Under B's own page the same grant works (positive control).
    assert (await op.get(conversation_path(b.id, grant["id"], b_conversation))).status_code == 200


async def test_a_revoked_grant_stops_the_next_read(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    grant = await support.grant(admin, conversation=conversation)
    op = await support.console.operator()
    path = conversation_path(tenant.id, grant["id"], conversation)
    assert (await op.get(path)).status_code == 200
    revoked = await admin.post(f"/api/v1/admin/support-grants/{grant['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert not_found(await op.get(path))
    again = await admin.post(f"/api/v1/admin/support-grants/{grant['id']}/revoke")
    assert (again.status_code, again.json()["detail"]) == (422, "not_open")
    assert len(await support.console.events("operator.support_viewed", tenant.id)) == 1


async def test_the_grant_check_is_not_only_the_applications(support: Support) -> None:
    """As ``askspore_support`` with the tenant set, the database shows a conversation,
    its messages and citations only while an open grant names it, and the settings
    tables only under an open settings grant."""
    tenant, admin = await admin_of(support.auth)
    granted = await support.conversation(tenant)
    other = await support.conversation(tenant)
    conn = support.admin

    async def visible(conversation: uuid.UUID) -> tuple[int, int, int]:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE askspore_support")
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant.id))
            conversations = await conn.fetchval(
                "SELECT count(*) FROM conversations WHERE id = $1", conversation
            )
            messages = await conn.fetchval(
                "SELECT count(*) FROM messages WHERE conversation_id = $1", conversation
            )
            citations = await conn.fetchval(
                "SELECT count(*) FROM citations c JOIN messages m ON m.id = c.message_id "
                "WHERE m.conversation_id = $1",
                conversation,
            )
            return conversations, messages, citations

    async def settings_rows() -> int:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE askspore_support")
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant.id))
            return int(await conn.fetchval("SELECT count(*) FROM workspaces"))

    assert await visible(granted) == (0, 0, 0)
    assert await settings_rows() == 0
    grant = await support.grant(admin, conversation=granted)
    assert await visible(granted) == (1, 2, 1)
    assert await visible(other) == (0, 0, 0)
    assert await settings_rows() == 0
    await support.expire(grant["id"])
    assert await visible(granted) == (0, 0, 0)
    settings = await support.grant(admin, scope="settings")
    assert await settings_rows() >= 1
    await admin.post(f"/api/v1/admin/support-grants/{settings['id']}/revoke")
    assert await settings_rows() == 0
    # Without a tenant set, nothing at all.
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE askspore_support")
        assert await conn.fetchval("SELECT count(*) FROM support_grants") == 0


async def test_the_operator_writes_nothing_through_a_grant(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    await support.grant(admin, conversation=conversation)
    await support.grant(admin, scope="settings")
    conn = support.admin
    writes = [
        ("UPDATE messages SET content = 'x' WHERE conversation_id = $1", conversation),
        ("DELETE FROM messages WHERE conversation_id = $1", conversation),
        ("UPDATE conversations SET title = 'x' WHERE id = $1", conversation),
        ("UPDATE workspaces SET name = 'x' WHERE tenant_id = $1", tenant.id),
        ("UPDATE tenant_settings SET retention_days = 1 WHERE tenant_id = $1", tenant.id),
        ("UPDATE support_grants SET revoked_at = now() WHERE tenant_id = $1", tenant.id),
        ("SELECT user_id FROM conversations WHERE id = $1", conversation),
        ("SELECT email FROM users WHERE tenant_id = $1", tenant.id),
    ]
    for statement, arg in writes:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE askspore_support")
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant.id))
                await conn.execute(statement, arg)
    # Only GET routes exist under support-grants.
    op = await support.console.operator()
    path = f"/api/v1/operator/tenants/{tenant.id}/support-grants"
    assert (await op.post(path, json={})).status_code == 405


# --- nothing of the viewed conversation leaves the response ---------------------------------


async def test_nothing_of_the_viewed_conversation_reaches_a_log(
    support: Support,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    tenant, admin = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    texts = await support.texts(conversation)
    note = NOTE.format("lognote")
    grant = await support.grant(admin, conversation=conversation, note=note)
    capsys.readouterr()
    op = await support.console.operator()

    viewed = await op.get(conversation_path(tenant.id, grant["id"], conversation))
    assert viewed.status_code == 200
    body = viewed.json()
    shown = [m["content"] for m in body["messages"]] + [
        c["excerpt"] for m in body["messages"] for c in m["citations"]
    ]
    assert sorted(shown) == sorted(texts)  # as the user sees them
    assert "user_id" not in json.dumps(body) and tenant.email not in json.dumps(body)
    # Refusals too: a wrong conversation, after revocation.
    refused = await op.get(conversation_path(tenant.id, grant["id"], uuid.uuid4()))
    await admin.post(f"/api/v1/admin/support-grants/{grant['id']}/revoke")
    after = await op.get(conversation_path(tenant.id, grant["id"], conversation))
    for response in (refused, after):
        assert not_found(response)

    logged = capsys.readouterr().out + "\n".join(r.getMessage() for r in caplog.records)
    assert '"event":"operator.support_viewed"' in logged  # positive control
    assert '"event":"operator.support_refused"' in logged
    for secret in [*texts, note, "Synthetic title", tenant.email]:
        assert secret not in logged, secret
    audit = await support.admin.fetch(
        "SELECT metadata::text AS m FROM audit_events WHERE tenant_id = $1", tenant.id
    )
    for secret in [*texts, note]:
        assert all(secret not in r["m"] for r in audit), secret


# --- the tenant admin's side --------------------------------------------------------------


async def test_the_admin_page_shows_the_view_event(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    conversation = await support.conversation(tenant)
    grant = await support.grant(admin, conversation=conversation, minutes=30)
    assert grant["state"] == "open" and grant["views"] == 0
    assert grant["conversation_title"].startswith("Synthetic title")
    op = await support.console.operator()
    listed = (await op.get(f"/api/v1/operator/tenants/{tenant.id}/support-grants")).json()
    assert [(g["id"], g["scope"], g["conversation_id"]) for g in listed] == [
        (grant["id"], "conversation", str(conversation))
    ]
    for _ in range(2):
        assert (await op.get(conversation_path(tenant.id, grant["id"], conversation))).is_success

    grants = (await admin.get("/api/v1/admin/support-grants")).json()
    assert [(g["id"], g["state"], g["views"]) for g in grants] == [(grant["id"], "used", 2)]
    assert grants[0]["last_viewed_at"] is not None
    events = await support.console.events("operator.support_viewed", tenant.id)
    operator_id = str(await support.console.operator_id())
    assert [meta(e) for e in events] == [
        {
            "operator_id": operator_id,
            "grant_id": grant["id"],
            "scope": "conversation",
            "conversation_id": str(conversation),
        }
    ] * 2
    # The view events are in the tenant's audit export.
    export = await admin.get("/api/v1/admin/audit-log")
    assert export.text.count("operator.support_viewed") == 2
    assert export.text.count("tenant_admin.support_granted") == 1


async def test_the_settings_view(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    await admin.put("/api/v1/admin/settings/retention", json={"retention_days": 7})
    grant = await support.grant(admin, scope="settings", minutes=15)
    assert (
        14 * 60
        <= (
            datetime.fromisoformat(grant["expires_at"])
            - datetime.fromisoformat(grant["created_at"])
        ).total_seconds()
        <= 15 * 60
    )
    op = await support.console.operator()
    body = (await op.get(settings_path(tenant.id, grant["id"]))).json()
    assert body["retention_days"] == 7 and body["grant_id"] == grant["id"]
    assert [w["default_mode"] for w in body["workspaces"]] == ["corpus_only"]
    events = await support.console.events("operator.support_viewed", tenant.id)
    assert [e["scope"] for e in events] == ["settings"]
    assert all(e["actor"] is None for e in events)  # the operator acts as themselves


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"scope": "conversation", "note": "Synthetic."}, "conversation_required"),
        (
            {"scope": "settings", "note": "Synthetic.", "conversation_id": "OWN"},
            "conversation_not_allowed",
        ),
        (
            {"scope": "conversation", "note": "Synthetic.", "conversation_id": "MEMBER"},
            "conversation_not_found",
        ),
        (
            {"scope": "conversation", "note": "Synthetic.", "conversation_id": "RANDOM"},
            "conversation_not_found",
        ),
        ({"scope": "settings", "note": "   "}, "note_required"),
    ],
)
async def test_a_grant_names_one_of_the_admins_own_conversations(
    support: Support, body: dict[str, Any], code: str
) -> None:
    tenant, admin = await admin_of(support.auth)
    member = await add_user(support.admin, tenant)
    ids = {
        "OWN": str(await support.conversation(tenant)),
        "MEMBER": str(await support.conversation(tenant, member.user_id)),
        "RANDOM": str(uuid.uuid4()),
    }
    if "conversation_id" in body:
        body = body | {"conversation_id": ids[body["conversation_id"]]}
    response = await admin.post("/api/v1/admin/support-grants", json=body)
    assert (response.status_code, response.json()["detail"]) == (422, code)
    assert await support.console.events("tenant_admin.support_granted", tenant.id) == []


@pytest.mark.parametrize("minutes", [14, 241, 0, 600])
async def test_the_duration_is_15_minutes_to_4_hours(support: Support, minutes: int) -> None:
    _, admin = await admin_of(support.auth)
    response = await admin.post(
        "/api/v1/admin/support-grants",
        json={"scope": "settings", "note": "Synthetic.", "duration_minutes": minutes},
    )
    assert response.status_code == 422


async def test_the_default_duration_is_one_hour_and_only_admins_grant(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    response = await admin.post(
        "/api/v1/admin/support-grants", json={"scope": "settings", "note": "Synthetic."}
    )
    assert response.status_code == 201 and response.json()["duration_minutes"] == 60
    member = await add_user(support.admin, tenant)
    plain = as_user(support.auth, member.email, tenant.id)
    assert (await plain.get("/api/v1/admin/support-grants")).status_code == 403
    assert (
        await plain.post(
            "/api/v1/admin/support-grants", json={"scope": "settings", "note": "Synthetic."}
        )
    ).status_code == 403
    # Another tenant's admin can neither list nor revoke it.
    _, other_admin = await admin_of(support.auth)
    assert (await other_admin.get("/api/v1/admin/support-grants")).json() == []
    grant_id = response.json()["id"]
    assert not_found(await other_admin.post(f"/api/v1/admin/support-grants/{grant_id}/revoke"))
    events = await support.console.events("tenant_admin.support_granted", tenant.id)
    assert [meta(e) for e in events] == [
        {"grant_id": grant_id, "scope": "settings", "conversation_id": None, "duration_minutes": 60}
    ]


async def test_a_revoked_or_closed_grant_cannot_be_reopened(
    support: Support, app_conn: asyncpg.Connection
) -> None:
    tenant, admin = await admin_of(support.auth)
    grant = await support.grant(admin, scope="settings")
    await admin.post(f"/api/v1/admin/support-grants/{grant['id']}/revoke")
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant.id))
    with pytest.raises(asyncpg.RaiseError, match="stays revoked"):
        await app_conn.execute(
            "UPDATE support_grants SET revoked_at = NULL WHERE id = $1", uuid.UUID(grant["id"])
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute(
            "UPDATE support_grants SET expires_at = expires_at + interval '1 day' WHERE id = $1",
            uuid.UUID(grant["id"]),
        )


# --- the daily purge ----------------------------------------------------------------------


async def test_the_daily_purge_closes_expired_grants(support: Support) -> None:
    tenant, admin = await admin_of(support.auth)
    expired = await support.grant(admin, scope="settings")
    still_open = await support.grant(admin, scope="settings")
    revoked = await support.grant(admin, scope="settings")
    await admin.post(f"/api/v1/admin/support-grants/{revoked['id']}/revoke")
    await support.expire(expired["id"])
    factory = support.auth.app.state.db_factory

    due = await purge_retention(factory, downloads_days=90, dry_run=True)
    assert {t.tenant_id: t.counts.support_grants_closed for t in due}[tenant.id] == 1
    done = await purge_retention(factory, downloads_days=90)
    assert {t.tenant_id: t.counts.support_grants_closed for t in done}[tenant.id] == 1
    closed = await support.admin.fetch(
        "SELECT id FROM support_grants WHERE tenant_id = $1 AND closed_at IS NOT NULL", tenant.id
    )
    assert [str(r["id"]) for r in closed] == [expired["id"]]
    events = await support.console.events("support.grant_expired", tenant.id)
    assert [meta(e) for e in events] == [{"grant_id": expired["id"]}]
    again = await purge_retention(factory, downloads_days=90)
    assert {t.tenant_id: t.counts.support_grants_closed for t in again}[tenant.id] == 0
    states = {g["id"]: g["state"] for g in (await admin.get("/api/v1/admin/support-grants")).json()}
    assert states == {expired["id"]: "expired", still_open["id"]: "open", revoked["id"]: "revoked"}
    # The retention role, scoped to one tenant, closes nothing of another.
    async with tenant_role_session(factory, RETENTION_ROLE, uuid.uuid4()) as session:
        assert await close_expired(session, tenant.id, dry_run=True) == 0
