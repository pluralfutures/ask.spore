"""Authentik implementation of ``SignInLinkProvider`` (P1a-02).

Desk-checked against the authentik ``version-2026.8`` source (the pinned tag is in
``infra/authentik/VERSION``); not yet run against a live instance (findings A7).
The API is the only Authentik client for sign-in links: the browser never holds an
Authentik session. Each call runs in a fresh cookie jar on the Compose network.

Sending (``send_sign_in_link``): the API runs the ``sign_in_flow`` (identification
stage by email, then the email stage) through the flow executor API. Authentik's
email stage creates a flow token and mails it over the configured SMTP relay using
our template (``infra/authentik/templates``), which puts the token in the fragment of
our landing page, never in a URL a mail scanner could open to spend it.

Redeeming (``redeem_sign_in_link``): restoring a plan from a flow token puts
Authentik's own one-time consent stage in front (``EmailTokenRevocationConsentStageView``,
which deletes the token only when its challenge is answered), then the email and
user-login stages finish. The API then runs the OIDC authorization-code flow with PKCE
in the same session, reads the code from the redirect itself and exchanges it for
tokens. Authentik does not bind a flow token to the browser that requested it; the
binding, single-POST and expiry controls are ours (``app.auth.links``).

Provisioning (``provision_user``): the core users API, with the tenant UUID in the
user's attributes; the ``ask_spore`` scope mapping copies it into tokens as the
``ask_spore_tenant`` claim.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr

from app.auth.provider import IssuedTokens, LinkRefused, ProviderError
from app.auth.tokens import TENANT_CLAIM, JwksTokenValidator
from app.core.config import AuthentikConfig, ConfigError, Settings

SCOPES = "openid email profile ask_spore"
MAX_REDIRECTS = 5


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class AuthentikProvider:
    def __init__(
        self,
        config: AuthentikConfig,
        *,
        client_secret: SecretStr,
        api_token: SecretStr,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client_secret = client_secret
        self._api_token = api_token
        self._transport = transport
        self._api = self._client(
            headers={"Authorization": f"Bearer {api_token.get_secret_value()}"}
        )

    def _client(self, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            transport=self._transport,
            headers=headers,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._api.aclose()

    # --- flow executor ------------------------------------------------------------------

    async def _challenge(
        self,
        http: httpx.AsyncClient,
        flow: str,
        query: str,
        answer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET (or POST ``answer`` to) the flow executor; follows its own redirects."""
        url = f"/api/v3/flows/executor/{flow}/"
        params = {"query": query}
        try:
            if answer is None:
                response = await http.get(url, params=params, follow_redirects=True)
            else:
                response = await http.post(url, params=params, json=answer, follow_redirects=True)
            response.raise_for_status()
            challenge: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError):
            raise ProviderError("authentik_unavailable") from None
        return challenge

    async def send_sign_in_link(self, email: str) -> None:
        flow = self._config.sign_in_flow
        async with self._client() as http:
            first = await self._challenge(http, flow, "")
            if first.get("component") != "ak-stage-identification":
                raise ProviderError("unexpected_challenge")
            sent = await self._challenge(
                http, flow, "", {"component": "ak-stage-identification", "uid_field": email}
            )
            if sent.get("component") != "ak-stage-email":
                raise ProviderError("link_not_sent")

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens:
        flow = self._config.sign_in_flow
        query = urlencode({"flow_token": token})
        async with self._client() as http:
            consent = await self._challenge(http, flow, query)
            if consent.get("component") != "ak-stage-consent" or not consent.get("token"):
                # Unknown, expired or already used: Authentik answers access denied.
                raise LinkRefused("refused_by_provider")
            done = await self._challenge(
                http, flow, query, {"component": "ak-stage-consent", "token": consent["token"]}
            )
            if done.get("component") != "xak-flow-redirect":
                raise LinkRefused("refused_by_provider")
            return await self._authorize(http)

    # --- OIDC authorization code with PKCE, in the session the flow just signed in ----

    async def _authorize(self, http: httpx.AsyncClient) -> IssuedTokens:
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(16)
        location = "/application/o/authorize/?" + urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        for _ in range(MAX_REDIRECTS):
            if location.startswith(self._config.redirect_uri):
                params = parse_qs(urlsplit(location).query)
                if params.get("state") != [state] or not params.get("code"):
                    raise ProviderError("bad_authorization_response")
                return await self._exchange(http, params["code"][0], verifier)
            target = urlsplit(location)
            if target.path.startswith("/if/flow/"):
                # The provider's authorization flow (implicit consent), via the executor API.
                slug = target.path.removeprefix("/if/flow/").strip("/")
                redirect = await self._challenge(http, slug, target.query)
                if redirect.get("component") != "xak-flow-redirect":
                    raise ProviderError("authorization_not_granted")
                location = str(redirect.get("to", ""))
                continue
            try:
                response = await http.get(location)
            except httpx.HTTPError:
                raise ProviderError("authentik_unavailable") from None
            if not response.is_redirect:
                raise ProviderError("authorization_not_granted")
            location = response.headers["location"]
        raise ProviderError("too_many_redirects")

    async def _exchange(self, http: httpx.AsyncClient, code: str, verifier: str) -> IssuedTokens:
        try:
            response = await http.post(
                "/application/o/token/",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._config.redirect_uri,
                    "client_id": self._config.client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                    "code_verifier": verifier,
                },
            )
            response.raise_for_status()
            access_token = response.json()["access_token"]
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("token_exchange_failed") from None
        if not isinstance(access_token, str):
            raise ProviderError("token_exchange_failed")
        return IssuedTokens(access_token=access_token)

    async def revoke_token(self, access_token: str) -> None:
        """RFC 7009 revocation at Authentik's OAuth2 provider (P1a-02, desk-checked)."""
        try:
            async with self._client() as http:
                response = await http.post(
                    "/application/o/revoke/",
                    data={
                        "token": access_token,
                        "token_type_hint": "access_token",
                        "client_id": self._config.client_id,
                        "client_secret": self._client_secret.get_secret_value(),
                    },
                )
            response.raise_for_status()
        except httpx.HTTPError:
            raise ProviderError("revocation_failed") from None

    # --- provisioning ---------------------------------------------------------------

    async def provision_user(self, *, email: str, display_name: str, tenant_id: UUID) -> None:
        body = {
            "username": email,
            "email": email,
            "name": display_name,
            "is_active": True,
            "path": "ask-spore",
            "attributes": {TENANT_CLAIM: str(tenant_id)},
        }
        try:
            found = await self._api.get("/api/v3/core/users/", params={"username": email})
            found.raise_for_status()
            results = found.json().get("results", [])
            if results:
                pk = results[0]["pk"]
                attributes = {**results[0].get("attributes", {}), TENANT_CLAIM: str(tenant_id)}
                response = await self._api.patch(
                    f"/api/v3/core/users/{pk}/", json={**body, "attributes": attributes}
                )
            else:
                response = await self._api.post("/api/v3/core/users/", json=body)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("provisioning_failed") from None


def oidc_services(
    settings: Settings, http: httpx.AsyncClient
) -> tuple[JwksTokenValidator, AuthentikProvider]:
    """The token validator and sign-in provider for ``[auth] mode = "oidc"``."""
    authentik = settings.models.auth.authentik
    client_secret = settings.secrets.authentik_client_secret
    api_token = settings.secrets.authentik_api_token
    if authentik is None or client_secret is None or api_token is None:
        raise ConfigError(["auth.mode is 'oidc' but Authentik is not configured"])
    validator = JwksTokenValidator(issuer=authentik.issuer, audience=authentik.client_id, http=http)
    provider = AuthentikProvider(authentik, client_secret=client_secret, api_token=api_token)
    return validator, provider
