"""P1a-02: sign-in links and OIDC token authentication, over HTTP, against PostgreSQL.

Authentik and the email provider are replaced by ``tests.fake_idp``; the token
validator, the link controls, the middleware and RLS are the real ones. Each
``httpx.AsyncClient`` is one browser (its own cookie jar).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import AuthConfig, AuthentikConfig, Secrets, Settings
from app.core.db import session_factory
from app.main import create_app
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import CONVERSATION_COLUMNS, CONVERSATION_DEFAULTS
from tests.fake_idp import CLIENT_ID, ISSUER, FakeSignInLinks, new_key, sign, validator_for
from tests.test_tenancy import Tenant, make_tenant

pytestmark = pytest.mark.usefixtures("database")

AUTHENTIK = AuthentikConfig(
    base_url="http://authentik-server:9000",
    issuer=ISSUER,
    client_id=CLIENT_ID,
    redirect_uri="https://ask-spore.invalid/auth/callback",
    sign_in_flow="ask-spore-sign-in-link",
    timeout_seconds=5,
    public_url="https://askspore.test.example",
)
BINDING = "askspore_link_binding"
SESSION = "askspore_session"


def oidc_settings(real: Settings, mode: str = "oidc") -> Any:
    auth = AuthConfig(mode=mode, authentik=AUTHENTIK)  # type: ignore[arg-type]
    return SimpleNamespace(
        models=real.models.model_copy(update={"auth": auth}),
        config_dir=real.config_dir,
        secrets=Secrets(
            mistral_api_key=SecretStr("unused"),
            ragflow_api_key=SecretStr("unused"),
            database_url=SecretStr("unused"),
            redis_url=SecretStr("unused"),
            phase0_bearer_token=None,
        ),
    )


class Auth:
    """An OIDC-mode app with the fake provider, and a way to open browsers on it."""

    def __init__(self, app: FastAPI, idp: FakeSignInLinks, admin: asyncpg.Connection) -> None:
        self.app = app
        self.idp = idp
        self.admin = admin
        self._transport = httpx.ASGITransport(app=app)
        self._browsers: list[httpx.AsyncClient] = []

    def browser(self) -> httpx.AsyncClient:
        http = httpx.AsyncClient(transport=self._transport, base_url="https://test")
        self._browsers.append(http)
        return http

    async def close(self) -> None:
        for http in self._browsers:
            await http.aclose()

    async def tenant(self, **kw: Any) -> Tenant:
        t = await make_tenant(self.admin, **kw)
        await self.idp.provision_user(email=t.email, display_name="Synthetic", tenant_id=t.id)
        return t

    async def request_link(self, browser: httpx.AsyncClient, email: str) -> httpx.Response:
        return await browser.post("/api/v1/auth/link", json={"email": email})

    async def complete(self, browser: httpx.AsyncClient, token: str) -> httpx.Response:
        return await browser.post("/api/v1/auth/link/complete", json={"token": token})

    async def sign_in(self, browser: httpx.AsyncClient, tenant: Tenant) -> None:
        assert (await self.request_link(browser, tenant.email)).status_code == 202
        response = await self.complete(browser, self.idp.last_token())
        assert response.status_code == 204, response.text

    async def audit(self, event: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.admin.fetch(
            "SELECT actor_user_id, metadata FROM audit_events "
            "WHERE event = $1 AND tenant_id = $2 ORDER BY created_at",
            event,
            tenant_id,
        )
        return [{"actor": r["actor_user_id"], **json.loads(r["metadata"])} for r in rows]


@pytest.fixture
async def auth(
    settings: Settings, engine: AsyncEngine, admin_conn: asyncpg.Connection
) -> AsyncIterator[Auth]:
    idp = FakeSignInLinks()
    app = create_app()
    app.state.settings = oidc_settings(settings)
    app.state.db_factory = session_factory(engine)
    app.state.sign_in_provider = idp
    app.state.token_validator = validator_for(idp.key)
    harness = Auth(app, idp, admin_conn)
    yield harness
    await harness.close()


def set_cookie(response: httpx.Response, name: str) -> str:
    (header,) = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    return header


# --- requesting a link -------------------------------------------------------------------


async def test_known_user_gets_a_link_bound_to_the_browser(auth: Auth) -> None:
    t = await auth.tenant()
    response = await auth.request_link(auth.browser(), t.email.upper())
    assert response.status_code == 202
    assert response.json() == {"status": "sent_if_known"}
    cookie = set_cookie(response, BINDING).lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/api/v1/auth/link"):
        assert attribute in cookie
    assert [email for email, _ in auth.idp.outbox] == [t.email]
    assert await auth.audit("auth.link_requested", t.id) == [
        {"actor": t.user_id, "method": "sign_in_link"}
    ]
    stored = await auth.admin.fetchval(
        "SELECT binding_hash FROM sign_in_links WHERE user_id = $1", t.user_id
    )
    assert len(stored) == 64 and stored not in cookie  # only the hash is stored


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param({"status": "suspended"}, id="suspended tenant"),
        pytest.param({"user_status": "deactivated"}, id="deactivated user"),
        pytest.param({"links_off": True}, id="links disabled"),
        pytest.param({"unknown": True}, id="unknown email"),
    ],
)
async def test_no_enumeration_and_no_link_for_ineligible_addresses(
    auth: Auth, setup: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    known = await auth.tenant()
    known_response = await auth.request_link(auth.browser(), known.email)

    t = await auth.tenant(
        status=setup.get("status", "active"), user_status=setup.get("user_status", "active")
    )
    if setup.get("links_off"):
        await auth.admin.execute(
            "UPDATE tenant_login_policy SET sign_in_links_enabled = false WHERE tenant_id = $1",
            t.id,
        )
    email = f"nobody-{uuid.uuid4().hex[:6]}@client.example" if setup.get("unknown") else t.email
    response = await auth.request_link(auth.browser(), email)

    # Indistinguishable from the known address: status, body, cookie attributes.
    assert response.status_code == known_response.status_code == 202
    assert response.json() == known_response.json()
    strip = lambda c: c.split(";", 1)[1]  # noqa: E731 - attributes after the value
    assert strip(set_cookie(response, BINDING)) == strip(set_cookie(known_response, BINDING))
    assert [e for e, _ in auth.idp.outbox] == [known.email]
    assert await auth.audit("auth.link_requested", t.id) == []
    assert email not in capsys.readouterr().out


async def test_links_per_window_are_capped(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    for _ in range(7):
        assert (await auth.request_link(browser, t.email)).status_code == 202
    assert len(auth.idp.outbox) == 5  # links_per_window
    limited = await auth.audit("auth.link_refused", t.id)
    assert [row["error_code"] for row in limited] == ["rate_limited", "rate_limited"]


# --- completing it: the post-click POST --------------------------------------------------


async def test_post_from_the_requesting_browser_signs_in(auth: Auth) -> None:
    t = await auth.tenant(user_status="invited", role="tenant_admin")
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    response = await auth.complete(browser, auth.idp.last_token())

    assert response.status_code == 204
    assert response.content == b""  # the token is never in a body
    session = set_cookie(response, SESSION).lower()
    for attribute in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attribute in session
    me = await browser.get("/api/v1/me")
    assert me.status_code == 200
    # P1b-08: the session's expiry, so the web app can renew it in time.
    assert me.json().pop("session_expires_at").endswith("Z")
    body = me.json()
    body.pop("session_expires_at")
    assert body == {
        "email": t.email,
        "display_name": "Synthetic User",
        "role": "tenant_admin",
        "tenant_display_name": "Synthetic Client",
    }
    user = await auth.admin.fetchrow(
        "SELECT status, last_login_at, last_login_method FROM users WHERE id = $1", t.user_id
    )
    assert user is not None
    assert (user["status"], user["last_login_method"]) == ("active", "sign_in_link")
    assert user["last_login_at"] is not None
    assert await auth.audit("auth.login", t.id) == [
        {"actor": t.user_id, "method": "sign_in_link", "status": "ok"}
    ]


async def test_get_of_the_link_consumes_nothing_and_a_later_post_succeeds(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    token = auth.idp.last_token()

    # What a mail scanner can do with the link: fetch it, with or without the fragment.
    for path in (
        f"/api/v1/auth/link/complete?token={token}",
        f"/api/v1/auth/link?token={token}",
        f"/auth/finish#token={token}",
        f"/auth/finish?token={token}",
    ):
        assert (await browser.get(path)).status_code in {401, 404, 405}
    assert auth.idp.redeemed == []
    assert (
        await auth.admin.fetchval(
            "SELECT consumed_at FROM sign_in_links WHERE user_id = $1", t.user_id
        )
        is None
    )

    assert (await auth.complete(browser, token)).status_code == 204


async def test_second_post_with_the_same_token_is_refused(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    token = auth.idp.last_token()
    assert (await auth.complete(browser, token)).status_code == 204

    again = await auth.complete(browser, token)
    assert again.status_code == 401
    # Success cleared this browser's binding cookie, so it now holds none (P1b-08).
    assert again.json() == {"detail": "no_binding"}
    # Another browser that requested its own link cannot replay it either.
    other = auth.browser()
    await auth.request_link(other, t.email)
    replay = await auth.complete(other, token)
    assert (replay.status_code, replay.json()) == (401, {"detail": "sign_in_failed"})
    assert auth.idp.redeemed == [token]  # refused by us, never resubmitted to the provider
    # The first browser's binding cookie was cleared on success; the replay from the
    # other browser is recognised by the token itself.
    assert (await auth.audit("auth.login_failed", INTERNAL_TENANT_ID))[-1]["error_code"] == (
        "no_binding"
    )
    failure = (await auth.audit("auth.login_failed", t.id))[-1]
    assert failure == {"actor": None, "method": "sign_in_link", "error_code": "used"}
    # The other browser's own pending link was not consumed by the refused replay.
    assert (
        await auth.admin.fetchval(
            "SELECT count(*) FROM sign_in_links WHERE user_id = $1 AND consumed_at IS NULL",
            t.user_id,
        )
        == 1
    )


async def test_link_opened_in_another_browser_is_refused_and_not_spent(auth: Auth) -> None:
    t = await auth.tenant()
    requesting = auth.browser()
    await auth.request_link(requesting, t.email)
    token = auth.idp.last_token()

    scanner = auth.browser()  # no binding cookie
    response = await auth.complete(scanner, token)
    assert response.status_code == 401
    # P1b-08: the landing page can say where to open the link; decided before any lookup.
    assert response.json() == {"detail": "no_binding"}
    assert auth.idp.redeemed == []
    failure = await auth.audit("auth.login_failed", INTERNAL_TENANT_ID)
    assert failure[-1]["error_code"] == "no_binding"

    assert (await auth.complete(requesting, token)).status_code == 204


async def test_binding_of_another_link_does_not_fit(auth: Auth) -> None:
    a = await auth.tenant()
    b = await auth.tenant()
    browser_a, browser_b = auth.browser(), auth.browser()
    await auth.request_link(browser_a, a.email)
    token_a = auth.idp.last_token()
    await auth.request_link(browser_b, b.email)

    # B's browser (bound to B's link) submits A's token: the provider's token names A.
    assert (await auth.complete(browser_b, token_a)).status_code == 401
    failure = await auth.audit("auth.login_failed", b.id)
    assert failure[-1]["error_code"] == "identity_mismatch"
    assert (await browser_b.get("/api/v1/me")).status_code == 401


async def test_expired_link_is_refused(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    await auth.admin.execute(
        "UPDATE sign_in_links SET created_at = now() - interval '16 minutes', "
        "expires_at = now() - interval '1 minute' WHERE user_id = $1",
        t.user_id,
    )
    assert (await auth.complete(browser, auth.idp.last_token())).status_code == 401
    assert auth.idp.redeemed == []
    assert (await auth.audit("auth.login_failed", t.id))[-1]["error_code"] == "expired"


async def test_link_expired_at_the_provider_is_refused(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    auth.idp.expire_all()
    assert (await auth.complete(browser, auth.idp.last_token())).status_code == 401
    assert (await auth.audit("auth.login_failed", t.id))[-1] == {
        "actor": t.user_id,
        "method": "sign_in_link",
        "error_code": "refused_by_provider",
    }


async def test_links_disabled_after_sending_refuses_the_sign_in(auth: Auth) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    await auth.admin.execute(
        "UPDATE tenant_login_policy SET sign_in_links_enabled = false WHERE tenant_id = $1", t.id
    )
    assert (await auth.complete(browser, auth.idp.last_token())).status_code == 401
    assert (await auth.audit("auth.login_failed", t.id))[-1]["error_code"] == "links_disabled"
    assert await auth.audit("auth.login", t.id) == []


async def test_sign_in_logs_carry_no_email_or_token(
    auth: Auth, capsys: pytest.CaptureFixture[str]
) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    token = auth.idp.last_token()
    await auth.complete(auth.browser(), token)
    await auth.complete(browser, token)
    await browser.get("/api/v1/me")
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line]
    assert {line["event"] for line in lines} >= {
        "auth.link_sent",
        "auth.login_failed",
        "auth.login",
    }
    for secret in (t.email, token, browser.cookies[SESSION]):
        assert secret not in out


# --- tokens on every request: tenant A cannot act on tenant B -----------------------------


async def _conversation(admin: asyncpg.Connection, t: Tenant) -> uuid.UUID:
    cid: uuid.UUID = await admin.fetchval(
        f"INSERT INTO conversations (tenant_id, user_id, title, {CONVERSATION_COLUMNS}) "
        f"VALUES ($1, $2, 'synthetic', {CONVERSATION_DEFAULTS}) RETURNING id",
        t.id,
        t.user_id,
    )
    return cid


async def test_token_for_tenant_a_cannot_act_on_tenant_b(auth: Auth) -> None:
    a = await auth.tenant()
    b = await auth.tenant()
    conversation_b = await _conversation(auth.admin, b)
    conversation_a = await _conversation(auth.admin, a)
    browser = auth.browser()
    await auth.sign_in(browser, a)

    listed = await browser.get("/api/v1/conversations")
    assert [c["id"] for c in listed.json()] == [str(conversation_a)]
    assert (await browser.get(f"/api/v1/conversations/{conversation_b}")).status_code == 404
    assert (await browser.delete(f"/api/v1/conversations/{conversation_b}")).status_code == 404
    assert (
        await auth.admin.fetchval(
            "SELECT count(*) FROM conversations WHERE id = $1", conversation_b
        )
        == 1
    )
    # Naming tenant B in the request changes nothing.
    response = await browser.get(
        f"/api/v1/conversations?tenant_id={b.id}", headers={"X-Tenant-Id": str(b.id)}
    )
    assert [c["id"] for c in response.json()] == [str(conversation_a)]


Forge = Callable[[FakeSignInLinks, Tenant, Tenant], str]


@pytest.mark.parametrize(
    "forge",
    [
        pytest.param(lambda idp, a, b: sign(idp.key, email=a.email, tenant_id=b.id), id="A as B"),
        pytest.param(lambda idp, a, b: sign(idp.key, email=b.email, tenant_id=a.id), id="B in A"),
        pytest.param(
            lambda idp, a, b: sign(idp.key, email=a.email, tenant_id=None), id="no tenant"
        ),
        pytest.param(
            lambda idp, a, b: sign(new_key(), email=a.email, tenant_id=a.id), id="other key"
        ),
        pytest.param(
            lambda idp, a, b: sign(idp.key, email=a.email, tenant_id=a.id, lifetime=-120),
            id="expired",
        ),
        pytest.param(
            lambda idp, a, b: sign(idp.key, email=a.email, tenant_id=a.id, aud="other-client"),
            id="audience",
        ),
        pytest.param(
            lambda idp, a, b: sign(idp.key, email=a.email, tenant_id=a.id, iss="https://evil/"),
            id="issuer",
        ),
        pytest.param(
            lambda idp, a, b: __import__("jwt").encode(
                {"email": a.email, "ask_spore_tenant": str(a.id), "iss": ISSUER, "aud": CLIENT_ID},
                "s" * 32,
                algorithm="HS256",
                headers={"kid": "test-key-1"},
            ),
            id="symmetric",
        ),
    ],
)
async def test_bad_or_mismatched_tokens_are_refused(auth: Auth, forge: Forge) -> None:
    a = await auth.tenant()
    b = await auth.tenant()
    token = forge(auth.idp, a, b)
    for headers, cookies in (({"Authorization": f"Bearer {token}"}, {}), ({}, {SESSION: token})):
        browser = auth.browser()
        browser.cookies.update(cookies)
        response = await browser.get("/api/v1/me", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}


async def test_bearer_header_works_like_the_cookie(auth: Auth) -> None:
    a = await auth.tenant()
    token = sign(auth.idp.key, email=a.email, tenant_id=a.id)
    response = await auth.browser().get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and response.json()["email"] == a.email


async def test_deactivated_user_with_a_valid_token_is_refused(auth: Auth) -> None:
    a = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, a)
    await auth.admin.execute("UPDATE users SET status = 'deactivated' WHERE id = $1", a.user_id)
    assert (await browser.get("/api/v1/me")).status_code == 401


async def test_logout_clears_the_session_cookie(auth: Auth) -> None:
    a = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, a)
    response = await browser.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert SESSION not in browser.cookies
    assert (await browser.get("/api/v1/me")).status_code == 401


async def test_old_cookie_is_refused_after_logout(auth: Auth) -> None:
    """P1a-02: sign-out revokes the session server-side, not only in the browser."""
    a = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, a)
    old = browser.cookies[SESSION]
    old_refresh = browser.cookies["askspore_refresh"]
    assert (await browser.get("/api/v1/me")).status_code == 200
    assert (await browser.post("/api/v1/auth/logout")).status_code == 204

    replay = auth.browser()
    replay.cookies.set(SESSION, old)
    assert (await replay.get("/api/v1/me")).status_code == 401
    bearer = await auth.browser().get("/api/v1/me", headers={"Authorization": f"Bearer {old}"})
    assert bearer.status_code == 401
    # P1b-08: the refresh token is revoked with it, at Authentik and in our list.
    assert auth.idp.revoked == [old, old_refresh]
    assert await auth.audit("auth.signed_out", a.id) == [{"actor": a.user_id, "status": "revoked"}]
    stored = await auth.admin.fetch(
        "SELECT token_sha256, user_id FROM revoked_sessions WHERE tenant_id = $1", a.id
    )
    # Only the hashes are kept, never the tokens.
    assert sorted((r["token_sha256"], r["user_id"]) for r in stored) == sorted(
        (hashlib.sha256(token.encode()).hexdigest(), a.user_id) for token in (old, old_refresh)
    )
    # A second sign-out with the same token revokes nothing new.
    again = auth.browser()
    again.cookies.set(SESSION, old)
    assert (await again.post("/api/v1/auth/logout")).status_code == 204
    assert len(await auth.audit("auth.signed_out", a.id)) == 1


async def test_logout_revokes_only_that_session(auth: Auth) -> None:
    a = await auth.tenant()
    first, second = auth.browser(), auth.browser()
    await auth.sign_in(first, a)
    await auth.sign_in(second, a)
    assert (await first.post("/api/v1/auth/logout")).status_code == 204
    assert (await second.get("/api/v1/me")).status_code == 200


async def test_logout_with_an_invalid_token_only_clears_the_cookie(auth: Auth) -> None:
    browser = auth.browser()
    browser.cookies.set(SESSION, "not-a-token")
    response = await browser.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in set_cookie(response, SESSION).lower()
    assert auth.idp.revoked == []


async def test_unauthenticated_routes_and_docs(auth: Auth) -> None:
    browser = auth.browser()
    assert (await browser.get("/api/v1/auth/mode")).json() == {"mode": "oidc"}
    assert (await browser.get("/healthz")).status_code == 200
    for path in ("/api/v1/me", "/api/v1/conversations", "/openapi.json", "/docs"):
        assert (await browser.get(path)).status_code == 401


# --- Phase 0 mode keeps working, and has no link routes -----------------------------------


async def test_phase0_mode_has_no_sign_in_links(
    settings: Settings, engine: AsyncEngine, admin_conn: asyncpg.Connection
) -> None:
    from tests.test_phase0_auth import ANALYST, TOKEN

    app = create_app()
    stub = oidc_settings(settings, mode="phase0")
    stub.secrets = Secrets(
        mistral_api_key=None,
        ragflow_api_key=SecretStr("unused"),
        database_url=SecretStr("unused"),
        redis_url=SecretStr("unused"),
        phase0_bearer_token=SecretStr(TOKEN),
    )
    app.state.settings = stub
    app.state.db_factory = session_factory(engine)
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TOKEN}", "X-User-Email": ANALYST}
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as http:
        assert (await http.get("/api/v1/auth/mode")).json() == {"mode": "phase0"}
        me = await http.get("/api/v1/me", headers=headers)
        assert me.status_code == 200 and me.json()["email"] == ANALYST
        link = await http.post("/api/v1/auth/link", json={"email": ANALYST}, headers=headers)
        assert link.status_code == 404
        discover = await http.post(
            "/api/v1/auth/discover", json={"email": ANALYST}, headers=headers
        )
        assert discover.status_code == 404
        # An OIDC token means nothing in Phase 0 mode.
        idp = FakeSignInLinks()
        token = sign(idp.key, email=ANALYST, tenant_id=INTERNAL_TENANT_ID)
        assert (
            await http.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401
