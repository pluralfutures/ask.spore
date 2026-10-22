"""P1a-13: tenant admin routes (users, workspace defaults, prompt versions, retention).
Over HTTP in OIDC mode, against PostgreSQL as the application role."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest

from tests.conftest import CONSENT_VERSION
from tests.fake_idp import sign
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

MODEL = "deepseek-v4.1-flash"
ADMIN_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/admin/users", None),
    ("POST", "/api/v1/admin/users", {"email": "new@client.example", "display_name": "New"}),
    ("PATCH", f"/api/v1/admin/users/{uuid.uuid4()}", {"status": "deactivated"}),
    (
        "PUT",
        f"/api/v1/admin/workspaces/{uuid.uuid4()}/defaults",
        {"default_mode": "corpus_only", "default_model": MODEL, "default_reasoning": False},
    ),
    ("GET", "/api/v1/admin/settings", None),
    ("PUT", "/api/v1/admin/settings/retention", {"retention_days": 7}),
    # The additional-instructions routes (findings B5) are admin-only too.
    ("GET", f"/api/v1/workspaces/{uuid.uuid4()}/prompts", None),
    ("PUT", f"/api/v1/workspaces/{uuid.uuid4()}/prompt", {"text": "Synthetic."}),
]


def as_user(harness: Auth, email: str, tenant_id: uuid.UUID) -> httpx.AsyncClient:
    browser = harness.browser()
    browser.headers["Authorization"] = (
        f"Bearer {sign(harness.idp.key, email=email, tenant_id=tenant_id)}"
    )
    return browser


async def admin_of(harness: Auth) -> tuple[Tenant, httpx.AsyncClient]:
    tenant = await harness.tenant(role="tenant_admin")
    return tenant, as_user(harness, tenant.email, tenant.id)


async def add_user(
    admin: asyncpg.Connection,
    tenant: Tenant,
    *,
    role: str = "user",
    status: str = "active",
    consent_version: str | None = CONSENT_VERSION,
) -> Tenant:
    email = f"member-{uuid.uuid4().hex[:8]}@client.example"
    user_id = await admin.fetchval(
        "INSERT INTO users (tenant_id, email, display_name, role, status, last_login_at, "
        "last_login_method, consent_version, consented_at) VALUES ($1, $2, 'Synthetic Member', "
        "$3, $4, now(), 'sign_in_link', $5, CASE WHEN $5::text IS NULL THEN NULL ELSE now() END) "
        "RETURNING id",
        tenant.id,
        email,
        role,
        status,
        consent_version,
    )
    return Tenant(tenant.id, user_id, email)


async def events(harness: Auth, event: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await harness.admin.fetch(
        "SELECT actor_user_id, metadata FROM audit_events "
        "WHERE event = $1 AND tenant_id = $2 ORDER BY created_at",
        event,
        tenant_id,
    )
    return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]


# --- only tenant admins ------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
async def test_user_role_cannot_call_admin_routes(
    auth: Auth,  # noqa: F811
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    tenant = await auth.tenant(role="user")
    browser = as_user(auth, tenant.email, tenant.id)
    assert (await browser.get("/api/v1/me")).json()["role"] == "user"
    response = await browser.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}
    # Refused before the body is read: an invalid body is still 403, not 422.
    if body is not None:
        assert (await browser.request(method, path, json={"bogus": 1})).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES[:6])
async def test_admin_routes_need_a_session(
    auth: Auth,  # noqa: F811
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    response = await auth.browser().request(method, path, json=body)
    assert response.status_code == 401


# --- users -------------------------------------------------------------------------------


async def test_admin_lists_own_tenant_users_with_last_login(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    other = await auth.tenant()
    response = await browser.get("/api/v1/admin/users")
    assert response.status_code == 200
    users = {u["id"]: u for u in response.json()}
    assert set(users) == {str(tenant.user_id), str(member.user_id)}  # never other's users
    assert str(other.user_id) not in users
    assert users[str(member.user_id)]["last_login_method"] == "sign_in_link"
    assert users[str(member.user_id)]["last_login_at"] is not None
    assert users[str(tenant.user_id)]["role"] == "tenant_admin"


async def test_invite_creates_an_invited_user_and_audits(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    email = f"Invitee-{uuid.uuid4().hex[:6]}@Client.Example"
    response = await browser.post(
        "/api/v1/admin/users", json={"email": email, "display_name": "Synthetic Invitee"}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert (created["email"], created["role"], created["status"]) == (
        email.lower(),
        "user",
        "invited",
    )
    assert auth.idp.users[email.lower()] == (tenant.id, "Synthetic Invitee")
    assert await events(auth, "tenant_admin.user_invited", tenant.id) == [
        {
            "actor": tenant.user_id,
            "before": {},
            "after": {"user_id": created["id"], "role": "user", "status": "invited"},
        }
    ]
    # The invitee signs in with a link; the first sign-in makes them active.
    invitee = Tenant(tenant.id, uuid.UUID(created["id"]), email.lower())
    await auth.sign_in(auth.browser(), invitee)
    status = await auth.admin.fetchval("SELECT status FROM users WHERE id = $1", invitee.user_id)
    assert status == "active"


async def test_invite_refuses_unverified_domains_and_taken_emails(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    other = await auth.tenant()
    for email, code, expected in (
        ("someone@elsewhere.example", 422, "domain_not_verified"),
        ("not-an-email", 422, "invalid_email"),
        (other.email, 409, "email_taken"),  # a user of another tenant
        (tenant.email, 409, "email_taken"),
    ):
        response = await browser.post(
            "/api/v1/admin/users", json={"email": email, "display_name": "Synthetic"}
        )
        assert (response.status_code, response.json()["detail"]) == (code, expected), email
    # Nothing was provisioned for the other tenant's user, and nothing was created.
    assert auth.idp.users[other.email] == (other.id, "Synthetic")
    assert await events(auth, "tenant_admin.user_invited", tenant.id) == []


async def test_deactivate_role_change_and_reactivate(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant)
    member_browser = as_user(auth, member.email, member.id)
    assert (await member_browser.get("/api/v1/me")).status_code == 200

    path = f"/api/v1/admin/users/{member.user_id}"
    response = await browser.patch(path, json={"status": "deactivated"})
    assert response.status_code == 200 and response.json()["status"] == "deactivated"
    assert (await member_browser.get("/api/v1/me")).status_code == 401  # at once

    response = await browser.patch(path, json={"status": "active", "role": "tenant_admin"})
    assert response.json()["status"] == "active" and response.json()["role"] == "tenant_admin"
    assert (await member_browser.get("/api/v1/me")).json()["role"] == "tenant_admin"
    changes = await events(auth, "tenant_admin.user_changed", tenant.id)
    uid = str(member.user_id)
    assert [(c["before"], c["after"]) for c in changes] == [
        (
            {"user_id": uid, "role": "user", "status": "active"},
            {"user_id": uid, "role": "user", "status": "deactivated"},
        ),
        (
            {"user_id": uid, "role": "user", "status": "deactivated"},
            {"user_id": uid, "role": "tenant_admin", "status": "active"},
        ),
    ]
    assert {c["actor"] for c in changes} == {tenant.user_id}


async def test_reactivating_a_user_who_never_signed_in_returns_them_to_invited(
    auth: Auth,  # noqa: F811
) -> None:
    tenant, browser = await admin_of(auth)
    member = await add_user(auth.admin, tenant, status="deactivated")
    await auth.admin.execute("UPDATE users SET last_login_at = NULL WHERE id = $1", member.user_id)
    response = await browser.patch(
        f"/api/v1/admin/users/{member.user_id}", json={"status": "active"}
    )
    assert response.json()["status"] == "invited"


async def test_admin_cannot_change_self_or_another_tenants_user(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    own = await browser.patch(f"/api/v1/admin/users/{tenant.user_id}", json={"role": "user"})
    assert (own.status_code, own.json()["detail"]) == (422, "cannot_change_self")
    other = await auth.tenant()
    foreign = await browser.patch(
        f"/api/v1/admin/users/{other.user_id}", json={"status": "deactivated"}
    )
    assert foreign.status_code == 404
    status = await auth.admin.fetchval("SELECT status FROM users WHERE id = $1", other.user_id)
    assert status == "active"


# --- workspace defaults and prompts ------------------------------------------------------


async def _workspace(admin: asyncpg.Connection, tenant: Tenant) -> uuid.UUID:
    wid: uuid.UUID = await admin.fetchval(
        "SELECT id FROM workspaces WHERE tenant_id = $1", tenant.id
    )
    return wid


async def test_set_workspace_defaults_among_enabled_options(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    await auth.admin.execute(
        "UPDATE tenant_entitlements SET answer_modes = ARRAY['corpus_only', 'general_knowledge'], "
        "enabled_models = ARRAY['deepseek-v4.1-flash', 'qwen3.8-27b'] WHERE tenant_id = $1",
        tenant.id,
    )
    wid = await _workspace(auth.admin, tenant)
    path = f"/api/v1/admin/workspaces/{wid}/defaults"
    body = {"default_mode": "general_knowledge", "default_model": "qwen3.8-27b"}
    response = await browser.put(path, json={**body, "default_reasoning": True})
    assert response.status_code == 200, response.text
    assert response.json()["default_model"] == "qwen3.8-27b"
    (change,) = await events(auth, "tenant_admin.workspace_defaults_changed", tenant.id)
    assert change["before"]["default_model"] == MODEL
    assert change["after"] == {
        "workspace_id": str(wid),
        "default_mode": "general_knowledge",
        "default_model": "qwen3.8-27b",
        "default_reasoning": True,
    }
    # A new conversation in the workspace starts from the new defaults.
    created = (await browser.post("/api/v1/conversations", json={})).json()
    assert (created["mode"], created["model"], created["reasoning"]) == (
        "general_knowledge",
        "qwen3.8-27b",
        True,
    )

    for refused, code in (
        ({"default_model": "anthropic/claude-opus-5.5"}, "model_not_enabled"),
        ({"default_model": "no-such-model"}, "model_unavailable"),
    ):
        response = await browser.put(path, json={**body, "default_reasoning": False, **refused})
        assert (response.status_code, response.json()["detail"]) == (422, code)
    await auth.admin.execute(
        "UPDATE tenant_entitlements SET answer_modes = ARRAY['corpus_only'] WHERE tenant_id = $1",
        tenant.id,
    )
    response = await browser.put(path, json={**body, "default_reasoning": False})
    assert (response.status_code, response.json()["detail"]) == (422, "mode_not_enabled")


async def test_another_tenants_workspace_is_not_found(auth: Auth) -> None:  # noqa: F811
    _, browser = await admin_of(auth)
    other = await auth.tenant()
    wid = await _workspace(auth.admin, other)
    body = {"default_mode": "corpus_only", "default_model": MODEL, "default_reasoning": True}
    response = await browser.put(f"/api/v1/admin/workspaces/{wid}/defaults", json=body)
    assert response.status_code == 404
    assert (await browser.get(f"/api/v1/workspaces/{wid}/prompts")).status_code == 404


async def test_app_role_may_change_only_workspace_defaults(app_conn: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE workspaces SET tag_ids = ARRAY['sample-web']")
    await app_conn.execute("UPDATE workspaces SET default_reasoning = default_reasoning")


async def test_saving_a_prompt_creates_a_new_version(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    wid = await _workspace(auth.admin, tenant)
    for text in ("Synthetic first instructions.", "Synthetic second instructions."):
        response = await browser.put(f"/api/v1/workspaces/{wid}/prompt", json={"text": text})
        assert response.status_code == 200
    history = (await browser.get(f"/api/v1/workspaces/{wid}/prompts")).json()
    assert [(p["version"], p["text"]) for p in history] == [
        (2, "Synthetic second instructions."),
        (1, "Synthetic first instructions."),
    ]


# --- retention ---------------------------------------------------------------------------


async def test_retention_cannot_be_set_above_30_days(
    auth: Auth,  # noqa: F811
    app_conn: asyncpg.Connection,
) -> None:
    tenant, browser = await admin_of(auth)
    for days in (31, 365, 0, -1):
        response = await browser.put(
            "/api/v1/admin/settings/retention", json={"retention_days": days}
        )
        assert response.status_code == 422, days
    assert (await browser.get("/api/v1/admin/settings")).json()["retention_days"] == 30
    # The database refuses it too, whoever writes.
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(tenant.id))
    with pytest.raises(asyncpg.CheckViolationError):
        await app_conn.execute(
            "INSERT INTO tenant_settings (tenant_id, retention_days) VALUES ($1, 31)", tenant.id
        )


async def test_shortening_retention_expires_conversations(auth: Auth) -> None:  # noqa: F811
    tenant, browser = await admin_of(auth)
    old = (await browser.post("/api/v1/conversations", json={})).json()["id"]
    await auth.admin.execute(
        "UPDATE conversations SET created_at = now() - interval '10 days', "
        "expires_at = now() + interval '20 days' WHERE id = $1",
        uuid.UUID(old),
    )
    recent = (await browser.post("/api/v1/conversations", json={})).json()["id"]

    response = await browser.put("/api/v1/admin/settings/retention", json={"retention_days": 7})
    assert response.status_code == 200
    assert response.json() == {
        "retention_days": 7,
        "max_retention_days": 30,
        "answer_modes": ["corpus_only"],
    }
    listed = [c["id"] for c in (await browser.get("/api/v1/conversations")).json()]
    assert listed == [recent]  # the ten-day-old one is past seven days: gone at read time
    assert (await browser.get(f"/api/v1/conversations/{old}")).status_code == 404

    created = (await browser.post("/api/v1/conversations", json={})).json()
    lifetime = datetime.fromisoformat(created["expires_at"]) - datetime.fromisoformat(
        created["created_at"]
    )
    assert timedelta(days=6, hours=23) < lifetime <= timedelta(days=7)
    (change,) = await events(auth, "tenant_admin.retention_changed", tenant.id)
    assert change == {
        "actor": tenant.user_id,
        "before": {"retention_days": 30},
        "after": {"retention_days": 7},
        "count": 2,
    }

    # Lengthening again applies to new conversations only.
    await browser.put("/api/v1/admin/settings/retention", json={"retention_days": 30})
    still = await auth.admin.fetchval(
        "SELECT expires_at - created_at FROM conversations WHERE id = $1", uuid.UUID(recent)
    )
    assert still <= timedelta(days=7)
    created = (await browser.post("/api/v1/conversations", json={})).json()
    lifetime = datetime.fromisoformat(created["expires_at"]) - datetime.fromisoformat(
        created["created_at"]
    )
    assert lifetime > timedelta(days=29)


async def test_retention_of_one_tenant_does_not_touch_another(auth: Auth) -> None:  # noqa: F811
    mine, browser = await admin_of(auth)
    other, other_browser = await admin_of(auth)
    theirs = (await other_browser.post("/api/v1/conversations", json={})).json()["id"]
    await auth.admin.execute(
        "UPDATE conversations SET created_at = now() - interval '10 days', "
        "expires_at = now() + interval '20 days' WHERE id = $1",
        uuid.UUID(theirs),
    )
    await browser.put("/api/v1/admin/settings/retention", json={"retention_days": 1})
    assert (await other_browser.get(f"/api/v1/conversations/{theirs}")).status_code == 200
    assert (await other_browser.get("/api/v1/admin/settings")).json()["retention_days"] == 30
    assert other.id != mine.id
