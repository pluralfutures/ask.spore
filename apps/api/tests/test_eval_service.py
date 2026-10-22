"""P1b-15 a: the eval harness's path under ``[auth] mode = "oidc"``.

The API in oidc mode, with Authentik faked (``tests.fake_idp``), the model and retrieval
faked, and PostgreSQL real: the harness's signed service credential asks a question as
the eval service identity; everything else about it is refused.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.eval_service import (
    EvalServiceValidator,
    generate_key_pair,
    is_eval_credential,
    sign_credential,
)
from app.chat.orchestrator import Orchestrator
from app.core.config import DEFAULT_CONFIG_DIR, EvalServiceConfig, Settings, load_settings
from app.core.db import create_engine, session_factory
from app.main import create_app
from app.operator.grants import create_eval_identity, grant_operator
from tests.chat_fixtures import World, chunks_for
from tests.conftest import MigratedDatabase
from tests.fake_idp import FakeSignInLinks, validator_for
from tests.fakes import FakeRedis, FakeRetriever, delta, router, sse
from tests.fakes import OpenAIRecorder as Recorder
from tests.test_api import parse_sse
from tests.test_auth import oidc_settings
from tests.test_config import ENV, problems_for
from tests.test_tenancy import make_tenant

pytestmark = pytest.mark.usefixtures("database")

EMAIL = "eval-service@example.org"
PRIVATE, PUBLIC = generate_key_pair()


class Eval:
    def __init__(self, app: Any, recorder: Recorder) -> None:
        self.app = app
        self.recorder = recorder
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def ask(self, token: str, question: str = "What grew?") -> list[tuple[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"}
        created = await self.http.post("/api/v1/conversations", headers=headers, json={})
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        self.recorder.add(sse(delta("Capacity grew [1].")))
        response = await self.http.post(
            f"/api/v1/conversations/{cid}/messages", headers=headers, json={"question": question}
        )
        assert response.status_code == 200
        assert (
            await self.http.delete(f"/api/v1/conversations/{cid}", headers=headers)
        ).status_code == 204
        return parse_sse(response.text)


@pytest.fixture
async def owner(database: MigratedDatabase) -> AsyncIterator[Any]:
    engine = create_engine(database.sqlalchemy_url)
    yield session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def harness(
    settings: Settings, engine: AsyncEngine, world: World, redis: FakeRedis, owner: Any
) -> AsyncIterator[Eval]:
    assert await create_eval_identity(owner, email=EMAIL) in ("created", "exists")
    idp = FakeSignInLinks()
    app = create_app()
    app.state.settings = oidc_settings(settings)
    app.state.db_factory = session_factory(engine)
    app.state.sign_in_provider = idp
    app.state.token_validator = validator_for(idp.key)
    app.state.eval_service = EvalServiceValidator(PUBLIC, EMAIL, 900)
    recorder = Recorder()
    app.state.orchestrator = Orchestrator(
        settings=settings,
        db_factory=app.state.db_factory,
        retriever=FakeRetriever(chunks_for(world)),
        llm=router(settings, recorder),
    )
    h = Eval(app, recorder)
    yield h
    await h.http.aclose()
    # The internal tenant keeps exactly its seeded users for other tests.
    await world.admin.execute("DELETE FROM users WHERE email = $1", EMAIL)


async def test_the_eval_harness_asks_through_the_oidc_api_with_its_credential(
    harness: Eval, admin_conn: asyncpg.Connection
) -> None:
    token = sign_credential(PRIVATE, EMAIL)
    assert is_eval_credential(token)
    events = await harness.ask(token)
    assert [name for name, _ in events][-1] == "done"
    me = await harness.http.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == EMAIL and me.json()["role"] == "user"
    # It is a plain user: no operator console, no tenant admin routes.
    for path in ("/api/v1/operator/tenants", "/api/v1/admin/users"):
        refused = await harness.http.get(path, headers={"Authorization": f"Bearer {token}"})
        assert refused.status_code == 403, path


def _claims_token(**overrides: Any) -> str:
    import jwt
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    now = int(time.time())
    claims = {
        "iss": "ask-spore-eval-harness",
        "aud": "ask-spore-eval",
        "sub": EMAIL,
        "iat": now,
        "exp": now + 300,
    } | overrides
    key = load_pem_private_key(PRIVATE.encode(), password=None)
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "ask-spore-eval"})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: sign_credential(generate_key_pair()[0], EMAIL), id="other-key"),
        pytest.param(lambda: sign_credential(PRIVATE, "analyst@example.org"), id="other-user"),
        pytest.param(lambda: sign_credential(PRIVATE, EMAIL, lifetime_seconds=7200), id="long"),
        pytest.param(lambda: sign_credential(PRIVATE, EMAIL, now=time.time() - 3600), id="expired"),
        pytest.param(lambda: _claims_token(aud="ask-spore"), id="audience"),
        pytest.param(lambda: _claims_token(iss="someone"), id="issuer"),
        pytest.param(
            lambda: _claims_token(iat=int(time.time()) + 600, exp=int(time.time()) + 900),
            id="future",
        ),
    ],
)
async def test_any_other_credential_is_refused(harness: Eval, token: Any) -> None:
    response = await harness.http.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token()}"}
    )
    assert response.status_code == 401


async def test_without_the_section_no_eval_credential_is_accepted(harness: Eval) -> None:
    harness.app.state.eval_service = None
    token = sign_credential(PRIVATE, EMAIL)
    response = await harness.http.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401  # checked against Authentik's keys, which refuse it


async def test_the_credential_never_reaches_another_tenant(
    harness: Eval, admin_conn: asyncpg.Connection
) -> None:
    # A client tenant's user with the same address as the service identity: the
    # credential resolves in the internal tenant only.
    client = await make_tenant(admin_conn, domain="example.org")
    await admin_conn.execute("UPDATE users SET email = $1 WHERE id = $2", EMAIL, client.user_id)
    internal = await admin_conn.fetchval("SELECT display_name FROM tenants WHERE slug = 'internal'")
    token = sign_credential(PRIVATE, EMAIL)
    me = await harness.http.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["tenant_display_name"] == internal != "Synthetic Client"


async def test_the_identity_is_never_an_operator(
    owner: Any, admin_conn: asyncpg.Connection
) -> None:
    email = f"op-{uuid.uuid4().hex[:6]}@example.org"
    await grant_operator(owner, email=email, display_name="Synthetic Op", provider=None)
    assert await create_eval_identity(owner, email=email) == "has_roles"
    await admin_conn.execute("DELETE FROM users WHERE email = $1", email)


def test_the_repository_config_accepts_no_eval_credential() -> None:
    # Production config: never a service credential (nor, in oidc mode, a bearer token).
    settings = load_settings(environ=ENV, config_dir=DEFAULT_CONFIG_DIR)
    assert settings.models.auth.mode == "oidc"
    assert settings.models.auth.eval_service is None


def test_the_section_needs_oidc_and_an_ed25519_key(tmp_path: Path) -> None:
    from tests.test_config import VALID_TOML

    section = f'\n[auth.eval_service]\nemail = "{EMAIL}"\npublic_key = """{PUBLIC}"""\n'
    assert "auth.eval_service needs [auth] mode = 'oidc'" in problems_for(
        tmp_path, VALID_TOML + section
    )
    bad = section.replace(PUBLIC.splitlines()[1], "AAAA")
    assert any("eval_service" in p for p in problems_for(tmp_path, VALID_TOML + bad))
    assert EvalServiceConfig(email=EMAIL, public_key=PUBLIC).max_lifetime_seconds == 900
