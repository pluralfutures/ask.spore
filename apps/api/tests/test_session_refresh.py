"""P1b-08: the session is renewed before the access token expires, and sign-out
revokes the refresh token too. Over HTTP against PostgreSQL with the fake provider."""

from __future__ import annotations

import pytest

from tests.fake_idp import sign
from tests.test_auth import SESSION, Auth, auth, set_cookie  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("database")

REFRESH = "askspore_refresh"


async def test_sign_in_sets_a_refresh_cookie_for_the_auth_routes_only(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.request_link(browser, t.email)
    response = await auth.complete(browser, auth.idp.last_token())
    cookie = set_cookie(response, REFRESH).lower()
    for attribute in (
        "httponly",
        "secure",
        "samesite=strict",
        "path=/api/v1/auth",
        "max-age=86400",
    ):
        assert attribute in cookie


async def test_refresh_keeps_the_session_and_retires_the_old_tokens(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    old_access, old_refresh = browser.cookies[SESSION], browser.cookies[REFRESH]

    response = await browser.post("/api/v1/auth/refresh")
    assert response.status_code == 204
    new_access, new_refresh = browser.cookies[SESSION], browser.cookies[REFRESH]
    assert new_access != old_access and new_refresh != old_refresh
    assert (await browser.get("/api/v1/me")).json()["email"] == t.email
    # The previous access token stops working, by our own list.
    stale = auth.browser()
    stale.headers["Authorization"] = f"Bearer {old_access}"
    assert (await stale.get("/api/v1/me")).status_code == 401
    assert await auth.audit("auth.session_refreshed", t.id) == [
        {"actor": t.user_id, "status": "ok"}
    ]


async def test_an_expired_access_token_can_still_be_renewed(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    expired = sign(auth.idp.key, email=t.email, tenant_id=t.id, lifetime=-120)
    headers = {"Authorization": f"Bearer {expired}"}
    assert (await browser.get("/api/v1/me", headers=headers)).status_code == 401
    response = await browser.post("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 204
    renewed = set_cookie(response, SESSION).split(";")[0].split("=", 1)[1]
    fresh = {"Authorization": f"Bearer {renewed}"}
    assert (await browser.get("/api/v1/me", headers=fresh)).status_code == 200


async def test_a_spent_refresh_token_is_refused_even_if_the_provider_took_it(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    old_refresh = browser.cookies[REFRESH]
    claims = dict(auth.idp.refresh_tokens[old_refresh])
    assert (await browser.post("/api/v1/auth/refresh")).status_code == 204
    # An Authentik that failed to rotate it would accept it again; our list does not.
    auth.idp.refresh_tokens[old_refresh] = claims
    replay = auth.browser()
    replay.cookies.set(REFRESH, old_refresh, path="/api/v1/auth")
    response = await replay.post("/api/v1/auth/refresh")
    assert (response.status_code, response.json()) == (401, {"detail": "refresh_refused"})
    assert SESSION not in replay.cookies


async def test_revocation_makes_the_old_tokens_fail(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    old_access, old_refresh = browser.cookies[SESSION], browser.cookies[REFRESH]
    auth.idp.ignore_refresh_revocation = True  # the provider's revocation did not take
    assert (await browser.post("/api/v1/auth/logout")).status_code == 204
    assert old_refresh in auth.idp.revoked and old_access in auth.idp.revoked

    replay = auth.browser()
    replay.cookies.set(SESSION, old_access)
    replay.cookies.set(REFRESH, old_refresh, path="/api/v1/auth")
    assert (await replay.get("/api/v1/me")).status_code == 401
    assert (await replay.post("/api/v1/auth/refresh")).status_code == 401
    # Whatever the provider issued for the replay was revoked straight away.
    issued = [token for token in auth.idp.refresh_tokens if token != old_refresh]
    assert all(token in auth.idp.revoked for token in issued)
    assert await auth.audit("auth.session_refreshed", t.id) == []


async def test_refresh_needs_the_refresh_cookie(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    browser.cookies.delete(REFRESH)
    response = await browser.post("/api/v1/auth/refresh")
    assert response.status_code == 401
    assert any(
        h.startswith(f"{SESSION}=") and "max-age=0" in h.lower()
        for h in response.headers.get_list("set-cookie")
    )


async def test_a_deactivated_user_cannot_renew(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    await auth.admin.execute("UPDATE users SET status = 'deactivated' WHERE id = $1", t.user_id)
    assert (await browser.post("/api/v1/auth/refresh")).status_code == 401


async def test_another_users_refresh_token_does_not_renew_this_session(auth: Auth) -> None:  # noqa: F811
    a, b = await auth.tenant(), await auth.tenant()
    browser_a, browser_b = auth.browser(), auth.browser()
    await auth.sign_in(browser_a, a)
    await auth.sign_in(browser_b, b)
    mixed = auth.browser()
    mixed.cookies.set(SESSION, browser_a.cookies[SESSION])
    mixed.cookies.set(REFRESH, browser_b.cookies[REFRESH], path="/api/v1/auth")
    assert (await mixed.post("/api/v1/auth/refresh")).status_code == 401
    assert await auth.audit("auth.session_refreshed", b.id) == []


async def test_refresh_is_not_logged_with_tokens(
    auth: Auth,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    t = await auth.tenant()
    browser = auth.browser()
    await auth.sign_in(browser, t)
    old_refresh = browser.cookies[REFRESH]
    await browser.post("/api/v1/auth/refresh")
    out = capsys.readouterr().out
    for secret in (old_refresh, browser.cookies[REFRESH], browser.cookies[SESSION], t.email):
        assert secret not in out
