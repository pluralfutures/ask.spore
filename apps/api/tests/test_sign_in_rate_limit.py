"""P1b-08: per-client-IP limits on the public sign-in routes, against PostgreSQL.

The test client's address is the socket peer, or the last ``X-Forwarded-For`` entry
(Caddy's) when the header is present.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.auth.ratelimit import MAX_TRACKED, IpRateLimiter
from tests.test_auth import BINDING, Auth, auth  # noqa: F401 - fixture
from tests.test_login_policy import unique_domain

pytestmark = pytest.mark.usefixtures("database")

LIMIT = 10  # [auth] ip_requests_per_window, default


async def test_link_requests_over_the_limit_get_429_and_send_nothing(auth: Auth) -> None:  # noqa: F811
    users = [await auth.tenant(domain=unique_domain()) for _ in range(LIMIT + 1)]
    browser = auth.browser()
    for t in users[:LIMIT]:
        assert (await auth.request_link(browser, t.email)).status_code == 202
    sent = list(auth.idp.outbox)
    rows = await auth.admin.fetchval("SELECT count(*) FROM sign_in_links")

    response = await auth.request_link(browser, users[LIMIT].email)
    assert response.status_code == 429
    assert response.json() == {"detail": "rate_limited"}
    assert int(response.headers["retry-after"]) > 0
    assert "set-cookie" not in response.headers  # no binding cookie either
    assert auth.idp.outbox == sent
    assert await auth.admin.fetchval("SELECT count(*) FROM sign_in_links") == rows
    assert await auth.audit("auth.link_requested", users[LIMIT].id) == []


async def test_another_client_address_is_not_limited(auth: Auth) -> None:  # noqa: F811
    t = await auth.tenant(domain=unique_domain())
    browser = auth.browser()
    forwarded = {"X-Forwarded-For": "198.51.100.7"}
    for _ in range(LIMIT):
        await browser.post("/api/v1/auth/link", json={"email": t.email}, headers=forwarded)
    blocked = await browser.post("/api/v1/auth/link", json={"email": t.email}, headers=forwarded)
    assert blocked.status_code == 429
    # A spoofed first entry does not help: Caddy's own entry (the last) counts.
    spoofed = {"X-Forwarded-For": "203.0.113.9, 198.51.100.7"}
    response = await browser.post("/api/v1/auth/link", json={"email": t.email}, headers=spoofed)
    assert response.status_code == 429
    other = {"X-Forwarded-For": "198.51.100.8"}
    response = await browser.post("/api/v1/auth/link", json={"email": t.email}, headers=other)
    assert response.status_code == 202


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/discover", {"email": "x@client.example"}),
        ("/api/v1/auth/sso/start", {"email": "x@client.example"}),
    ],
)
async def test_discovery_and_sso_start_are_limited_too(
    auth: Auth,  # noqa: F811
    path: str,
    body: dict[str, Any],
) -> None:
    browser = auth.browser()
    for _ in range(LIMIT):
        assert (await browser.post(path, json=body)).status_code in (200, 409)
    assert (await browser.post(path, json=body)).status_code == 429
    # Each route counts on its own: links still go out.
    assert (await auth.request_link(browser, "x@client.example")).status_code == 202


async def test_the_limit_is_not_logged_with_the_address(
    auth: Auth,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    browser = auth.browser()
    headers = {"X-Forwarded-For": "192.0.2.44"}
    for _ in range(LIMIT + 1):
        await browser.post("/api/v1/auth/discover", json={"email": "x@a.example"}, headers=headers)
    out = capsys.readouterr().out
    assert '"event":"auth.ip_rate_limited"' in out
    assert "192.0.2.44" not in out


def test_window_slides() -> None:
    now = [0.0]
    limiter = IpRateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.retry_after("a") == 61
    now[0] = 59.0
    assert not limiter.allow("a")
    now[0] = 60.5
    assert limiter.allow("a")
    assert limiter.allow("b")


def test_memory_is_bounded() -> None:
    limiter = IpRateLimiter(1, 60, clock=lambda: 0.0)
    for i in range(MAX_TRACKED + 10):
        limiter.allow(f"10.0.{i // 256}.{i % 256}")
    assert len(limiter._hits) == MAX_TRACKED
