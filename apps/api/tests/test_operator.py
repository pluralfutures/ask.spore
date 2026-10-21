"""P1a-03: operator console routes, the operator dependency and role, and the audit
trail of every change. Over HTTP in OIDC mode, against PostgreSQL."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.audit.writer import ForbiddenAuditField, _check
from app.core.db import session_factory
from app.operator.grants import grant_operator, revoke_operator
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase
from tests.fake_idp import sign
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

OPERATOR_EMAIL = "editor@example.org"  # seeded into the internal tenant (conftest)
MODEL = "deepseek-v4.1-flash"
BOTH_MODES = ["general_knowledge", "corpus_only"]
ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/operator/me", None),
    ("GET", "/api/v1/operator/options", None),
    ("GET", "/api/v1/operator/tenants", None),
    ("POST", "/api/v1/operator/tenants", {"slug": "x-tenant", "display_name": "X"}),
    (
        "POST",
        f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/admins",
        {"email": "new@x.example", "display_name": "New"},
    ),
    (
        "PUT",
        f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/entitlements",
        {
            "answer_modes": ["corpus_only"],
            "enabled_models": [MODEL],
            "external_models_enabled": False,
        },
    ),
    ("GET", f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/login-policy", None),
    (
        "PUT",
        f"/api/v1/operator/tenants/{INTERNAL_TENANT_ID}/login-policy",
        {
            "sign_in_links_enabled": False,
            "jit_provisioning_enabled": False,
            "admin_mfa_required": True,
        },
    ),
    ("GET", "/api/v1/operator/notices", None),
]


@pytest.fixture
async def owner(database: MigratedDatabase) -> AsyncIterator[Any]:
    engine = create_async_engine(database.sqlalchemy_url)
    yield session_factory(engine)
    await engine.dispose()


class Console:
    def __init__(self, harness: Auth, owner: Any) -> None:
        self.auth = harness
        self.owner = owner

    async def operator(self) -> httpx.AsyncClient:
        await grant_operator(self.owner, email=OPERATOR_EMAIL, display_name=None, provider=None)
        return self.as_user(OPERATOR_EMAIL, INTERNAL_TENANT_ID)

    def as_user(self, email: str, tenant_id: uuid.UUID) -> httpx.AsyncClient:
        browser = self.auth.browser()
        token = sign(self.auth.idp.key, email=email, tenant_id=tenant_id)
        browser.headers["Authorization"] = f"Bearer {token}"
        return browser

    async def events(self, event: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.auth.admin.fetch(
            "SELECT actor_user_id, metadata FROM audit_events "
            "WHERE event = $1 AND tenant_id = $2 ORDER BY created_at",
            event,
            tenant_id,
        )
        return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]

    async def operator_id(self) -> uuid.UUID:
        user_id: uuid.UUID = await self.auth.admin.fetchval(
            "SELECT id FROM users WHERE email = $1", OPERATOR_EMAIL
        )
        return user_id


@pytest.fixture
async def console(auth: Auth, owner: Any) -> AsyncIterator[Console]:  # noqa: F811
    yield Console(auth, owner)
    await revoke_operator(owner, email=OPERATOR_EMAIL)


def entitlements(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "answer_modes": ["corpus_only"],
        "enabled_models": [MODEL],
        "external_models_enabled": False,
        "external_spend_cap_cents": None,
    }
    body.update(overrides)
    return body


async def create(op: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    slug = body.pop("slug", f"t-{uuid.uuid4().hex[:10]}")
    response = await op.post(
        "/api/v1/operator/tenants", json={"slug": slug, "display_name": "Synthetic Co", **body}
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# --- who can reach the console -----------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_tenant_admin_cannot_reach_operator_routes(
    console: Console, method: str, path: str, body: dict[str, Any] | None
) -> None:
    admin: Tenant = await console.auth.tenant(role="tenant_admin")
    browser = console.as_user(admin.email, admin.id)
    assert (await browser.get("/api/v1/me")).status_code == 200  # a valid, signed-in admin
    response = await browser.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_internal_user_who_is_not_an_operator_is_refused(
    console: Console, method: str, path: str, body: dict[str, Any] | None
) -> None:
    browser = console.as_user("analyst@example.org", INTERNAL_TENANT_ID)
    assert (await browser.request(method, path, json=body)).status_code == 403


async def test_unauthenticated_gets_401(console: Console) -> None:
    assert (await console.auth.browser().get("/api/v1/operator/tenants")).status_code == 401


async def test_operator_listing_in_another_tenant_does_not_count(console: Console) -> None:
    # The operators row names an internal user; a client user with the same email cannot
    # exist (one email, one tenant), and a token claiming another tenant is not internal.
    await console.operator()
    forged = console.as_user(OPERATOR_EMAIL, uuid.uuid4())
    assert (await forged.get("/api/v1/operator/tenants")).status_code == 401


async def test_revoked_operator_is_refused(console: Console) -> None:
    op = await console.operator()
    assert (await op.get("/api/v1/operator/tenants")).status_code == 200
    assert await revoke_operator(console.owner, email=OPERATOR_EMAIL) == "revoked"
    assert (await op.get("/api/v1/operator/tenants")).status_code == 403
    granted = await console.events("operator.granted", INTERNAL_TENANT_ID)
    revoked = await console.events("operator.revoked", INTERNAL_TENANT_ID)
    assert granted and revoked


# --- create tenant, invite first admin ---------------------------------------------------


async def test_create_tenant_with_defaults_and_audit(console: Console) -> None:
    op = await console.operator()
    domain = f"c{uuid.uuid4().hex[:8]}.example"
    created = await create(op, verified_domains=[domain.upper(), domain])
    assert created["verified_domains"] == [domain]
    assert created["status"] == "active" and created["admins"] == 0
    ent = created["entitlements"]
    assert (ent["answer_modes"], ent["enabled_models"]) == (["corpus_only"], [MODEL])
    assert ent["external_models_enabled"] is False
    policy = created["login_policy"]
    assert (policy["sign_in_links_enabled"], policy["sso_source_kind"]) == (True, "none")
    assert (policy["jit_provisioning_enabled"], policy["admin_mfa_required"]) == (False, True)

    tenant_id = uuid.UUID(created["id"])
    (event,) = await console.events("operator.tenant_created", tenant_id)
    assert event["actor"] is None
    assert event["operator_id"] == str(await console.operator_id())
    assert event["before"] == {}
    assert event["after"]["slug"] == created["slug"]
    assert event["after"]["verified_domains"] == [domain]
    assert event["after"]["external_models_enabled"] is False
    listed = (await op.get("/api/v1/operator/tenants")).json()
    assert created["id"] in {t["id"] for t in listed}
    assert str(INTERNAL_TENANT_ID) in {t["id"] for t in listed}  # outside tenant RLS


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"slug": "internal"}, 409, "slug_taken"),
        ({"slug": "Bad Slug"}, 422, None),
        ({"verified_domains": ["not a domain"]}, 422, None),
        ({"tenant_id": str(uuid.uuid4())}, 422, None),  # no IDs from the client
    ],
)
async def test_create_tenant_validation(
    console: Console, body: dict[str, Any], status: int, detail: str | None
) -> None:
    op = await console.operator()
    payload = {"slug": f"t-{uuid.uuid4().hex[:8]}", "display_name": "X", **body}
    response = await op.post("/api/v1/operator/tenants", json=payload)
    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail


async def test_a_domain_belongs_to_one_tenant(console: Console) -> None:
    op = await console.operator()
    domain = f"d{uuid.uuid4().hex[:8]}.example"
    await create(op, verified_domains=[domain])
    response = await op.post(
        "/api/v1/operator/tenants",
        json={
            "slug": f"t-{uuid.uuid4().hex[:8]}",
            "display_name": "Y",
            "verified_domains": [domain],
        },
    )
    assert (response.status_code, response.json()["detail"]) == (409, "domain_taken")


async def test_invited_first_admin_signs_in_with_a_link(console: Console) -> None:
    op = await console.operator()
    tenant_id = uuid.UUID((await create(op))["id"])
    email = f"admin-{uuid.uuid4().hex[:6]}@client.example"
    response = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins",
        json={"email": email.upper(), "display_name": "First Admin"},
    )
    assert response.status_code == 201
    user_id = uuid.UUID(response.json()["user_id"])
    row = await console.auth.admin.fetchrow(
        "SELECT tenant_id, email, role, status FROM users WHERE id = $1", user_id
    )
    assert row is not None
    assert tuple(row.values()) == (tenant_id, email, "tenant_admin", "invited")
    assert console.auth.idp.users[email][0] == tenant_id  # provisioned with the tenant
    (event,) = await console.events("operator.admin_invited", tenant_id)
    assert event["after"] == {"user_id": str(user_id), "role": "tenant_admin", "status": "invited"}
    assert email not in json.dumps(event)  # the audit row names the user, not the address

    # The admin signs in from their own browser and becomes active.
    browser = console.auth.browser()
    await console.auth.request_link(browser, email)
    assert (await console.auth.complete(browser, console.auth.idp.last_token())).status_code == 204
    me = (await browser.get("/api/v1/me")).json()
    assert (me["role"], me["tenant_display_name"]) == ("tenant_admin", "Synthetic Co")
    assert (
        await console.auth.admin.fetchval("SELECT status FROM users WHERE id = $1", user_id)
        == "active"
    )
    # ...and still cannot reach the console.
    assert (await browser.get("/api/v1/operator/tenants")).status_code == 403


async def test_invite_refuses_an_email_of_another_tenant(console: Console) -> None:
    op = await console.operator()
    existing: Tenant = await console.auth.tenant()
    tenant_id = (await create(op))["id"]
    response = await op.post(
        f"/api/v1/operator/tenants/{tenant_id}/admins",
        json={"email": existing.email, "display_name": "Dup"},
    )
    assert (response.status_code, response.json()["detail"]) == (409, "email_taken")
    missing = await op.post(
        f"/api/v1/operator/tenants/{uuid.uuid4()}/admins",
        json={"email": "a@b.example", "display_name": "A"},
    )
    assert missing.status_code == 404


# --- entitlements -------------------------------------------------------------------------


async def test_entitlement_change_is_audited_with_before_and_after(console: Console) -> None:
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    response = await op.put(
        f"/api/v1/operator/tenants/{tenant_id}/entitlements",
        json=entitlements(answer_modes=["general_knowledge", "corpus_only"]),
    )
    assert response.status_code == 200
    assert response.json()["answer_modes"] == ["corpus_only", "general_knowledge"]
    (event,) = await console.events("operator.entitlements_changed", uuid.UUID(tenant_id))
    assert event["operator_id"] == str(await console.operator_id())
    assert event["before"]["answer_modes"] == ["corpus_only"]
    assert event["after"]["answer_modes"] == ["corpus_only", "general_knowledge"]
    # Saving the same values again changes nothing and writes nothing.
    again = await op.put(
        f"/api/v1/operator/tenants/{tenant_id}/entitlements",
        json=entitlements(answer_modes=["general_knowledge", "corpus_only"]),
    )
    assert again.status_code == 200
    assert len(await console.events("operator.entitlements_changed", uuid.UUID(tenant_id))) == 1


async def test_enabling_external_models_needs_the_acceptance_reference(console: Console) -> None:
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    path = f"/api/v1/operator/tenants/{tenant_id}/entitlements"
    refused = await op.put(
        path, json=entitlements(external_models_enabled=True, external_spend_cap_cents=50_000)
    )
    assert (refused.status_code, refused.json()["detail"]) == (422, "acceptance_required")
    no_cap = await op.put(
        path,
        json=entitlements(
            external_models_enabled=True,
            external_acceptance={"reference": "DPA-SYN-001 §4", "accepted_on": "2026-10-15"},
        ),
    )
    assert (no_cap.status_code, no_cap.json()["detail"]) == (422, "spend_cap_required")
    future = (date.today() + timedelta(days=2)).isoformat()
    in_future = await op.put(
        path,
        json=entitlements(
            external_models_enabled=True,
            external_spend_cap_cents=50_000,
            external_acceptance={"reference": "DPA-SYN-001", "accepted_on": future},
        ),
    )
    assert in_future.status_code == 422
    assert await console.events("operator.entitlements_changed", uuid.UUID(tenant_id)) == []
    assert (
        await console.auth.admin.fetchval(
            "SELECT external_models_enabled FROM tenant_entitlements WHERE tenant_id = $1",
            uuid.UUID(tenant_id),
        )
        is False
    )

    enabled = await op.put(
        path,
        json=entitlements(
            external_models_enabled=True,
            external_spend_cap_cents=50_000,
            external_acceptance={"reference": "DPA-SYN-001 §4", "accepted_on": "2026-10-15"},
        ),
    )
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["external_acceptance_reference"] == "DPA-SYN-001 §4"
    assert body["external_acceptance_date"] == "2026-10-15"
    (event,) = await console.events("operator.entitlements_changed", uuid.UUID(tenant_id))
    assert event["acceptance_reference"] == "DPA-SYN-001 §4"
    assert event["acceptance_date"] == "2026-10-15"
    assert event["before"]["external_models_enabled"] is False
    assert event["after"]["external_models_enabled"] is True
    assert event["after"]["external_spend_cap_cents"] == 50_000

    # Already on, with the acceptance on file: other changes need no new reference.
    cap = await op.put(
        path, json=entitlements(external_models_enabled=True, external_spend_cap_cents=80_000)
    )
    assert cap.status_code == 200 and cap.json()["external_acceptance_reference"]


async def test_database_refuses_external_models_without_acceptance(
    console: Console, admin_conn: asyncpg.Connection
) -> None:
    t: Tenant = await console.auth.tenant()
    with pytest.raises(asyncpg.CheckViolationError, match="external_needs_acceptance"):
        await admin_conn.execute(
            "UPDATE tenant_entitlements SET external_models_enabled = true, "
            "external_spend_cap_cents = 100 WHERE tenant_id = $1",
            t.id,
        )


@pytest.mark.parametrize(
    ("override", "detail"),
    [
        ({"enabled_models": ["gpt-latest"]}, "unknown_model"),
        ({"answer_modes": ["general_knowledge"]}, "corpus_only_required"),
        ({"answer_modes": ["web_search", "corpus_only"]}, None),
        ({"enabled_models": []}, None),
        ({"dataset_ids": ["ds-1"]}, None),  # never from the client
    ],
)
async def test_entitlement_validation(
    console: Console, override: dict[str, Any], detail: str | None
) -> None:
    op = await console.operator()
    tenant_id = (await create(op))["id"]
    response = await op.put(
        f"/api/v1/operator/tenants/{tenant_id}/entitlements", json=entitlements(**override)
    )
    assert response.status_code == 422
    if detail:
        assert response.json()["detail"] == detail


async def test_options_list_what_can_be_enabled(console: Console) -> None:
    op = await console.operator()
    assert (await op.get("/api/v1/operator/options")).json() == {
        "answer_modes": ["corpus_only", "general_knowledge"],
        # The catalogue (P1a-09), in its order.
        "models": [MODEL, "qwen3.8-27b", "openai/gpt-6.1-sol", "anthropic/claude-opus-5.5"],
        "tags": [
            "cc-shared",
            "cc-team1-healthcare-gpo",
            "cc-team2-college-universities",
            "cc-team3-commercial-restaurants",
            "sample-analysis",
            "sample-reports",
            "sample-web",
        ],
    }
    me = (await op.get("/api/v1/operator/me")).json()
    assert me["email"] == OPERATOR_EMAIL


# --- notices -------------------------------------------------------------------------------


async def test_notices_list_spans_tenants_newest_first(
    console: Console, admin_conn: asyncpg.Connection
) -> None:
    a: Tenant = await console.auth.tenant()
    b: Tenant = await console.auth.tenant()
    for tenant, kind, age in ((a, "prompt.tenant_name_match", 2), (b, "spend.cap_80", 1)):
        await admin_conn.execute(
            "INSERT INTO operator_notices (tenant_id, kind, created_at) "
            "VALUES ($1, $2, now() - make_interval(mins => $3))",
            tenant.id,
            kind,
            age,
        )
    op = await console.operator()
    notices = (await op.get("/api/v1/operator/notices")).json()
    mine = [n for n in notices if n["tenant_id"] in {str(a.id), str(b.id)}]
    assert [n["kind"] for n in mine] == ["spend.cap_80", "prompt.tenant_name_match"]
    # A tenant admin of tenant A sees none of them, not even A's.
    admin = console.as_user(a.email, a.id)
    assert (await admin.get("/api/v1/operator/notices")).status_code == 403


# --- the operator role in the database -----------------------------------------------------


@pytest.fixture
async def operator_role(app_conn: asyncpg.Connection) -> asyncpg.Connection:
    await app_conn.execute("SET ROLE askspore_operator")
    return app_conn


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM conversations",
        "SELECT * FROM messages",
        "SELECT * FROM citations",
        "SELECT * FROM feedback",
        "SELECT * FROM sign_in_links",
        "SELECT * FROM sources",
        "UPDATE audit_events SET event = 'x'",
        "DELETE FROM users",
        "INSERT INTO operators (user_id) VALUES (gen_random_uuid())",
    ],
)
async def test_operator_role_has_no_access_to_chat_content(
    operator_role: asyncpg.Connection, query: str
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await operator_role.execute(query)


async def test_operator_role_sees_every_tenant(
    console: Console, operator_role: asyncpg.Connection
) -> None:
    a: Tenant = await console.auth.tenant()
    seen = {r["id"] for r in await operator_role.fetch("SELECT id FROM tenants")}
    assert {a.id, INTERNAL_TENANT_ID} <= seen


async def test_app_role_does_not_inherit_the_operator_role(
    admin_conn: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    grant = await admin_conn.fetchrow(
        "SELECT inherit_option, set_option FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
        "WHERE r.rolname = 'askspore_operator' AND u.rolname = 'askspore_app'"
    )
    assert grant is not None and grant["set_option"] and not grant["inherit_option"]
    # Without SET ROLE, the app role sees neither operators nor notices.
    for table in ("operators", "operator_notices"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.fetch(f"SELECT * FROM {table}")


# --- audit writer: before/after are allow-listed too ------------------------------------------


@pytest.mark.parametrize(
    "metadata",
    [
        {"before": {"query": "x"}},
        {"after": {"email": "a@b.example"}},
        {"after": "flat"},
        {"answer": {"slug": "x"}},
        {"after": {"display_name": "x" * 200}},
        {"after": {"enabled_models": [{"nested": 1}]}},
    ],
)
def test_audit_changes_are_allow_listed(metadata: dict[str, Any]) -> None:
    with pytest.raises(ForbiddenAuditField):
        _check(metadata)


def test_audit_changes_accept_settings() -> None:
    _check({"operator_id": "x", "before": {}, "after": {"slug": "a", "enabled_models": ["m"]}})


# --- ask-spore operators grant|revoke ---------------------------------------------------------


async def test_grant_creates_and_provisions_an_internal_user(console: Console) -> None:
    email = f"ops-{uuid.uuid4().hex[:6]}@platform.example"
    assert (
        await grant_operator(console.owner, email=email, display_name=None, provider=None)
        == "no_user"
    )
    result = await grant_operator(
        console.owner, email=email, display_name="Ops", provider=console.auth.idp
    )
    assert result == "granted"
    assert console.auth.idp.users[email][0] == INTERNAL_TENANT_ID
    row = await console.auth.admin.fetchrow(
        "SELECT u.status, o.user_id FROM users u JOIN operators o ON o.user_id = u.id "
        "WHERE u.email = $1",
        email,
    )
    assert row is not None and row["status"] == "invited"
    again = await grant_operator(console.owner, email=email, display_name="Ops", provider=None)
    assert again == "already_operator"
    assert await revoke_operator(console.owner, email=email) == "revoked"
    assert await revoke_operator(console.owner, email=email) == "not_operator"
    # Leave the seeded internal tenant as other tests expect it.
    await console.auth.admin.execute("DELETE FROM users WHERE email = $1", email)


# --- the download switch per source (P1a-14) ------------------------------------------------


async def _register(admin: asyncpg.Connection, kind: str, *, stored: bool) -> uuid.UUID:
    sha = uuid.uuid4().hex * 2
    source_id: uuid.UUID = await admin.fetchval(
        "INSERT INTO sources (type, title, publisher, licence_basis, tags, status, file_sha256, "
        "stored_path) VALUES ($1, 'Synthetic', 'Synthetic Publisher', 'own-work', "
        "ARRAY['sample-reports'], 'ingested', $2, $3) RETURNING id",
        kind,
        sha,
        f"{sha[:2]}/{sha}.{kind}" if stored else None,
    )
    return source_id


async def test_operator_toggles_downloadable_audited(console: Console) -> None:
    op = await console.operator()
    source = await _register(console.auth.admin, "pdf", stored=True)
    listed = {s["id"]: s for s in (await op.get("/api/v1/operator/sources")).json()}
    assert listed[str(source)]["downloadable"] is False
    assert listed[str(source)]["stored"] is True
    assert "ragflow_document_ids" not in listed[str(source)]

    path = f"/api/v1/operator/sources/{source}/downloadable"
    response = await op.put(path, json={"downloadable": True})
    assert response.status_code == 200 and response.json()["downloadable"] is True
    assert (await op.put(path, json={"downloadable": True})).status_code == 200  # no change
    await op.put(path, json={"downloadable": False})
    events = await console.events("operator.source_downloadable_changed", INTERNAL_TENANT_ID)
    mine = [e for e in events if e["source_id"] == str(source)]
    assert [(e["before"], e["after"]) for e in mine] == [
        ({"downloadable": False}, {"downloadable": True}),
        ({"downloadable": True}, {"downloadable": False}),
    ]
    assert mine[0]["operator_id"] == str(await console.operator_id())
    await console.auth.admin.execute("DELETE FROM sources WHERE id = $1", source)


async def test_operator_cannot_open_the_gate_without_a_stored_file(console: Console) -> None:
    op = await console.operator()
    page = await _register(console.auth.admin, "markdown", stored=False)
    unstored = await _register(console.auth.admin, "docx", stored=False)
    for source, code in ((page, "not_a_file"), (unstored, "not_stored")):
        response = await op.put(
            f"/api/v1/operator/sources/{source}/downloadable", json={"downloadable": True}
        )
        assert (response.status_code, response.json()["detail"]) == (422, code)
        await console.auth.admin.execute("DELETE FROM sources WHERE id = $1", source)


async def test_tenant_admin_cannot_toggle_downloadable(console: Console) -> None:
    admin: Tenant = await console.auth.tenant(role="tenant_admin")
    browser = console.as_user(admin.email, admin.id)
    response = await browser.put(
        f"/api/v1/operator/sources/{uuid.uuid4()}/downloadable", json={"downloadable": True}
    )
    assert response.status_code == 403
    assert (await browser.get("/api/v1/operator/sources")).status_code == 403


async def test_operator_role_reads_register_columns_but_not_ragflow_ids(
    operator_role: asyncpg.Connection,
) -> None:
    await operator_role.fetch("SELECT id, title, licence_basis, downloadable FROM sources")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await operator_role.fetch("SELECT ragflow_document_ids FROM sources")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await operator_role.execute("UPDATE sources SET tags = ARRAY['sample-web']")
