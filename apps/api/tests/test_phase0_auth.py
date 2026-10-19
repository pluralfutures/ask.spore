"""P0-06: Phase 0 auth (shared bearer token + X-User-Email) and tenant session scoping."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.deps import db_session
from app.core.config import AuthConfig, Secrets
from app.core.db import session_factory
from app.core.phase0_auth import token_matches
from app.main import create_app
from app.tenancy.models import INTERNAL_TENANT_ID
from tests.conftest import MigratedDatabase

TOKEN = "phase0-test-token-0123456789abcdef"
ANALYST = "analyst@example.org"
UNAUTHORIZED = {"detail": "unauthorized"}


class _Models:
    auth = AuthConfig()  # mode "phase0"


class _Settings:
    def __init__(self) -> None:
        self.models = _Models()
        self.secrets = Secrets(
            mistral_api_key=SecretStr("unused"),
            ragflow_api_key=SecretStr("unused"),
            database_url=SecretStr("unused"),
            redis_url=SecretStr("unused"),
            phase0_bearer_token=SecretStr(TOKEN),
        )


def _app_with_probe(database: MigratedDatabase) -> tuple[FastAPI, Any]:
    app = create_app()
    # Connect as the application role so RLS applies, as in production.
    engine = create_async_engine(
        database.sqlalchemy_url, connect_args={"server_settings": {"role": "askspore_app"}}
    )
    app.state.settings = _Settings()
    app.state.db_factory = session_factory(engine)

    @app.get("/api/v1/_probe")
    async def probe(
        request: Request, session: AsyncSession = Depends(db_session)
    ) -> dict[str, Any]:
        return {
            "tenant_id": str(request.state.tenant_id),
            "user_id": str(request.state.user_id),
            "app_tenant_id": await session.scalar(
                text("SELECT current_setting('app.tenant_id', true)")
            ),
            "db_role": await session.scalar(text("SELECT current_user")),
            "visible_users": await session.scalar(text("SELECT count(*) FROM users")),
        }

    return app, engine


@pytest.fixture
async def client(database: MigratedDatabase) -> AsyncIterator[httpx.AsyncClient]:
    app, engine = _app_with_probe(database)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await engine.dispose()


def _headers(token: str | None = TOKEN, email: str | None = ANALYST) -> dict[str, str]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if email is not None:
        headers["X-User-Email"] = email
    return headers


async def test_valid_token_and_seeded_user_sets_tenant_and_session_variable(
    client: httpx.AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    response = await client.get("/api/v1/_probe", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    analyst_id = await admin_conn.fetchval("SELECT id FROM users WHERE email = $1", ANALYST)
    assert body["tenant_id"] == str(INTERNAL_TENANT_ID)
    assert body["user_id"] == str(analyst_id)
    assert body["app_tenant_id"] == str(INTERNAL_TENANT_ID)
    assert body["db_role"] == "askspore_app"
    assert body["visible_users"] == 2  # only the internal tenant's seeded users


async def test_email_match_is_case_insensitive(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/_probe", headers=_headers(email="Analyst@Example.ORG"))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no headers"),
        pytest.param(_headers(token=None), id="missing token"),
        pytest.param(_headers(token="wrong-token-0123456789abcdef0123"), id="wrong token"),
        pytest.param(_headers(token=TOKEN[:-1]), id="token prefix"),
        pytest.param(_headers(token=""), id="empty token"),
        pytest.param({"Authorization": f"Basic {TOKEN}", "X-User-Email": ANALYST}, id="basic"),
        pytest.param({"Authorization": TOKEN, "X-User-Email": ANALYST}, id="no scheme"),
        pytest.param(_headers(email=None), id="missing email"),
        pytest.param(_headers(email="nobody@example.org"), id="unknown email"),
        pytest.param(_headers(email="a" * 400 + "@example.org"), id="oversized email"),
    ],
)
async def test_rejected_with_identical_401(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/_probe", headers=headers)
    assert response.status_code == 401
    assert response.json() == UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


async def test_user_of_another_tenant_is_rejected(
    client: httpx.AsyncClient, admin_conn: asyncpg.Connection
) -> None:
    other = uuid.uuid4()
    email = f"outsider-{other.hex[:8]}@example.org"
    await admin_conn.execute(
        "INSERT INTO tenants (id, slug, display_name) VALUES ($1, $2, 'Other')",
        other,
        f"o-{other.hex}",
    )
    await admin_conn.execute(
        "INSERT INTO users (tenant_id, email, display_name) VALUES ($1, $2, 'Outsider')",
        other,
        email,
    )
    response = await client.get("/api/v1/_probe", headers=_headers(email=email))
    assert response.status_code == 401


async def test_tenant_cannot_be_chosen_by_the_client(client: httpx.AsyncClient) -> None:
    other = str(uuid.uuid4())
    headers = {**_headers(), "X-Tenant-Id": other}
    response = await client.get(f"/api/v1/_probe?tenant_id={other}", headers=headers)
    assert response.json()["tenant_id"] == str(INTERNAL_TENANT_ID)


async def test_openapi_docs_are_behind_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/openapi.json")).status_code == 401
    assert (await client.get("/docs")).status_code == 401


async def test_liveness_probe_needs_no_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200


async def test_rejection_log_has_no_token_or_email(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_email = "secret-person@example.org"
    await client.get("/api/v1/_probe", headers=_headers(token="x" * 40, email=secret_email))
    await client.get("/api/v1/_probe", headers=_headers(email=secret_email))
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    assert [line["error_code"] for line in lines] == ["bad_token", "unknown_user"]
    for line in lines:
        assert secret_email not in json.dumps(line)
        assert "x" * 40 not in json.dumps(line)
        assert TOKEN not in json.dumps(line)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"Bearer {TOKEN}", True),
        (f"bearer {TOKEN}", True),
        (f"Bearer {TOKEN}x", False),
        ("Bearer ", False),
        (None, False),
        (TOKEN, False),
    ],
)
def test_token_matches(header: str | None, expected: bool) -> None:
    assert token_matches(header, TOKEN) is expected
