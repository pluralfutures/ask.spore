"""P1b-07: the operator configures a tenant's SSO source; the tenant admin sees it.

Over HTTP against PostgreSQL; Authentik is the fake (``tests.fake_idp``), which keeps
what the API asked it to configure. Client secrets must reach the provider and nothing
else: not the database, the audit trail, a response or the logs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from tests.fake_idp import sign
from tests.test_auth import Auth, auth  # noqa: F401 - fixture
from tests.test_login_policy import unique_domain
from tests.test_operator import Console, console, owner  # noqa: F401 - fixtures
from tests.test_saml_metadata import metadata_xml
from tests.test_sso import CaddyPaths, signed_in, slug_of
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

SECRET = "synthetic-client-secret-0f9e8d7c"
ENTRA = {
    "kind": "entra",
    "entra_tenant_id": "0b1c2d3e-4f50-4617-8899-aabbccddeeff",
    "client_id": "11111111-aaaa-4bbb-8ccc-222222222222",
    "client_secret": SECRET,
}


async def setup(console: Console, **tenant: Any) -> tuple[httpx.AsyncClient, Tenant, str]:  # noqa: F811
    op = await console.operator()
    t = await console.auth.tenant(domain=unique_domain(), **tenant)
    return op, t, f"/api/v1/operator/tenants/{t.id}/login-policy/sso"


async def everything_stored(console: Console, tenant_id: uuid.UUID) -> str:  # noqa: F811
    """The tenant's policy row and audit rows, as text, to search for secrets."""
    policy = await console.auth.admin.fetchrow(
        "SELECT * FROM tenant_login_policy WHERE tenant_id = $1", tenant_id
    )
    events = await console.auth.admin.fetch(
        "SELECT metadata FROM audit_events WHERE tenant_id = $1", tenant_id
    )
    return json.dumps({**dict(policy), "events": [e["metadata"] for e in events]}, default=str)


async def test_operator_configures_entra_and_the_secret_goes_to_authentik_only(
    console: Console,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    op, t, path = await setup(console)
    slug = await console.auth.admin.fetchval("SELECT slug FROM tenants WHERE id = $1", t.id)
    response = await op.put(path, json={**ENTRA, "admin_group_ids": [str(uuid.uuid4())]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sso_source_kind"] == "entra"
    assert body["sso_source_config"]["entra_tenant_id"] == ENTRA["entra_tenant_id"]
    assert body["sso_endpoints"] == {
        "redirect_uri": f"https://askspore.test.example/source/oauth/callback/sso-{slug}/"
    }
    source = console.auth.idp.sources[f"sso-{slug}"]
    assert source.client_secret == SECRET
    assert source.spec.tenant_id == t.id
    assert source.spec.verified_domains == (t.email.partition("@")[2],)

    assert SECRET not in response.text
    assert SECRET not in await everything_stored(console, t.id)
    assert SECRET not in capsys.readouterr().out
    (event,) = await console.events("operator.sso_source_changed", t.id)
    assert event["operator_id"] == str(await console.operator_id())
    assert event["before"] == {
        "sso_source_kind": "none",
        "sso_source_slug": None,
        "sso_config_sha256": None,
    }
    assert event["after"]["sso_source_kind"] == "entra"
    assert len(event["after"]["sso_config_sha256"]) == 64


async def test_resaving_keeps_the_secret_but_a_new_kind_needs_one(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    assert (await op.put(path, json=ENTRA)).status_code == 200
    unchanged = {k: v for k, v in ENTRA.items() if k != "client_secret"}
    assert (await op.put(path, json=unchanged)).status_code == 200
    assert len(await console.events("operator.sso_source_changed", t.id)) == 1  # no change
    google = {"kind": "google", "client_id": "123-abc.apps.googleusercontent.com"}
    response = await op.put(path, json=google)
    assert (response.status_code, response.json()) == (422, {"detail": "client_secret_required"})
    response = await op.put(path, json={**google, "client_secret": SECRET})
    assert response.status_code == 200 and response.json()["sso_source_kind"] == "google"


async def test_operator_configures_saml_from_metadata(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    response = await op.put(path, json={"kind": "saml", "metadata_xml": metadata_xml()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sso_source_config"]["idp_entity_id"] == "https://idp.synthetic.example/metadata"
    assert set(body["sso_endpoints"]) == {"acs_url", "sp_entity_id"}
    assert body["sso_endpoints"]["acs_url"].endswith(f"/source/saml/{body['sso_source_slug']}/acs/")
    spec = console.auth.idp.sources[body["sso_source_slug"]].spec
    assert spec.certificate_pem and spec.certificate_pem.startswith("-----BEGIN CERTIFICATE")
    assert "BEGIN CERTIFICATE" not in await everything_stored(console, t.id)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            {"kind": "saml", "metadata_xml": metadata_xml(prolog="<!DOCTYPE x>")},
            "metadata_doctype",
        ),
        (
            {
                "kind": "oidc",
                "issuer": "http://idp.example",
                "client_id": "c",
                "client_secret": "s",
            },
            "invalid_issuer",
        ),
    ],
)
async def test_unusable_source_fields_are_refused(
    console: Console,  # noqa: F811
    body: dict[str, Any],
    code: str,
) -> None:
    op, _, path = await setup(console)
    response = await op.put(path, json=body)
    assert (response.status_code, response.json()) == (422, {"detail": code})
    assert console.auth.idp.sources == {}


async def test_source_fields_take_no_identifiers_or_unknown_kinds(console: Console) -> None:  # noqa: F811
    op, _, path = await setup(console)
    for body in (
        {**ENTRA, "tenant_id": str(uuid.uuid4())},
        {**ENTRA, "kind": "github"},
        {"kind": "google", "client_id": "bad id with spaces", "client_secret": SECRET},
    ):
        assert (await op.put(path, json=body)).status_code == 422


async def test_a_tenant_without_verified_domains_gets_no_source(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    await console.auth.admin.execute(
        "UPDATE tenants SET verified_domains = '{}' WHERE id = $1", t.id
    )
    response = await op.put(path, json=ENTRA)
    assert (response.status_code, response.json()) == (422, {"detail": "no_verified_domains"})


async def test_authentik_failure_changes_nothing(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    console.auth.idp.fail_configure = True
    response = await op.put(path, json=ENTRA)
    assert (response.status_code, response.json()) == (502, {"detail": "source_not_configured"})
    kind = await console.auth.admin.fetchval(
        "SELECT sso_source_kind FROM tenant_login_policy WHERE tenant_id = $1", t.id
    )
    assert kind == "none"
    assert await console.events("operator.sso_source_changed", t.id) == []


async def test_operator_removes_the_source(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    slug = (await op.put(path, json=ENTRA)).json()["sso_source_slug"]
    response = await op.delete(path)
    assert response.status_code == 200
    assert (response.json()["sso_source_kind"], response.json()["sso_source_config"]) == (
        "none",
        {},
    )
    assert console.auth.idp.removed == [slug] and slug not in console.auth.idp.sources
    events = await console.events("operator.sso_source_changed", t.id)
    assert events[-1]["after"] == {
        "sso_source_kind": "none",
        "sso_source_slug": None,
        "sso_config_sha256": None,
    }
    # Removing again is a no-op.
    assert (await op.delete(path)).status_code == 200
    assert len(await console.events("operator.sso_source_changed", t.id)) == 2


async def test_a_source_configured_in_the_console_signs_users_in(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console)
    assert (await op.put(path, json=ENTRA)).status_code == 200
    harness = console.auth
    harness._transport = httpx.ASGITransport(app=CaddyPaths(harness.app))
    browser = harness.browser()
    started = await browser.post("/api/v1/auth/sso/start", json={"email": t.email})
    url = started.json()["redirect_url"]
    params = harness.idp.answer(url, email=t.email)
    response = await browser.get(f"/source/oauth/callback/{slug_of(url)}/", params=params)
    assert signed_in(response)


# --- the tenant admin sees the source, read-only -----------------------------------------


async def test_tenant_admin_sees_the_source_read_only(console: Console) -> None:  # noqa: F811
    op, t, path = await setup(console, role="tenant_admin")
    configured = (await op.put(path, json=ENTRA)).json()
    admin = console.as_user(t.email, t.id)
    response = await admin.get("/api/v1/admin/login-policy")
    assert response.status_code == 200
    assert response.json() == configured
    assert SECRET not in response.text
    for method in ("PUT", "POST", "DELETE", "PATCH"):
        assert (await admin.request(method, "/api/v1/admin/login-policy", json={})).status_code == (
            405
        )
    # Nor through the operator's routes.
    assert (await admin.put(path, json=ENTRA)).status_code == 403
    assert (await admin.delete(path)).status_code == 403


async def test_a_user_cannot_see_the_login_policy(console: Console) -> None:  # noqa: F811
    t = await console.auth.tenant(domain=unique_domain(), role="user")
    response = await console.as_user(t.email, t.id).get("/api/v1/admin/login-policy")
    assert response.status_code == 403


async def test_another_tenants_admin_sees_only_their_own_policy(console: Console) -> None:  # noqa: F811
    op, _, path = await setup(console)
    assert (await op.put(path, json=ENTRA)).status_code == 200
    b = await console.auth.tenant(domain=unique_domain(), role="tenant_admin")
    token = sign(console.auth.idp.key, email=b.email, tenant_id=b.id)
    browser = console.auth.browser()
    browser.headers["Authorization"] = f"Bearer {token}"
    assert (await browser.get("/api/v1/admin/login-policy")).json()["sso_source_kind"] == "none"
