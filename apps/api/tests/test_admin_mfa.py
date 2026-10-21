"""P1b-08: a second factor for tenant admins on sign-in links, through Authentik's
authenticator validation stage bound to the admin group, relayed by the API.

The fake (``tests.fake_idp``) stands in for the stage: members of its ``mfa_group`` are
asked for a TOTP code (``TOTP_CODE``), first to enrol, then to validate.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.tenancy.models import INTERNAL_TENANT_ID
from tests.fake_idp import SETUP_URI, TOTP_CODE
from tests.test_auth import SESSION, Auth, auth, set_cookie  # noqa: F401 - fixture
from tests.test_operator import Console, console, owner  # noqa: F401 - fixtures
from tests.test_tenancy import Tenant

pytestmark = pytest.mark.usefixtures("database")

MFA_BINDING = "askspore_mfa_binding"
MFA_STATE = "askspore_mfa_state"


async def admin(harness: Auth, *, in_group: bool = True, enrolled: bool = True) -> Tenant:
    t = await harness.tenant(role="tenant_admin")
    if in_group:
        await harness.idp.set_admin_mfa(t.email, True)
    if enrolled:
        harness.idp.totp_enrolled.add(t.email)
    return t


async def link(harness: Auth, browser: httpx.AsyncClient, t: Tenant) -> httpx.Response:
    await harness.request_link(browser, t.email)
    return await harness.complete(browser, harness.idp.last_token())


async def code(browser: httpx.AsyncClient, value: str = TOTP_CODE) -> httpx.Response:
    return await browser.post("/api/v1/auth/mfa", json={"code": value})


async def test_an_admin_signs_in_with_a_second_factor(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth)
    browser = auth.browser()
    pending = await link(auth, browser, t)
    assert pending.status_code == 200
    assert pending.json() == {
        "status": "mfa_required",
        "stage": "validate",
        "setup_uri": None,
        "failed": False,
    }
    assert pending.headers["cache-control"] == "no-store"
    assert not any(h.startswith(f"{SESSION}=") for h in pending.headers.get_list("set-cookie"))
    for name in (MFA_BINDING, MFA_STATE):
        cookie = set_cookie(pending, name).lower()
        for attribute in ("httponly", "secure", "samesite=strict", "path=/api/v1/auth/mfa"):
            assert attribute in cookie
    assert (await browser.get("/api/v1/me")).status_code == 401  # not signed in yet

    done = await code(browser)
    assert done.status_code == 204
    assert (await browser.get("/api/v1/me")).json()["role"] == "tenant_admin"
    assert await auth.audit("auth.login", t.id) == [
        {"actor": t.user_id, "method": "sign_in_link", "status": "ok", "mfa": True}
    ]


async def test_first_sign_in_enrols_an_authenticator(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth, enrolled=False)
    browser = auth.browser()
    pending = await link(auth, browser, t)
    assert (pending.json()["stage"], pending.json()["setup_uri"]) == ("setup", SETUP_URI)
    assert (await code(browser)).status_code == 204
    # The next sign-in validates the enrolled authenticator.
    again = auth.browser()
    assert (await link(auth, again, t)).json()["stage"] == "validate"


async def test_a_wrong_code_asks_again_then_five_attempts_end_it(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth)
    browser = auth.browser()
    await link(auth, browser, t)
    for _ in range(4):
        retry = await code(browser, "000000")
        assert (retry.status_code, retry.json()["failed"]) == (200, True)
    refused = await code(browser, "000000")
    assert (refused.status_code, refused.json()) == (401, {"detail": "sign_in_failed"})
    # Even the right code is refused now; the link must be asked for again.
    assert (await code(browser)).status_code == 401
    assert len(await auth.audit("auth.mfa_failed", t.id)) == 5
    codes = [e["error_code"] for e in await auth.audit("auth.login_failed", t.id)]
    assert codes == ["too_many_attempts"]
    # The refusal cleared the browser's MFA cookies, so the last code had no binding.
    last = (await auth.audit("auth.login_failed", INTERNAL_TENANT_ID))[-1]
    assert last["error_code"] == "no_binding"
    assert await auth.audit("auth.login", t.id) == []


async def test_the_code_must_come_from_the_browser_that_posted_the_link(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth)
    await link(auth, auth.browser(), t)
    other = auth.browser()
    response = await code(other)
    assert response.status_code == 401
    last = (await auth.audit("auth.login_failed", INTERNAL_TENANT_ID))[-1]
    assert (last["method"], last["error_code"]) == ("sign_in_link", "no_binding")
    assert auth.idp.mfa_pending, "the pending challenge was not touched"
    assert await auth.audit("auth.login", t.id) == []


async def test_an_expired_challenge_is_refused(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth)
    browser = auth.browser()
    await link(auth, browser, t)
    await auth.admin.execute(
        "UPDATE mfa_challenges SET created_at = now() - interval '6 minutes', "
        "expires_at = now() - interval '1 minute' WHERE tenant_id = $1",
        t.id,
    )
    assert (await code(browser)).status_code == 401
    assert (await auth.audit("auth.login_failed", t.id))[-1]["error_code"] == "expired"


async def test_an_admin_without_the_second_factor_is_refused_and_put_in_the_group(
    auth: Auth,  # noqa: F811
) -> None:
    """Fail closed: Authentik did not ask (the admin is not in its group), so the API
    refuses, revokes what Authentik issued, and fixes the membership."""
    t = await admin(auth, in_group=False)
    browser = auth.browser()
    response = await link(auth, browser, t)
    assert response.status_code == 401
    assert (await auth.audit("auth.login_failed", t.id))[-1]["error_code"] == "mfa_not_enforced"
    assert auth.idp.revoked, "the tokens Authentik issued are revoked"
    assert (t.email, True) in auth.idp.mfa_sync
    assert await auth.audit("auth.login", t.id) == []
    # The next link asks for the second factor.
    assert (await link(auth, auth.browser(), t)).json()["stage"] == "validate"


async def test_no_second_factor_when_the_tenant_does_not_require_it(auth: Auth) -> None:  # noqa: F811
    t = await admin(auth, in_group=False)
    await auth.admin.execute(
        "UPDATE tenant_login_policy SET admin_mfa_required = false WHERE tenant_id = $1", t.id
    )
    assert (await link(auth, auth.browser(), t)).status_code == 204


async def test_a_user_is_never_asked(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(role="user")
    assert (await link(auth, auth.browser(), t)).status_code == 204


async def test_codes_and_setup_uri_stay_out_of_the_logs(
    auth: Auth,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    t = await admin(auth, enrolled=False)
    browser = auth.browser()
    await link(auth, browser, t)
    await code(browser, "999999")
    await code(browser)
    out = capsys.readouterr().out
    for secret in (SETUP_URI, "SYNTHETICSECRET", TOTP_CODE, "999999", t.email):
        assert secret not in out


# --- the admin group follows roles and the policy ---------------------------------------


async def test_operator_switching_the_requirement_moves_the_tenants_admins(
    console: Console,  # noqa: F811
) -> None:
    op = await console.operator()
    a = await console.auth.tenant(role="tenant_admin")
    user = f"member-{uuid.uuid4().hex[:6]}@client.example"
    await console.auth.admin.execute(
        "INSERT INTO users (tenant_id, email, display_name, role) VALUES ($1, $2, 'M', 'user')",
        a.id,
        user,
    )
    path = f"/api/v1/operator/tenants/{a.id}/login-policy"
    body = {"sign_in_links_enabled": True, "jit_provisioning_enabled": False}
    assert (await op.put(path, json={**body, "admin_mfa_required": False})).status_code == 200
    assert console.auth.idp.mfa_sync == [(a.email, False)]
    assert (await op.put(path, json={**body, "admin_mfa_required": True})).status_code == 200
    assert console.auth.idp.mfa_sync == [(a.email, False), (a.email, True)]
    # Authentik refusing leaves the policy as it was.
    console.auth.idp.fail_mfa_sync = True
    response = await op.put(path, json={**body, "admin_mfa_required": False})
    assert (response.status_code, response.json()) == (502, {"detail": "mfa_not_updated"})
    required = await console.auth.admin.fetchval(
        "SELECT admin_mfa_required FROM tenant_login_policy WHERE tenant_id = $1", a.id
    )
    assert required is True


async def test_role_changes_move_the_user_in_and_out_of_the_group(
    console: Console,  # noqa: F811
) -> None:
    a = await console.auth.tenant(role="tenant_admin")
    browser = console.as_user(a.email, a.id)
    invited = await browser.post(
        "/api/v1/admin/users",
        json={"email": "second-admin@client.example", "display_name": "S", "role": "tenant_admin"},
    )
    assert invited.status_code == 201, invited.text
    assert console.auth.idp.mfa_sync == [("second-admin@client.example", True)]
    user_id = invited.json()["id"]
    demoted = await browser.patch(f"/api/v1/admin/users/{user_id}", json={"role": "user"})
    assert demoted.status_code == 200
    assert console.auth.idp.mfa_sync[-1] == ("second-admin@client.example", False)
    console.auth.idp.fail_mfa_sync = True
    promoted = await browser.patch(f"/api/v1/admin/users/{user_id}", json={"role": "tenant_admin"})
    assert promoted.status_code == 502
    role = await console.auth.admin.fetchval("SELECT role FROM users WHERE id = $1", user_id)
    assert role == "user"
