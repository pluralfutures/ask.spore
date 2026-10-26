"""P1b-07: sign-in through a tenant's SSO source, against PostgreSQL with the fake IdP.

The fake (``tests.fake_idp``) plays Authentik and the client's IdP. It mints the token
Authentik would, but does not apply the source mapping's domain and ``hd`` checks, so
every refusal here comes from the API's own checks (``app.auth.sso``). Each test gives
its tenants their own domains. ``CaddyPaths`` routes the IdP's callbacks the way
``infra/caddy/Caddyfile`` does, so the browser-binding cookies (path ``/source/``) are
sent as a browser would send them.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.sources import entra_config, google_config, oidc_config, saml_config, spec_for
from app.auth.sources import parse_idp_metadata as parse_metadata
from app.auth.sso import refusal_reason
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.authentik_expressions import run_source_mapping, run_source_policy
from tests.fake_idp import sign
from tests.test_auth import SESSION, Auth, auth  # noqa: F401 - fixture
from tests.test_consent import export_rows
from tests.test_login_policy import unique_domain
from tests.test_saml_metadata import metadata_xml
from tests.test_tenancy import Tenant
from tests.test_tenant_admin import add_user, as_user

pytestmark = pytest.mark.usefixtures("database")

REPO = Path(__file__).resolve().parents[3]
ADMIN_GROUP = "11111111-2222-4333-8444-555555555555"
FAILED = "/?sign_in=failed"


class CaddyPaths:
    """The Caddyfile's rewrites of Authentik's callback paths to the API's routes."""

    OAUTH = re.compile(r"^/source/oauth/callback/([a-z0-9-]+)/$")
    SAML = re.compile(r"^/source/saml/([a-z0-9-]+)/acs/$")

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if match := self.OAUTH.fullmatch(path):
                scope = {**scope, "path": f"/api/v1/auth/sso/oauth/{match[1]}"}
            elif match := self.SAML.fullmatch(path):
                scope = {**scope, "path": f"/api/v1/auth/sso/saml/{match[1]}"}
        await self.app(scope, receive, send)


@pytest.fixture
async def sso(auth: Auth) -> AsyncIterator[Auth]:  # noqa: F811
    auth._transport = httpx.ASGITransport(app=CaddyPaths(auth.app))
    yield auth


async def with_source(
    harness: Auth,
    kind: str = "entra",
    *,
    jit: bool = False,
    links: bool = True,
    admin_groups: list[str] | None = None,
    user_status: str = "invited",
) -> Tenant:
    """A tenant with one user, its own domain and an SSO source of ``kind``, configured
    in the fake and in the policy as the console would."""
    t = await harness.tenant(domain=unique_domain(), user_status=user_status)
    slug = await harness.admin.fetchval("SELECT slug FROM tenants WHERE id = $1", t.id)
    if kind == "entra":
        config = entra_config(
            uuid.uuid4(), "client-entra", [uuid.UUID(g) for g in admin_groups or []]
        )
    elif kind == "google":
        config = google_config("123-abc.apps.googleusercontent.com")
    elif kind == "oidc":
        config = oidc_config("https://idp.client.example/realms/x", "client-oidc")
    else:
        config = saml_config(parse_metadata(metadata_xml()))
    spec = spec_for(
        tenant_id=t.id,
        tenant_slug=slug,
        verified_domains=[t.email.partition("@")[2]],
        kind=kind,  # type: ignore[arg-type]
        config=config,
    )
    await harness.idp.configure_source(spec, SecretStr("synthetic-client-secret"))
    await harness.admin.execute(
        "UPDATE tenant_login_policy SET sso_source_kind = $2, sso_source_slug = $3, "
        "sso_source_config = $4::jsonb, jit_provisioning_enabled = $5, "
        "sign_in_links_enabled = $6 WHERE tenant_id = $1",
        t.id,
        kind,
        spec.slug,
        json.dumps(config),
        jit,
        links,
    )
    return t


def slug_of(redirect_url: str) -> str:
    return redirect_url.split("/")[3]


async def start(browser: httpx.AsyncClient, email: str) -> httpx.Response:
    return await browser.post("/api/v1/auth/sso/start", json={"email": email})


async def callback(
    browser: httpx.AsyncClient, slug: str, params: dict[str, str], *, saml: bool = False
) -> httpx.Response:
    if saml:
        return await browser.post(f"/source/saml/{slug}/acs/", data=params)
    return await browser.get(f"/source/oauth/callback/{slug}/", params=params)


async def sign_in(
    harness: Auth,
    browser: httpx.AsyncClient,
    email: str,
    *,
    saml: bool = False,
    **claims: Any,
) -> httpx.Response:
    """Start at the login page with ``email``; the user then signs in at the IdP as
    ``claims.get("as_email", email)``. Returns the callback's response."""
    started = await start(browser, email)
    assert started.status_code == 200, started.text
    url = started.json()["redirect_url"]
    params = harness.idp.answer(url, email=claims.pop("as_email", email), saml=saml, **claims)
    return await callback(browser, slug_of(url), params, saml=saml)


async def failures(harness: Auth, tenant_id: uuid.UUID) -> list[str]:
    return [e["error_code"] for e in await harness.audit("auth.login_failed", tenant_id)]


def signed_in(response: httpx.Response) -> bool:
    return (
        response.status_code == 303
        and response.headers["location"] == "/"
        and any(h.startswith(f"{SESSION}=") for h in response.headers.get_list("set-cookie"))
    )


def refused(response: httpx.Response, reason: str | None = None) -> bool:
    location = response.headers.get("location", "")
    return (
        response.status_code == 303
        and location.startswith(FAILED + "&reason=")
        and (reason is None or location == f"{FAILED}&reason={reason}")
        and not any(h.startswith(f"{SESSION}=") for h in response.headers.get_list("set-cookie"))
    )


# --- signing in -------------------------------------------------------------------------


async def test_invited_user_signs_in_with_entra(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    browser = sso.browser()
    started = await start(browser, t.email)
    assert started.status_code == 200
    assert started.json()["redirect_url"].startswith("https://idp.example/")
    for header in started.headers.get_list("set-cookie"):
        lowered = header.lower()
        for attribute in ("httponly", "secure", "samesite=lax", "path=/source/"):
            assert attribute in lowered, header
    params = sso.idp.answer(started.json()["redirect_url"], email=t.email)
    response = await callback(browser, slug_of(started.json()["redirect_url"]), params)
    assert signed_in(response), response.headers
    session = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{SESSION}=")]
    assert "samesite=strict" in session[0].lower() and "httponly" in session[0].lower()
    # The binding cookies are cleared, and the session works.
    assert (await browser.get("/api/v1/me")).json()["email"] == t.email
    user = await sso.admin.fetchrow(
        "SELECT status, last_login_method FROM users WHERE id = $1", t.user_id
    )
    assert (user["status"], user["last_login_method"]) == ("active", "sso")
    assert await sso.audit("auth.login", t.id) == [
        {"actor": t.user_id, "method": "sso:entra", "status": "ok"}
    ]


@pytest.mark.parametrize("kind", ["google", "oidc"])
async def test_other_oidc_kinds_sign_in(sso: Auth, kind: str) -> None:
    t = await with_source(sso, kind)
    hd = t.email.partition("@")[2] if kind == "google" else None
    assert signed_in(await sign_in(sso, sso.browser(), t.email, hd=hd))


async def test_saml_sign_in_posts_to_the_acs(sso: Auth) -> None:
    t = await with_source(sso, "saml")
    browser = sso.browser()
    started = await start(browser, t.email)
    for header in started.headers.get_list("set-cookie"):
        assert "samesite=none" in header.lower() and "secure" in header.lower()
    params = sso.idp.answer(started.json()["redirect_url"], email=t.email, saml=True)
    response = await callback(browser, slug_of(started.json()["redirect_url"]), params, saml=True)
    assert signed_in(response)


async def test_jit_provisions_a_user_of_a_verified_domain(sso: Auth) -> None:
    t = await with_source(sso, "entra", jit=True)
    new = f"new-{uuid.uuid4().hex[:6]}@{t.email.partition('@')[2]}"
    browser = sso.browser()
    assert signed_in(await sign_in(sso, browser, new))
    row = await sso.admin.fetchrow(
        "SELECT id, role, status, last_login_method FROM users WHERE tenant_id = $1 AND email = $2",
        t.id,
        new,
    )
    assert (row["role"], row["status"], row["last_login_method"]) == ("user", "active", "sso")
    (event,) = await sso.audit("auth.user_provisioned", t.id)
    assert event["actor"] == row["id"] and event["after"]["role"] == "user"
    assert (await browser.get("/api/v1/me")).json()["email"] == new


async def test_without_jit_only_invited_users_sign_in(sso: Auth) -> None:
    t = await with_source(sso, "entra", jit=False)
    new = f"new-{uuid.uuid4().hex[:6]}@{t.email.partition('@')[2]}"
    assert refused(await sign_in(sso, sso.browser(), new))
    assert await sso.admin.fetchval("SELECT count(*) FROM users WHERE email = $1", new) == 0
    assert await failures(sso, t.id) == ["not_invited"]


async def test_unverified_domain_is_refused(sso: Auth) -> None:
    t = await with_source(sso, "entra", jit=True)
    outsider = f"someone@{unique_domain()}"
    # The user started with the tenant's domain, then signed in at the IdP as another.
    assert refused(await sign_in(sso, sso.browser(), t.email, as_email=outsider))
    assert await sso.admin.fetchval("SELECT count(*) FROM users WHERE email = $1", outsider) == 0
    assert await failures(sso, t.id) == ["domain_not_verified"]


@pytest.mark.parametrize("hd", [None, "other.example", "gmail.com"])
async def test_google_hd_mismatch_is_refused(sso: Auth, hd: str | None) -> None:
    t = await with_source(sso, "google", jit=True)
    assert refused(await sign_in(sso, sso.browser(), t.email, hd=hd))
    assert await failures(sso, t.id) == ["hd_mismatch"]
    status = await sso.admin.fetchval("SELECT status FROM users WHERE id = $1", t.user_id)
    assert status == "invited"


async def test_unverified_address_at_the_idp_is_refused(sso: Auth) -> None:
    t = await with_source(sso, "oidc")
    assert refused(await sign_in(sso, sso.browser(), t.email, email_verified=False))
    assert await failures(sso, t.id) == ["email_unverified"]


async def test_deactivated_user_is_refused(sso: Auth) -> None:
    t = await with_source(sso, "entra", jit=True, user_status="deactivated")
    assert refused(await sign_in(sso, sso.browser(), t.email))
    assert await failures(sso, t.id) == ["user_inactive"]


async def test_address_of_another_tenants_user_is_not_provisioned(sso: Auth) -> None:
    a = await with_source(sso, "entra", jit=True)
    b = await sso.tenant(domain=unique_domain())
    # B's user has an address at A's verified domain (invited there before A's domain
    # was verified, say): JIT at A must not create a second user for it.
    shared = f"shared-{uuid.uuid4().hex[:6]}@{a.email.partition('@')[2]}"
    await sso.admin.execute("UPDATE users SET email = $2 WHERE id = $1", b.user_id, shared)
    assert refused(await sign_in(sso, sso.browser(), shared))
    assert await failures(sso, a.id) == ["email_in_other_tenant"]
    assert await sso.admin.fetchval("SELECT count(*) FROM users WHERE email = $1", shared) == 1


async def test_entra_admin_groups_set_the_role_at_every_sign_in(sso: Auth) -> None:
    t = await with_source(sso, "entra", jit=True, admin_groups=[ADMIN_GROUP])
    assert signed_in(await sign_in(sso, sso.browser(), t.email, groups=(ADMIN_GROUP,)))
    assert await sso.admin.fetchval("SELECT role FROM users WHERE id = $1", t.user_id) == (
        "tenant_admin"
    )
    assert signed_in(await sign_in(sso, sso.browser(), t.email, groups=("another-group",)))
    assert await sso.admin.fetchval("SELECT role FROM users WHERE id = $1", t.user_id) == "user"
    changes = await sso.audit("auth.role_from_sso", t.id)
    assert [(c["before"]["role"], c["after"]["role"]) for c in changes] == [
        ("user", "tenant_admin"),
        ("tenant_admin", "user"),
    ]


async def test_without_group_mapping_the_role_is_left_alone(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    await sso.admin.execute("UPDATE users SET role = 'tenant_admin' WHERE id = $1", t.user_id)
    assert signed_in(await sign_in(sso, sso.browser(), t.email, groups=(ADMIN_GROUP,)))
    role = await sso.admin.fetchval("SELECT role FROM users WHERE id = $1", t.user_id)
    assert role == "tenant_admin"


# --- tenant isolation -------------------------------------------------------------------


async def test_a_token_from_a_source_bound_to_tenant_a_cannot_act_in_tenant_b(sso: Auth) -> None:
    a = await with_source(sso, "entra", jit=True)
    b = await with_source(sso, "entra", jit=True, user_status="active")
    b_slug = await sso.admin.fetchval(
        "SELECT sso_source_slug FROM tenant_login_policy WHERE tenant_id = $1", b.id
    )

    # 1. A's IdP vouches for B's user: refused, and B's user is untouched.
    assert refused(await sign_in(sso, sso.browser(), a.email, as_email=b.email))
    assert await failures(sso, a.id) == ["domain_not_verified"]
    assert await sso.audit("auth.login", b.id) == []

    # 2. The token Authentik would mint for that (A's tenant, B's address) is refused by
    #    every route: it names no user of A, and it can never name a user of B.
    token = sign(sso.idp.key, email=b.email, tenant_id=a.id, ask_spore_sso={"source": "x"})
    browser = sso.browser()
    browser.headers["Authorization"] = f"Bearer {token}"
    assert (await browser.get("/api/v1/me")).status_code == 401
    assert (await browser.get("/api/v1/conversations")).status_code == 401

    # 3. A sign-in started for B whose IdP answer is delivered to A's source: refused
    #    before either source is asked.
    browser = sso.browser()
    started = await start(browser, b.email)
    params = sso.idp.answer(started.json()["redirect_url"], email=b.email)
    a_slug = await sso.admin.fetchval(
        "SELECT sso_source_slug FROM tenant_login_policy WHERE tenant_id = $1", a.id
    )
    finished = len(sso.idp.finished)
    assert refused(await callback(browser, a_slug, params))
    assert len(sso.idp.finished) == finished
    assert await failures(sso, b.id) == ["source_mismatch"]

    # 4. A misconfigured source that stamps B's tenant on A's users: refused.
    sso.idp.mint_tenant = b.id
    assert refused(await sign_in(sso, sso.browser(), a.email))
    sso.idp.mint_tenant = None
    # 5. A token claiming another source than the one the sign-in went through: refused.
    sso.idp.mint_source = b_slug
    assert refused(await sign_in(sso, sso.browser(), a.email))
    sso.idp.mint_source = None
    assert (await failures(sso, a.id))[-2:] == ["tenant_mismatch", "source_mismatch"]
    assert await sso.audit("auth.login", b.id) == []
    assert (
        await sso.admin.fetchval("SELECT last_login_at FROM users WHERE id = $1", b.user_id) is None
    )


# --- browser binding and single use -----------------------------------------------------


async def test_the_callback_needs_the_browser_that_started(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    started = await start(sso.browser(), t.email)
    params = sso.idp.answer(started.json()["redirect_url"], email=t.email)
    other = sso.browser()  # a different browser: no binding cookie
    assert refused(await callback(other, slug_of(started.json()["redirect_url"]), params))
    assert sso.idp.finished == []  # refused before Authentik was asked
    last = (await sso.audit("auth.login_failed", INTERNAL_TENANT_ID))[-1]
    # Before the attempt is found its source is unknown: "sso" without a kind (P1c-02).
    assert (last["method"], last["error_code"]) == ("sso", "no_binding")


async def test_an_attempt_is_used_once(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    browser = sso.browser()
    started = await start(browser, t.email)
    cookies = {c.name: c.value for c in browser.cookies.jar}
    url = started.json()["redirect_url"]
    params = sso.idp.answer(url, email=t.email)
    assert signed_in(await callback(browser, slug_of(url), params))
    replay = sso.browser()
    for name, value in cookies.items():
        replay.cookies.set(name, value, path="/source/")
    assert refused(await callback(replay, slug_of(url), params))
    assert await failures(sso, t.id) == ["used"]


async def test_an_expired_attempt_is_refused(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    browser = sso.browser()
    started = await start(browser, t.email)
    await sso.admin.execute(
        "UPDATE sso_attempts SET created_at = now() - interval '11 minutes', "
        "expires_at = now() - interval '1 minute' WHERE tenant_id = $1",
        t.id,
    )
    params = sso.idp.answer(started.json()["redirect_url"], email=t.email)
    assert refused(await callback(browser, slug_of(started.json()["redirect_url"]), params))
    assert await failures(sso, t.id) == ["expired"]


async def test_a_source_removed_mid_sign_in_refuses_it(sso: Auth) -> None:
    t = await with_source(sso, "entra")
    browser = sso.browser()
    started = await start(browser, t.email)
    await sso.admin.execute(
        "UPDATE tenant_login_policy SET sso_source_kind = 'none', sso_source_slug = NULL "
        "WHERE tenant_id = $1",
        t.id,
    )
    params = sso.idp.answer(started.json()["redirect_url"], email=t.email)
    assert refused(await callback(browser, slug_of(started.json()["redirect_url"]), params))
    assert await failures(sso, t.id) == ["source_changed"]


async def test_start_answers_alike_for_unknown_domains_and_domains_without_sso(sso: Auth) -> None:
    links_only = await sso.tenant(domain=unique_domain())
    answers = []
    for email in (f"x@{unique_domain()}", links_only.email, "not-an-address"):
        response = await start(sso.browser(), email)
        answers.append((response.status_code, response.json(), response.headers.get("set-cookie")))
    assert answers == [(409, {"detail": "sso_unavailable"}, None)] * 3


async def test_nothing_identifying_reaches_the_logs(
    sso: Auth, capsys: pytest.CaptureFixture[str]
) -> None:
    t = await with_source(sso, "entra", jit=True)
    browser = sso.browser()
    response = await sign_in(sso, browser, t.email)
    assert signed_in(response)
    outsider = f"x@{unique_domain()}"
    assert refused(await sign_in(sso, sso.browser(), t.email, as_email=outsider))
    out = capsys.readouterr().out
    assert '"event":"auth.login"' in out and '"error_code":"domain_not_verified"' in out
    token = browser.cookies.get(SESSION)
    assert token and token not in out
    for address in (t.email, outsider, t.email.partition("@")[2]):
        assert address not in out


# --- the routing the IdPs rely on -------------------------------------------------------


def test_caddy_routes_the_callback_paths_to_the_api() -> None:
    caddyfile = (REPO / "infra" / "caddy" / "Caddyfile").read_text()
    assert "rewrite * /api/v1/auth/sso/oauth/{re.sso_oauth.1}" in caddyfile
    assert "rewrite * /api/v1/auth/sso/saml/{re.sso_saml.1}" in caddyfile
    assert r"^/source/oauth/callback/([a-z0-9-]+)/$" in caddyfile
    assert r"^/source/saml/([a-z0-9-]+)/acs/$" in caddyfile


# --- P1c-02: refusals by the source end on our page, with the kind in the audit ----------

KINDS = ["entra", "google", "oidc", "saml"]


def claims_for(kind: str, email: str) -> dict[str, Any]:
    domain = email.partition("@")[2]
    return {"saml": True} if kind == "saml" else {"hd": domain if kind == "google" else None}


@pytest.mark.parametrize("kind", KINDS)
async def test_every_kind_records_its_kind_on_login(sso: Auth, kind: str) -> None:
    t = await with_source(sso, kind)
    sso.idp.apply_mapping = True
    assert signed_in(await sign_in(sso, sso.browser(), t.email, **claims_for(kind, t.email)))
    assert [e["method"] for e in await sso.audit("auth.login", t.id)] == [f"sso:{kind}"]
    # The users column keeps the method family (its constraint), not the kind.
    method = await sso.admin.fetchval(
        "SELECT last_login_method FROM users WHERE id = $1", t.user_id
    )
    assert method == "sso"
    assert sso.idp.events == []


@pytest.mark.parametrize("kind", KINDS)
async def test_an_out_of_domain_sign_in_is_refused_by_the_source_on_our_page(
    sso: Auth, kind: str
) -> None:
    t = await with_source(sso, kind, jit=True)
    sso.idp.apply_mapping = True
    outsider = f"someone@{unique_domain()}"
    claims = claims_for(kind, outsider)
    minted = len(sso.idp.refresh_tokens)
    response = await sign_in(sso, sso.browser(), t.email, as_email=outsider, **claims)
    # Our sign-in page with a reason; not an Authentik error, no 500.
    assert refused(response, reason="domain"), response.headers
    # Authentik denied the flow through its policy: no mapping exception, no
    # configuration_error event, and no token was minted for the outsider.
    assert sso.idp.events == []
    assert len(sso.idp.refresh_tokens) == minted
    (failed,) = await sso.audit("auth.login_failed", t.id)
    assert (failed["method"], failed["error_code"]) == (f"sso:{kind}", "domain_not_verified")
    assert await sso.admin.fetchval("SELECT count(*) FROM users WHERE email = $1", outsider) == 0


@pytest.mark.parametrize("kind", ["google", "oidc"])
async def test_an_address_the_idp_did_not_verify_is_refused_by_the_source(
    sso: Auth, kind: str
) -> None:
    t = await with_source(sso, kind, jit=True)
    sso.idp.apply_mapping = True
    claims = claims_for(kind, t.email)
    response = await sign_in(sso, sso.browser(), t.email, email_verified=False, **claims)
    assert refused(response, reason="unverified")
    assert sso.idp.events == []
    (failed,) = await sso.audit("auth.login_failed", t.id)
    assert (failed["method"], failed["error_code"]) == (f"sso:{kind}", "email_unverified")


async def test_a_google_hd_outside_the_domains_is_refused_by_the_source(sso: Auth) -> None:
    t = await with_source(sso, "google", jit=True)
    sso.idp.apply_mapping = True
    assert refused(await sign_in(sso, sso.browser(), t.email, hd="gmail.com"), reason="domain")
    assert sso.idp.events == []
    assert await failures(sso, t.id) == ["hd_mismatch"]


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("not_invited", "no_access"),
        # Never tells an outsider that the address is another tenant's user.
        ("email_in_other_tenant", "no_access"),
        ("no_binding", "start_again"),
        ("tenant_mismatch", "failed"),
        ("refused_by_source", "failed"),
    ],
)
def test_the_page_gets_a_coarse_reason_never_the_code(code: str, reason: str) -> None:
    assert refusal_reason(code) == reason


async def test_the_refusal_reason_does_not_tell_another_tenants_user_apart(sso: Auth) -> None:
    a = await with_source(sso, "entra", jit=False)
    b = await sso.tenant(domain=unique_domain())
    shared = f"shared-{uuid.uuid4().hex[:6]}@{a.email.partition('@')[2]}"
    await sso.admin.execute("UPDATE users SET email = $2 WHERE id = $1", b.user_id, shared)
    stranger = f"new-{uuid.uuid4().hex[:6]}@{a.email.partition('@')[2]}"
    first = await sign_in(sso, sso.browser(), shared)
    second = await sign_in(sso, sso.browser(), stranger)
    assert refused(first, "no_access") and refused(second, "no_access")
    assert await failures(sso, a.id) == ["email_in_other_tenant", "not_invited"]


async def test_the_audit_export_shows_the_kind_of_each_sso_event(sso: Auth) -> None:
    t = await with_source(sso, "google", jit=True)
    sso.idp.apply_mapping = True
    domain = t.email.partition("@")[2]
    assert signed_in(await sign_in(sso, sso.browser(), t.email, hd=domain))
    outsider = f"x@{unique_domain()}"
    assert refused(await sign_in(sso, sso.browser(), t.email, as_email=outsider, hd=domain))
    admin = await add_user(sso.admin, t, role="tenant_admin")
    rows = export_rows(await as_user(sso, admin.email, t.id).get("/api/v1/admin/audit-log"))
    methods = {
        (r["event"], json.loads(r["metadata"]).get("method"))
        for r in rows
        if r["event"].startswith("auth.")
    }
    assert {("auth.login", "sso:google"), ("auth.login_failed", "sso:google")} <= methods
    assert outsider not in json.dumps(rows)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "info",
    [
        {},
        {"email": None},
        {"email": "no-at-sign"},
        {"email": 42, "hd": None, "email_verified": "yes"},
        {"mail": "x@client.example", "hd": ["a"]},
        {"userPrincipalName": "  X@Client.Example  ", "email_verified": "true"},
    ],
)
def test_the_mapping_never_raises_whatever_the_idp_sends(kind: str, info: dict[str, Any]) -> None:
    # An exception in a source mapping is what Authentik answers with HTTP 500 and
    # configuration_error events (Phase 1b release 2.4).
    config = {
        "entra": entra_config(uuid.uuid4(), "c", []),
        "google": google_config("c"),
        "oidc": oidc_config("https://idp.client.example", "c"),
        "saml": saml_config(parse_metadata(metadata_xml())),
    }[kind]
    spec = spec_for(
        tenant_id=uuid.uuid4(),
        tenant_slug="cc",
        verified_domains=["client.example"],
        kind=kind,  # type: ignore[arg-type]
        config=config,
    )
    name_id = SimpleNamespace(text=info.get("email") or "")
    properties = run_source_mapping(spec, info=info, properties={"groups": ["g"]}, name_id=name_id)
    passing, messages = run_source_policy({"prompt_data": properties})
    refusal = properties.get("attributes", {}).get("ask_spore_refusal")
    assert passing == (refusal is None)
    assert messages == ([] if refusal is None else [f"ask-spore-refusal:{refusal}"])
