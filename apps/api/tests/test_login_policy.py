"""P1b-06: the per-tenant login policy and tenant discovery by email domain.

Over HTTP in OIDC mode against PostgreSQL, with the fake identity provider. Each test
gives its tenants their own domains, so discovery has exactly one tenant per domain.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import asyncpg
import pytest

from tests.conftest import MigratedDatabase, migrate
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_operator import Console, console, owner  # noqa: F401 - fixtures
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

NEUTRAL = {"methods": ["sign_in_link"], "sso_kind": None}


def unique_domain() -> str:
    return f"d{uuid.uuid4().hex[:10]}.example"


async def set_policy(admin: asyncpg.Connection, tenant_id: uuid.UUID, **values: Any) -> None:
    """Arrange a policy as the owner (the console's SSO routes are P1b-07's tests)."""
    if values.get("sso_source_kind", "none") != "none":
        values.setdefault("sso_source_slug", f"ask-spore-{uuid.uuid4().hex[:12]}")
    columns = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(values))
    await admin.execute(
        f"UPDATE tenant_login_policy SET {columns} WHERE tenant_id = $1",
        tenant_id,
        *values.values(),
    )


async def discover(auth: Auth, email: str) -> dict[str, Any]:  # noqa: F811
    response = await auth.browser().post("/api/v1/auth/discover", json={"email": email})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- discovery ---------------------------------------------------------------------------


async def test_domain_resolves_to_its_tenants_methods(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, t.id, sso_source_kind="entra")
    assert await discover(auth, t.email) == {
        "methods": ["sso", "sign_in_link"],
        "sso_kind": "entra",
    }
    # Case and surrounding space do not matter; any address of the domain gets the same.
    assert await discover(auth, f"  {t.email.upper()} ") == await discover(auth, t.email)
    other = f"nobody-{uuid.uuid4().hex[:6]}@{t.email.partition('@')[2]}"
    assert await discover(auth, other) == await discover(auth, t.email)


async def test_links_off_leaves_only_sso(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, t.id, sso_source_kind="google", sign_in_links_enabled=False)
    assert await discover(auth, t.email) == {"methods": ["sso"], "sso_kind": "google"}


async def test_a_domain_of_tenant_a_never_offers_tenant_bs_methods(auth: Auth) -> None:  # noqa: F811
    a = await auth.tenant(domain=unique_domain())
    b = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, a.id, sso_source_kind="entra", sign_in_links_enabled=False)
    await set_policy(auth.admin, b.id, sso_source_kind="saml")
    assert await discover(auth, a.email) == {"methods": ["sso"], "sso_kind": "entra"}
    assert await discover(auth, b.email) == {"methods": ["sso", "sign_in_link"], "sso_kind": "saml"}
    # A user of tenant B whose address is at A's domain is offered A's methods only,
    # never B's: the answer is the domain's.
    await auth.admin.execute(
        "UPDATE users SET email = $2 WHERE id = $1",
        b.user_id,
        f"b-user@{a.email.partition('@')[2]}",
    )
    assert await discover(auth, f"b-user@{a.email.partition('@')[2]}") == {
        "methods": ["sso"],
        "sso_kind": "entra",
    }


async def test_unknown_domain_gets_the_same_answer_as_an_unknown_user(auth: Auth) -> None:  # noqa: F811
    links_only = await auth.tenant(domain=unique_domain())
    links_off = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, links_off.id, sign_in_links_enabled=False)
    suspended = await auth.tenant(domain=unique_domain(), status="suspended")
    await set_policy(auth.admin, suspended.id, sso_source_kind="oidc")
    domain = links_only.email.partition("@")[2]
    browser = auth.browser()
    answers = []
    for email in (
        f"nobody@{unique_domain()}",  # unknown domain
        f"nobody@{domain}",  # unknown user of a known domain
        links_only.email,  # known user
        links_off.email,  # tenant with links off and no SSO
        suspended.email,  # suspended tenant's domain, even with SSO configured
        "not-an-address",
        "user@localhost",
    ):
        response = await browser.post("/api/v1/auth/discover", json={"email": email})
        answers.append((response.status_code, response.json(), sorted(response.headers.keys())))
    assert all(answer == answers[0] for answer in answers)
    assert answers[0][:2] == (200, NEUTRAL)
    assert "set-cookie" not in answers[0][2]


async def test_a_domain_claimed_by_two_tenants_offers_nothing_tenant_specific(
    auth: Auth,  # noqa: F811
) -> None:
    domain = unique_domain()
    a = await auth.tenant(domain=domain)
    b = await auth.tenant(domain=domain)  # arranged as the owner; the console refuses it
    await set_policy(auth.admin, a.id, sso_source_kind="entra")
    await set_policy(auth.admin, b.id, sso_source_kind="google")
    assert await discover(auth, a.email) == NEUTRAL


async def test_discovery_answer_carries_no_tenant_identifiers(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, t.id, sso_source_kind="oidc", sso_source_slug="ask-spore-zz-test")
    response = await auth.browser().post("/api/v1/auth/discover", json={"email": t.email})
    for identifier in (str(t.id), "ask-spore-zz-test", str(t.user_id)):
        assert identifier not in response.text


# --- sign-in links follow the policy -----------------------------------------------------


async def test_links_refused_for_a_tenant_with_links_off(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, t.id, sso_source_kind="entra", sign_in_links_enabled=False)
    known = await auth.tenant(domain=unique_domain())
    known_response = await auth.request_link(auth.browser(), known.email)
    before = list(auth.idp.outbox)

    response = await auth.request_link(auth.browser(), t.email)
    # The same answer as for any address, and nothing is sent.
    assert (response.status_code, response.json()) == (
        known_response.status_code,
        known_response.json(),
    )
    assert auth.idp.outbox == [*before]
    assert await auth.audit("auth.link_requested", t.id) == []


async def test_links_back_on_sends_again(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    await set_policy(auth.admin, t.id, sign_in_links_enabled=False)
    await auth.request_link(auth.browser(), t.email)
    assert [e for e, _ in auth.idp.outbox if e == t.email] == []
    await set_policy(auth.admin, t.id, sign_in_links_enabled=True)
    await auth.sign_in(auth.browser(), t)


# --- the operator sets the policy --------------------------------------------------------


async def test_operator_sets_the_policy_and_it_is_audited(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    created = (
        await op.post(
            "/api/v1/operator/tenants",
            json={"slug": f"t-{uuid.uuid4().hex[:10]}", "display_name": "Synthetic Co"},
        )
    ).json()
    tenant_id = created["id"]
    path = f"/api/v1/operator/tenants/{tenant_id}/login-policy"
    body = {
        "sign_in_links_enabled": False,
        "jit_provisioning_enabled": True,
        "admin_mfa_required": False,
    }
    response = await op.put(path, json=body)
    assert response.status_code == 200, response.text
    assert {k: response.json()[k] for k in body} == body
    assert (await op.get(path)).json() == response.json()

    (event,) = await console.events("operator.login_policy_changed", uuid.UUID(tenant_id))
    assert event["actor"] is None and event["operator_id"] == str(await console.operator_id())
    assert event["before"] == {
        "sign_in_links_enabled": True,
        "sso_source_kind": "none",
        "sso_source_slug": None,
        "jit_provisioning_enabled": False,
        "admin_mfa_required": True,
    }
    assert event["after"] == {**event["before"], **body}
    # The same values again change nothing and write nothing.
    assert (await op.put(path, json=body)).status_code == 200
    assert len(await console.events("operator.login_policy_changed", uuid.UUID(tenant_id))) == 1


async def test_operator_policy_for_unknown_tenant_is_not_found(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    path = f"/api/v1/operator/tenants/{uuid.uuid4()}/login-policy"
    assert (await op.get(path)).status_code == 404
    body = {
        "sign_in_links_enabled": True,
        "jit_provisioning_enabled": False,
        "admin_mfa_required": True,
    }
    assert (await op.put(path, json=body)).status_code == 404


async def test_policy_body_takes_no_sso_fields_or_identifiers(console: Console) -> None:  # noqa: F811
    op = await console.operator()
    tenant = await console.auth.tenant(domain=unique_domain())
    path = f"/api/v1/operator/tenants/{tenant.id}/login-policy"
    base = {
        "sign_in_links_enabled": True,
        "jit_provisioning_enabled": False,
        "admin_mfa_required": True,
    }
    for extra in ({"sso_source_kind": "entra"}, {"tenant_id": str(uuid.uuid4())}):
        assert (await op.put(path, json={**base, **extra})).status_code == 422


# --- the table ---------------------------------------------------------------------------


async def test_every_new_tenant_gets_a_default_policy(admin_conn: asyncpg.Connection) -> None:
    tenant_id = uuid.uuid4()
    await admin_conn.execute(
        "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Policy Default')",
        tenant_id,
        f"p-{tenant_id.hex[:12]}",
    )
    row = await admin_conn.fetchrow(
        "SELECT * FROM tenant_login_policy WHERE tenant_id = $1", tenant_id
    )
    assert row is not None
    assert (row["sign_in_links_enabled"], row["sso_source_kind"], row["sso_source_slug"]) == (
        True,
        "none",
        None,
    )
    assert (row["jit_provisioning_enabled"], row["admin_mfa_required"]) == (False, True)
    # No entitlements row: removed, so the console's tenant list stays whole.
    await admin_conn.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    assert (
        await admin_conn.fetchval(
            "SELECT count(*) FROM tenant_login_policy WHERE tenant_id = $1", tenant_id
        )
        == 0
    )


async def test_app_role_reads_its_own_policy_but_cannot_change_it(
    app_conn: asyncpg.Connection,
    auth: Auth,  # noqa: F811
) -> None:
    t: Tenant = await auth.tenant(domain=unique_domain())
    await app_conn.execute("SELECT set_config('app.tenant_id', $1, false)", str(t.id))
    assert await app_conn.fetchval("SELECT count(*) FROM tenant_login_policy") == 1
    for statement in (
        "UPDATE tenant_login_policy SET sign_in_links_enabled = false",
        "DELETE FROM tenant_login_policy",
        "INSERT INTO tenant_login_policy (tenant_id) VALUES (gen_random_uuid())",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(statement)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"sso_source_kind": "github"}, "sso_kind_valid"),
        ({"sso_source_kind": "entra"}, "sso_slug_with_kind"),
        ({"sso_source_slug": "ask-spore-x"}, "sso_slug_with_kind"),
        ({"sso_source_kind": "entra", "sso_source_slug": "Bad Slug"}, "sso_slug_format"),
    ],
)
async def test_policy_constraints(
    admin_conn: asyncpg.Connection,
    auth: Auth,  # noqa: F811
    values: dict[str, str],
    constraint: str,
) -> None:
    t = await auth.tenant(domain=unique_domain())
    columns = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(values))
    with pytest.raises(asyncpg.CheckViolationError, match=constraint):
        await admin_conn.execute(
            f"UPDATE tenant_login_policy SET {columns} WHERE tenant_id = $1",
            t.id,
            *values.values(),
        )


def test_migration_carries_the_links_switch_both_ways(database: MigratedDatabase) -> None:
    """Revision 0020 moves ``sign_in_links_enabled`` from the entitlements; its downgrade
    moves it back. A tenant with links off stays off across both."""

    async def arrange() -> uuid.UUID:
        conn = await asyncpg.connect(database.dsn)
        try:
            tenant_id = uuid.uuid4()
            await conn.execute(
                "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Links Off')",
                tenant_id,
                f"m-{tenant_id.hex[:12]}",
            )
            await conn.execute("INSERT INTO tenant_entitlements (tenant_id) VALUES ($1)", tenant_id)
            await conn.execute(
                "UPDATE tenant_login_policy SET sign_in_links_enabled = false WHERE tenant_id = $1",
                tenant_id,
            )
            return tenant_id
        finally:
            await conn.close()

    async def fetch(sql: str, tenant_id: uuid.UUID) -> Any:
        conn = await asyncpg.connect(database.dsn)
        try:
            return await conn.fetchval(sql, tenant_id)
        finally:
            await conn.close()

    tenant_id = asyncio.run(arrange())
    migrate(database, "0012", down=True)
    assert (
        asyncio.run(
            fetch(
                "SELECT sign_in_links_enabled FROM tenant_entitlements WHERE tenant_id = $1",
                tenant_id,
            )
        )
        is False
    )
    migrate(database)
    assert (
        asyncio.run(
            fetch(
                "SELECT sign_in_links_enabled FROM tenant_login_policy WHERE tenant_id = $1",
                tenant_id,
            )
        )
        is False
    )
    asyncio.run(fetch("DELETE FROM tenants WHERE id = $1 RETURNING id", tenant_id))
