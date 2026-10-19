"""P1a-02 components: token validator, Authentik adapter, the auth lookup role, config."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import asyncpg
import httpx
import pytest
from pydantic import SecretStr

from app.auth.authentik import AuthentikProvider
from app.auth.provider import LinkRefused, ProviderError
from app.auth.tokens import InvalidToken, JwksTokenValidator
from app.core.config import ConfigError, load_settings
from tests.fake_idp import CLIENT_ID, ISSUER, jwks_of, new_key, sign, validator_for
from tests.test_auth import AUTHENTIK
from tests.test_config import ENV, VALID_TOML, write_config

# --- token validator -------------------------------------------------------------------


async def test_validator_accepts_a_good_token_and_caches_the_jwks() -> None:
    key = new_key()
    calls: list[str] = []
    validator = validator_for(key, calls)
    tenant = uuid.uuid4()
    for _ in range(3):
        identity = await validator.validate(sign(key, email="A@Client.Example", tenant_id=tenant))
        assert (identity.email, identity.tenant_id) == ("a@client.example", tenant)
    assert calls == [ISSUER + "jwks/"]


async def test_validator_picks_up_a_rotated_key() -> None:
    old, new = new_key(), new_key()
    serving = {"jwks": jwks_of(old, "k1")}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=serving["jwks"])

    validator = JwksTokenValidator(
        issuer=ISSUER,
        audience=CLIENT_ID,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        cache_seconds=0,
    )
    await validator.validate(sign(old, email="a@x.example", tenant_id=uuid.uuid4(), kid="k1"))
    serving["jwks"] = jwks_of(new, "k2")
    await validator.validate(sign(new, email="a@x.example", tenant_id=uuid.uuid4(), kid="k2"))


@pytest.mark.parametrize(
    ("token", "code"),
    [("", "malformed"), ("not-a-jwt", "malformed"), ("x" * 9000, "malformed")],
)
async def test_validator_refuses_garbage(token: str, code: str) -> None:
    with pytest.raises(InvalidToken) as excinfo:
        await validator_for(new_key()).validate(token)
    assert excinfo.value.error_code == code


async def test_unreachable_jwks_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    validator = JwksTokenValidator(
        issuer=ISSUER,
        audience=CLIENT_ID,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InvalidToken) as excinfo:
        await validator.validate(sign(new_key(), email="a@x.example", tenant_id=uuid.uuid4()))
    assert excinfo.value.error_code == "jwks_unavailable"


# --- Authentik adapter, against a simulated Authentik ----------------------------------


class SimulatedAuthentik:
    """Answers like authentik 2026.8's flow executor and OIDC endpoints (desk-checked)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_valid = True
        self.users: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        url = request.url
        assert url.host == "authentik-server" and url.port == 9000
        path, query = url.path, parse_qs(url.query.decode())
        body = (
            json.loads(request.content)
            if request.headers.get("content-type", "").startswith("application/json")
            else None
        )
        flow = "/api/v3/flows/executor/ask-spore-sign-in-link/"
        if path == flow and request.method == "GET":
            inner = parse_qs(query.get("query", [""])[0])
            if "flow_token" in inner:
                if not self.token_valid:
                    return httpx.Response(200, json={"component": "ak-stage-access-denied"})
                return httpx.Response(200, json={"component": "ak-stage-consent", "token": "c1"})
            return httpx.Response(200, json={"component": "ak-stage-identification"})
        if path == flow and request.method == "POST":
            assert body is not None
            if body["component"] == "ak-stage-identification":
                return httpx.Response(200, json={"component": "ak-stage-email"})
            assert body == {"component": "ak-stage-consent", "token": "c1"}
            return httpx.Response(200, json={"component": "xak-flow-redirect", "to": "/"})
        if path == "/application/o/authorize/":
            assert query["client_id"] == [CLIENT_ID] and query["code_challenge_method"] == ["S256"]
            self.state = query["state"][0]
            return httpx.Response(
                302,
                headers={
                    "location": "/if/flow/default-provider-authorization-implicit-consent/"
                    "?client_id=ask-spore"
                },
            )
        if path == "/api/v3/flows/executor/default-provider-authorization-implicit-consent/":
            to = f"{AUTHENTIK.redirect_uri}?code=code-1&state={self.state}"
            return httpx.Response(200, json={"component": "xak-flow-redirect", "to": to})
        if path == "/application/o/token/":
            form = parse_qs(request.content.decode())
            assert form["code"] == ["code-1"] and form["client_secret"] == ["client-secret"]
            assert form["code_verifier"]
            return httpx.Response(200, json={"access_token": "issued-access-token"})
        if path == "/api/v3/core/users/" and request.method == "GET":
            return httpx.Response(200, json={"results": self.users})
        if path == "/api/v3/core/users/" and request.method == "POST":
            assert request.headers["authorization"] == "Bearer api-token"
            self.users.append({"pk": 7, **(body or {})})
            return httpx.Response(201, json={"pk": 7})
        if path == "/api/v3/core/users/7/" and request.method == "PATCH":
            return httpx.Response(200, json={"pk": 7})
        return httpx.Response(404)


def adapter(sim: SimulatedAuthentik) -> AuthentikProvider:
    return AuthentikProvider(
        AUTHENTIK,
        client_secret=SecretStr("client-secret"),
        api_token=SecretStr("api-token"),
        transport=httpx.MockTransport(sim),
    )


async def test_adapter_sends_a_link_through_the_flow() -> None:
    sim = SimulatedAuthentik()
    await adapter(sim).send_sign_in_link("a@client.example")
    posted = json.loads(sim.requests[-1].content)
    assert posted == {"component": "ak-stage-identification", "uid_field": "a@client.example"}


async def test_adapter_redeems_consent_then_code_exchange() -> None:
    sim = SimulatedAuthentik()
    issued = await adapter(sim).redeem_sign_in_link("flow-token-1")
    assert issued.access_token == "issued-access-token"
    first = sim.requests[0]
    assert parse_qs(first.url.params["query"]) == {"flow_token": ["flow-token-1"]}
    # No browser session is involved: every call went to Authentik on the Compose network.
    assert {r.url.host for r in sim.requests} == {"authentik-server"}


async def test_adapter_reports_a_refused_token() -> None:
    sim = SimulatedAuthentik()
    sim.token_valid = False
    with pytest.raises(LinkRefused):
        await adapter(sim).redeem_sign_in_link("spent")
    assert not any(r.url.path == "/application/o/token/" for r in sim.requests)


async def test_adapter_provisions_with_the_tenant_attribute() -> None:
    sim = SimulatedAuthentik()
    tenant = uuid.uuid4()
    provider = adapter(sim)
    await provider.provision_user(email="a@client.example", display_name="A", tenant_id=tenant)
    created = json.loads(sim.requests[-1].content)
    assert created["attributes"] == {"ask_spore_tenant": str(tenant)}
    await provider.provision_user(email="a@client.example", display_name="A", tenant_id=tenant)
    assert sim.requests[-1].method == "PATCH"


async def test_adapter_maps_transport_failures() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    provider = AuthentikProvider(
        AUTHENTIK,
        client_secret=SecretStr("s"),
        api_token=SecretStr("t"),
        transport=httpx.MockTransport(down),
    )
    with pytest.raises(ProviderError):
        await provider.send_sign_in_link("a@client.example")


# --- the auth lookup role ----------------------------------------------------------------


@pytest.fixture
async def auth_role(app_conn: asyncpg.Connection) -> asyncpg.Connection:
    await app_conn.execute("SET ROLE askspore_auth")
    return app_conn


@pytest.mark.parametrize(
    "query",
    [
        "SELECT display_name FROM users",
        "SELECT name FROM tenants",
        "SELECT display_name FROM tenants",
        "SELECT enabled_models FROM tenant_entitlements",
        "SELECT * FROM conversations",
        "SELECT * FROM messages",
        "SELECT * FROM audit_events",
    ],
)
async def test_auth_role_reads_only_what_the_lookup_needs(
    auth_role: asyncpg.Connection, query: str
) -> None:
    with pytest.raises((asyncpg.InsufficientPrivilegeError, asyncpg.UndefinedColumnError)):
        await auth_role.fetch(query)


async def test_auth_role_cannot_change_users(auth_role: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await auth_role.execute("UPDATE users SET status = 'active'")


async def test_app_role_does_not_inherit_the_auth_role(admin_conn: asyncpg.Connection) -> None:
    grant = await admin_conn.fetchrow(
        "SELECT inherit_option, set_option FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
        "WHERE r.rolname = 'askspore_auth' AND u.rolname = 'askspore_app'"
    )
    assert grant is not None and grant["set_option"] and not grant["inherit_option"]
    role = await admin_conn.fetchrow(
        "SELECT rolcanlogin, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'askspore_auth'"
    )
    assert role is not None and not any(role.values())


# --- configuration -----------------------------------------------------------------------

OIDC_TOML = (
    VALID_TOML.replace(
        'eu_hosts = ["api.mistral.ai", "ragflow"]',
        'eu_hosts = ["api.mistral.ai", "ragflow", "authentik-server"]',
    )
    + """
[auth]
mode = "oidc"

[auth.authentik]
base_url = "http://authentik-server:9000"
issuer = "http://authentik-server:9000/application/o/ask-spore/"
client_id = "ask-spore"
redirect_uri = "https://ask-spore.invalid/auth/callback"
sign_in_flow = "ask-spore-sign-in-link"
timeout_seconds = 10
"""
)
OIDC_ENV = {
    **{k: v for k, v in ENV.items() if k != "PHASE0_BEARER_TOKEN"},
    "AUTHENTIK_CLIENT_SECRET": "client-secret",
    "AUTHENTIK_API_TOKEN": "api-token",
}


def test_oidc_mode_needs_authentik_secrets_not_the_phase0_token(tmp_path: Path) -> None:
    settings = load_settings(environ=OIDC_ENV, config_dir=write_config(tmp_path, OIDC_TOML))
    assert settings.models.auth.mode == "oidc"
    assert settings.secrets.phase0_bearer_token is None
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=ENV, config_dir=write_config(tmp_path, OIDC_TOML))
    assert "AUTHENTIK_CLIENT_SECRET, AUTHENTIK_API_TOKEN" in str(excinfo.value)


def test_oidc_mode_ignores_a_leftover_phase0_token(tmp_path: Path) -> None:
    env = {**OIDC_ENV, "PHASE0_BEARER_TOKEN": ENV["PHASE0_BEARER_TOKEN"]}
    settings = load_settings(environ=env, config_dir=write_config(tmp_path, OIDC_TOML))
    assert settings.secrets.phase0_bearer_token is None


def test_phase0_mode_still_needs_the_bearer_token(tmp_path: Path) -> None:
    env = {k: v for k, v in ENV.items() if k != "PHASE0_BEARER_TOKEN"}
    with pytest.raises(ConfigError, match="PHASE0_BEARER_TOKEN"):
        load_settings(environ=env, config_dir=write_config(tmp_path))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ('"authentik-server"]', "authentik.base_url host"),
        ("link_ttl_seconds", "link_ttl_seconds"),
        ("no_section", "no [auth.authentik] section"),
    ],
)
def test_oidc_config_is_checked(tmp_path: Path, change: str, problem: str) -> None:
    text = OIDC_TOML
    if change == '"authentik-server"]':
        text = text.replace(', "authentik-server"]', "]")
    elif change == "link_ttl_seconds":
        text = text.replace('mode = "oidc"', 'mode = "oidc"\nlink_ttl_seconds = 3600')
    else:
        text = text[: text.index("[auth.authentik]")]
    with pytest.raises(ConfigError) as excinfo:
        load_settings(environ=OIDC_ENV, config_dir=write_config(tmp_path, text))
    assert problem in str(excinfo.value)
