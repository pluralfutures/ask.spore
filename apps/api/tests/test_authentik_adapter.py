"""P1b-07 and P1b-08: the Authentik adapter against a simulated Authentik.

Answers like authentik 2026.8 (desk-checked against the ``version-2026.8`` source, not a
live instance): the OAuth and SAML source views, the flow executor, the OAuth2 token and
revocation endpoints, and the core, source, property-mapping and crypto APIs. Checks
what the adapter sends: the public host on the relayed source calls, the pinned Entra
endpoints, the generated mapping, the client secret to Authentik only, the code to the
stage the flow stopped at.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr

from app.auth.authentik import AuthentikProvider
from app.auth.provider import IssuedTokens, LinkRefused, MfaRequired, ProviderError
from app.auth.sources import entra_config, parse_idp_metadata, saml_config, spec_for
from tests.test_auth import AUTHENTIK
from tests.test_saml_metadata import metadata_xml

PUBLIC_HOST = "askspore.test.example"
TENANT = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
LINK_FLOW = "/api/v3/flows/executor/ask-spore-sign-in-link/"
SOURCE_FLOW = "/api/v3/flows/executor/ask-spore-source-authentication/"
CONSENT_FLOW = "/api/v3/flows/executor/default-provider-authorization-implicit-consent/"


class Simulated:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.objects: dict[str, list[dict[str, Any]]] = {}
        self.mfa_stage = "ak-stage-authenticator-validate"
        self.mfa_needed = False
        self.refresh_ok = True
        self.at_mfa = False  # the link flow's plan stands at the second factor

    def _list(self, path: str, query: dict[str, list[str]]) -> httpx.Response:
        found = [
            o
            for o in self.objects.get(path, [])
            if all(str(o.get(k)) == v[0] for k, v in query.items())
        ]
        return httpx.Response(200, json={"results": found})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        path, query = request.url.path, parse_qs(request.url.query.decode())
        body: Any = None
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content)
        form = parse_qs(request.content.decode()) if not body and request.content else {}

        if path.startswith("/source/oauth/login/"):
            return httpx.Response(
                302,
                headers={
                    "location": "https://login.microsoftonline.com/x/authorize?state=s1",
                    "set-cookie": "authentik_session=pending-1; Path=/; HttpOnly",
                },
            )
        if path.startswith("/source/oauth/callback/") or path.startswith("/source/saml/"):
            if request.headers.get("cookie") != "authentik_session=pending-1":
                return httpx.Response(400, text="bad state")
            if "denied" in str(query) + str(form):
                return httpx.Response(400, text="Request to authenticate has been denied")
            return httpx.Response(
                302, headers={"location": "/if/flow/ask-spore-source-authentication/?next=%2F"}
            )
        if path == SOURCE_FLOW:
            return httpx.Response(200, json={"component": "xak-flow-redirect", "to": "/"})
        if path == LINK_FLOW and request.method == "GET":
            # With a plan in the session, the executor answers with its current stage.
            if self.at_mfa:
                return httpx.Response(200, json={"component": self.mfa_stage, "config_url": "u"})
            return httpx.Response(200, json={"component": "ak-stage-consent", "token": "c1"})
        if path == LINK_FLOW and request.method == "POST":
            if body["component"] == "ak-stage-consent":
                if self.mfa_needed:
                    self.at_mfa = True
                    return httpx.Response(
                        200, json={"component": self.mfa_stage, "config_url": "otpauth://x"}
                    )
                return httpx.Response(200, json={"component": "xak-flow-redirect", "to": "/"})
            assert body["component"] == self.mfa_stage
            if body["code"] != "123456":
                return httpx.Response(
                    200,
                    json={"component": self.mfa_stage, "response_errors": {"code": ["Invalid"]}},
                )
            self.at_mfa = False
            return httpx.Response(200, json={"component": "xak-flow-redirect", "to": "/"})
        if path == "/application/o/authorize/":
            self.state = query["state"][0]
            return httpx.Response(
                302,
                headers={"location": "/if/flow/default-provider-authorization-implicit-consent/"},
            )
        if path == CONSENT_FLOW:
            to = f"{AUTHENTIK.redirect_uri}?code=code-1&state={self.state}"
            return httpx.Response(200, json={"component": "xak-flow-redirect", "to": to})
        if path == "/application/o/token/":
            if form["grant_type"] == ["refresh_token"]:
                if not self.refresh_ok:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "a2", "refresh_token": "r2"})
            return httpx.Response(200, json={"access_token": "a1", "refresh_token": "r1"})
        if path == "/application/o/revoke/":
            return httpx.Response(200)
        if path.endswith("/add_user/") or path.endswith("/remove_user/"):
            return httpx.Response(204)
        if path.endswith("/generate/"):
            created = {"pk": "kp-generated", "name": body["common_name"]}
            self.objects.setdefault("/api/v3/crypto/certificatekeypairs/", []).append(created)
            return httpx.Response(200, json=created)
        if request.method == "GET":
            return self._list(path, query)
        if request.method == "POST":
            created = {"pk": f"pk-{len(self.requests)}", **body}
            self.objects.setdefault(path, []).append(created)
            return httpx.Response(201, json=created)
        if request.method == "PATCH":
            return httpx.Response(200, json={"pk": path.rstrip("/").split("/")[-1], **body})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    def sent(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]


def provider(sim: Simulated) -> AuthentikProvider:
    return AuthentikProvider(
        AUTHENTIK,
        client_secret=SecretStr("client-secret"),
        api_token=SecretStr("api-token"),
        transport=httpx.MockTransport(sim),
    )


def seed_flows(sim: Simulated) -> None:
    sim.objects["/api/v3/flows/instances/"] = [
        {"pk": "flow-auth", "slug": "ask-spore-source-authentication"},
        {"pk": "flow-enrol", "slug": "ask-spore-source-enrollment"},
        {"pk": "flow-pre", "slug": "ask-spore-source-pre-authentication"},
    ]


# --- SSO relay (P1b-07) -----------------------------------------------------------------


async def test_start_and_finish_sso_relay_with_the_public_host() -> None:
    sim = Simulated()
    p = provider(sim)
    redirect = await p.start_sso("entra", "sso-cc")
    assert redirect.url.startswith("https://login.microsoftonline.com/")
    (start,) = sim.sent("GET", "/source/oauth/login/sso-cc/")
    assert start.headers["host"] == PUBLIC_HOST
    assert start.headers["x-forwarded-proto"] == "https"

    issued = await p.finish_sso("entra", "sso-cc", {"code": "c", "state": "s1"}, redirect.resume)
    assert issued == IssuedTokens(access_token="a1", refresh_token="r1")
    (callback,) = sim.sent("GET", "/source/oauth/callback/sso-cc/")
    assert callback.headers["host"] == PUBLIC_HOST
    assert parse_qs(callback.url.query.decode()) == {"code": ["c"], "state": ["s1"]}
    # Every call went to Authentik on the Compose network; none to a browser-facing host.
    assert {r.url.host for r in sim.requests} == {"authentik-server"}


async def test_saml_answer_is_posted_to_the_acs() -> None:
    sim = Simulated()
    p = provider(sim)
    redirect = await p.start_sso("entra", "sso-cc")  # the session cookie, as for SAML
    await p.finish_sso("saml", "sso-cc", {"SAMLResponse": "x", "RelayState": "r"}, redirect.resume)
    (acs,) = sim.sent("POST", "/source/saml/sso-cc/acs/")
    assert parse_qs(acs.content.decode()) == {"SAMLResponse": ["x"], "RelayState": ["r"]}


async def test_a_refused_source_answer_is_a_refusal() -> None:
    sim = Simulated()
    p = provider(sim)
    redirect = await p.start_sso("entra", "sso-cc")
    with pytest.raises(LinkRefused):
        await p.finish_sso("entra", "sso-cc", {"error": "denied"}, redirect.resume)
    with pytest.raises(LinkRefused):
        await p.finish_sso("entra", "sso-cc", {"code": "c"}, "not-a-resume")
    assert sim.sent("POST", "/application/o/token/") == []


async def test_configure_entra_pins_the_tenant_and_sends_the_secret_to_authentik() -> None:
    sim = Simulated()
    seed_flows(sim)
    tid = uuid.uuid4()
    group = uuid.uuid4()
    spec = spec_for(
        tenant_id=TENANT,
        tenant_slug="cc",
        verified_domains=["client.example"],
        kind="entra",
        config=entra_config(tid, "app-id", [group]),
    )
    await provider(sim).configure_source(spec, SecretStr("s3cret"))
    (mapping,) = sim.sent("POST", "/api/v3/propertymappings/source/oauth/")
    expression = json.loads(mapping.content)["expression"]
    assert str(TENANT) in expression and '["client.example"]' in expression
    (created,) = sim.sent("POST", "/api/v3/sources/oauth/")
    source = json.loads(created.content)
    assert source["provider_type"] == "entraid"
    assert source["consumer_key"] == "app-id" and source["consumer_secret"] == "s3cret"
    for key in ("authorization_url", "access_token_url", "oidc_well_known_url"):
        assert f"https://login.microsoftonline.com/{tid}/" in source[key]
    assert source["additional_scopes"] == "https://graph.microsoft.com/GroupMember.Read.All"
    assert source["user_matching_mode"] == "identifier"
    assert (source["authentication_flow"], source["enrollment_flow"]) == ("flow-auth", "flow-enrol")
    assert all(r.headers["authorization"] == "Bearer api-token" for r in sim.requests)


async def test_configure_saml_imports_the_idp_certificate_and_generates_our_key() -> None:
    sim = Simulated()
    seed_flows(sim)
    metadata = parse_idp_metadata(metadata_xml())
    spec = spec_for(
        tenant_id=TENANT,
        tenant_slug="cc",
        verified_domains=["client.example"],
        kind="saml",
        config=saml_config(metadata),
        certificate_pem=metadata.certificate_pem,
    )
    await provider(sim).configure_source(spec, None)
    (imported,) = sim.sent("POST", "/api/v3/crypto/certificatekeypairs/")
    assert json.loads(imported.content)["key_data"] == ""  # public certificate only
    assert sim.sent("POST", "/api/v3/crypto/certificatekeypairs/generate/")
    (created,) = sim.sent("POST", "/api/v3/sources/saml/")
    source = json.loads(created.content)
    assert source["binding_type"] == "redirect" and source["allow_idp_initiated"] is False
    assert source["signing_kp"] == "kp-generated"
    assert source["pre_authentication_flow"] == "flow-pre"


async def test_a_new_oauth_source_needs_the_secret_and_missing_flows_fail() -> None:
    sim = Simulated()
    seed_flows(sim)
    spec = spec_for(
        tenant_id=TENANT,
        tenant_slug="cc",
        verified_domains=["client.example"],
        kind="entra",
        config=entra_config(uuid.uuid4(), "app-id", []),
    )
    with pytest.raises(ProviderError):
        await provider(sim).configure_source(spec, None)
    sim.objects["/api/v3/flows/instances/"] = []
    with pytest.raises(ProviderError):
        await provider(sim).configure_source(spec, SecretStr("s"))


# --- refresh, revocation and the second factor (P1b-08) ---------------------------------


async def test_refresh_uses_the_refresh_grant_and_maps_refusals() -> None:
    sim = Simulated()
    p = provider(sim)
    assert await p.refresh_session("r1") == IssuedTokens(access_token="a2", refresh_token="r2")
    (call,) = sim.sent("POST", "/application/o/token/")
    form = parse_qs(call.content.decode())
    assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["r1"]
    sim.refresh_ok = False
    with pytest.raises(LinkRefused):
        await p.refresh_session("r1")


async def test_revocation_names_the_token_kind() -> None:
    sim = Simulated()
    await provider(sim).revoke_token("r1", "refresh_token")
    (call,) = sim.sent("POST", "/application/o/revoke/")
    assert parse_qs(call.content.decode())["token_type_hint"] == ["refresh_token"]


@pytest.mark.parametrize(
    "stage", ["ak-stage-authenticator-validate", "ak-stage-authenticator-totp"]
)
async def test_the_second_factor_is_relayed_to_the_stage_that_asks(stage: str) -> None:
    sim = Simulated()
    sim.mfa_needed, sim.mfa_stage = True, stage
    p = provider(sim)
    pending = await p.redeem_sign_in_link("flow-token-1")
    assert isinstance(pending, MfaRequired)
    assert pending.stage == ("setup" if stage.endswith("totp") else "validate")
    assert (pending.setup_uri is not None) == stage.endswith("totp")
    wrong = await p.answer_mfa(pending.resume, "000000")
    assert isinstance(wrong, MfaRequired) and wrong.failed
    done = await p.answer_mfa(pending.resume, "123456")
    assert done == IssuedTokens(access_token="a1", refresh_token="r1", mfa=True)
    posted = [json.loads(r.content) for r in sim.sent("POST", LINK_FLOW)]
    assert posted[-1] == {"component": stage, "code": "123456"}


async def test_admin_group_membership() -> None:
    sim = Simulated()
    sim.objects["/api/v3/core/users/"] = [{"pk": 7, "username": "a@client.example"}]
    sim.objects["/api/v3/core/groups/"] = [{"pk": "g1", "name": "ask-spore-tenant-admins"}]
    p = provider(sim)
    await p.set_admin_mfa("a@client.example", True)
    await p.set_admin_mfa("a@client.example", False)
    assert [r.url.path for r in sim.requests if r.method == "POST"] == [
        "/api/v3/core/groups/g1/add_user/",
        "/api/v3/core/groups/g1/remove_user/",
    ]
    await p.set_admin_mfa("nobody@client.example", True)  # no link user: nothing to do
    sim.objects["/api/v3/core/groups/"] = []
    with pytest.raises(ProviderError):
        await p.set_admin_mfa("a@client.example", True)


async def test_a_removed_user_is_deactivated_never_deleted() -> None:
    """P1c-07: the provisioner may change users, not delete them (blueprint)."""
    sim = Simulated()
    sim.objects["/api/v3/core/users/"] = [{"pk": 7, "username": "a@client.example"}]
    p = provider(sim)
    await p.disable_user("a@client.example")
    (patch,) = sim.sent("PATCH", "/api/v3/core/users/7/")
    assert json.loads(patch.content) == {"is_active": False}
    await p.disable_user("nobody@client.example")  # no such user: nothing to do
    assert [r.method for r in sim.requests if r.method in ("PATCH", "DELETE")] == ["PATCH"]


def test_the_public_host_is_ours() -> None:
    assert urlsplit(AUTHENTIK.public_url or "").netloc == PUBLIC_HOST
