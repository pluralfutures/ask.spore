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

Tenant SSO sources (P1b-07, desk-checked against the same source, not yet run live):
``configure_source`` creates or updates one source per tenant through the API, with a
property mapping generated for that tenant (``_mapping_expression``): it refuses any
address outside the tenant's verified domains (and, for Google, any ``hd`` outside
them), and sets the ``ask_spore_tenant`` attribute from the source's own tenant and
``ask_spore_sso`` from what the IdP said; the ``ask_spore`` scope mapping copies both
into tokens. ``start_sso`` and ``finish_sso`` relay the browser's round trip to the
IdP: the API calls Authentik's login and callback endpoints itself, presenting our
public host (``public_url``) so that the redirect URIs and SAML destinations Authentik
builds are the ones the client registered, then runs the source's flow and the OIDC
code flow as for links. Authentik's pending session travels in the browser's cookie
(``SsoRedirect.resume``), never in our database.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr

from app.auth.provider import (
    IssuedTokens,
    LinkRefused,
    MfaRequired,
    ProviderError,
    SourceSpec,
    SsoRedirect,
    TokenKind,
)
from app.auth.tokens import SSO_CLAIM, TENANT_CLAIM, JwksTokenValidator
from app.core.config import AuthentikConfig, ConfigError, Settings
from app.tenancy.login_policy import SsoKind

# offline_access (P1b-08): a refresh token, so the session is renewed before it expires.
SCOPES = "openid email profile ask_spore offline_access"
MAX_REDIRECTS = 5

# P1b-07: Authentik's API paths for the two source families, and its OAuth source types.
SOURCES: Final = {"oauth": "/api/v3/sources/oauth/", "saml": "/api/v3/sources/saml/"}
MAPPINGS: Final = {
    "oauth": "/api/v3/propertymappings/source/oauth/",
    "saml": "/api/v3/propertymappings/source/saml/",
}
KEYPAIRS: Final = "/api/v3/crypto/certificatekeypairs/"
PROVIDER_TYPES: Final = {"entra": "entraid", "google": "google", "oidc": "openidconnect"}
# P1b-08: the stages of the second factor Authentik asks tenant admins for.
TOTP_SETUP: Final = "ak-stage-authenticator-totp"
MFA_COMPONENTS: Final = frozenset({"ak-stage-authenticator-validate", TOTP_SETUP})
SAML_EMAIL_NAME_ID: Final = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
SSO_USER_PATH: Final = "ask-spore/sso"
ENTRA_GROUPS_SCOPE: Final = "https://graph.microsoft.com/GroupMember.Read.All"
# P1c-02: the mapping's refusals, as the source flows' policy reports them on Authentik's
# access-denied page ("ask-spore-refusal:<code>"). Only these codes are read from it.
REFUSAL_ATTRIBUTE: Final = "ask_spore_refusal"
REFUSAL_CODES: Final = frozenset({"domain_not_verified", "hd_mismatch", "email_unverified"})
_REFUSAL_MARK: Final = re.compile(r"ask-spore-refusal:([a-z_]{1,32})")
MAX_DENIED_PAGE: Final = 65536

_OAUTH_EMAIL = """\
email = str(info.get("email") or info.get("mail") or info.get("userPrincipalName") or "")
email = email.strip().lower()
hd = str(info.get("hd") or "").strip().lower()
verified = info.get("email_verified", info.get("verified_email", KIND == "entra"))
verified = verified is True or verified == "true"
groups = {str(g) for g in (properties.get("groups") or [])}
"""
_SAML_EMAIL = """\
email = str(name_id.text if name_id is not None else "").strip().lower()
hd = ""
verified = True  # asserted in the IdP's signed response
groups = set()
"""
_MAPPING = """\
# ask.spore source mapping (P1b-07), generated by the API for one tenant: do not edit.
# The tenant is this source's own, never a claim. Addresses outside the tenant's
# verified domains are refused here, and again by the API. A refusal is a return value,
# never an exception (P1c-02): no tenant, and the refusal code, which the source flows'
# policy ask-spore-source-if-sso turns into Authentik's access-denied answer.
TENANT = {tenant}
SOURCE = {slug}
KIND = {kind}
DOMAINS = {domains}
ADMIN_GROUPS = {groups}
{email}
refusal = ""
if email.rpartition("@")[2] not in DOMAINS:
    refusal = "domain_not_verified"
elif KIND == "google" and hd not in DOMAINS:
    refusal = "hd_mismatch"
elif not verified:
    refusal = "email_unverified"
if refusal:
    return {{"attributes": {{"{refusal_attribute}": refusal}}}}
return {{
    "username": SOURCE + "." + email,
    "email": email,
    "path": "{path}",
    "attributes": {{
        "{tenant_claim}": TENANT,
        "{sso_claim}": {{
            "source": SOURCE,
            "hd": hd,
            "email_verified": verified,
            "admin": bool(groups & set(ADMIN_GROUPS)),
        }},
    }},
}}
"""


def _tokens(response: httpx.Response, error_code: str) -> IssuedTokens:
    try:
        body = response.json()
        access_token, refresh_token = body["access_token"], body.get("refresh_token")
    except (ValueError, KeyError, AttributeError):
        raise ProviderError(error_code) from None
    if not isinstance(access_token, str) or not isinstance(refresh_token, str | None):
        raise ProviderError(error_code)
    return IssuedTokens(access_token=access_token, refresh_token=refresh_token)


def source_refusal(page: str) -> LinkRefused:
    """The refusal Authentik answered a source callback with: the mapping's code when its
    access-denied page names one of ours, ``refused_by_source`` otherwise. Nothing else
    is taken from the page."""
    for match in _REFUSAL_MARK.finditer(page[:MAX_DENIED_PAGE]):
        if match[1] in REFUSAL_CODES:
            return LinkRefused(match[1])
    return LinkRefused("refused_by_source")


def family(kind: SsoKind) -> str:
    return "saml" if kind == "saml" else "oauth"


def mapping_expression(spec: SourceSpec) -> str:
    """The source's property mapping. Literals only come from our validated values."""
    groups = spec.config.get("admin_group_ids", []) if spec.kind == "entra" else []
    return _MAPPING.format(
        tenant=json.dumps(str(spec.tenant_id)),
        slug=json.dumps(spec.slug),
        kind=json.dumps(spec.kind),
        domains=json.dumps(sorted(spec.verified_domains)),
        groups=json.dumps(sorted(groups if isinstance(groups, list) else [])),
        email=_SAML_EMAIL if spec.kind == "saml" else _OAUTH_EMAIL,
        path=SSO_USER_PATH,
        tenant_claim=TENANT_CLAIM,
        sso_claim=SSO_CLAIM,
        refusal_attribute=REFUSAL_ATTRIBUTE,
    )


def _encode_resume(cookies: Mapping[str, str], query: str = "") -> str:
    """Authentik's pending session (its cookies) and the flow query, for a cookie."""
    raw = json.dumps({"c": dict(cookies), "q": query}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_resume(resume: str) -> tuple[dict[str, str], str]:
    try:
        value = json.loads(base64.urlsafe_b64decode(resume.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeError):
        raise LinkRefused("bad_resume") from None
    cookies, query = (value.get("c"), value.get("q")) if isinstance(value, dict) else (None, None)
    if (
        not isinstance(cookies, dict)
        or not isinstance(query, str)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in cookies.items())
    ):
        raise LinkRefused("bad_resume")
    return cookies, query


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

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens | MfaRequired:
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
            return await self._after_stage(http, query, done, mfa=False)

    async def _after_stage(
        self, http: httpx.AsyncClient, query: str, challenge: dict[str, Any], *, mfa: bool
    ) -> IssuedTokens | MfaRequired:
        """Where the link flow stands: a second factor to relay (P1b-08), or done."""
        component = challenge.get("component")
        if component in MFA_COMPONENTS:
            setup_uri = challenge.get("config_url") if component == TOTP_SETUP else None
            return MfaRequired(
                stage="setup" if component == TOTP_SETUP else "validate",
                resume=_encode_resume(dict(http.cookies), query),
                setup_uri=setup_uri if isinstance(setup_uri, str) else None,
                failed=bool(challenge.get("response_errors")),
            )
        if component != "xak-flow-redirect":
            raise LinkRefused("refused_by_provider")
        issued = await self._authorize(http)
        return IssuedTokens(
            access_token=issued.access_token, refresh_token=issued.refresh_token, mfa=mfa
        )

    async def answer_mfa(self, resume: str, code: str) -> IssuedTokens | MfaRequired:
        """POST the code to the stage the flow stopped at (validation or TOTP setup)."""
        cookies, query = _decode_resume(resume)
        async with self._client() as http:
            http.cookies.update(cookies)
            current = await self._challenge(http, self._config.sign_in_flow, query)
            component = current.get("component")
            if component not in MFA_COMPONENTS:
                raise LinkRefused("refused_by_provider")
            answered = await self._challenge(
                http, self._config.sign_in_flow, query, {"component": component, "code": code}
            )
            return await self._after_stage(http, query, answered, mfa=True)

    async def set_admin_mfa(self, email: str, required: bool) -> None:
        """Membership of the group the link flow's validation stage is bound to."""
        try:
            user = await self._find("/api/v3/core/users/", username=email)
            if user is None:
                return  # no sign-in-link user in Authentik: nothing to challenge
            group = await self._find("/api/v3/core/groups/", name=self._config.admin_mfa_group)
            if group is None:
                raise ProviderError("mfa_group_missing")
            action = "add_user" if required else "remove_user"
            response = await self._api.post(
                f"/api/v3/core/groups/{group['pk']}/{action}/", json={"pk": user["pk"]}
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("mfa_group_not_updated") from None

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
        except httpx.HTTPError:
            raise ProviderError("token_exchange_failed") from None
        return _tokens(response, "token_exchange_failed")

    async def refresh_session(self, refresh_token: str) -> IssuedTokens:
        """The refresh-token grant (P1b-08). Authentik rotates the refresh token: the one
        presented is revoked and a new one returned (desk-checked, ``TokenView``)."""
        try:
            async with self._client() as http:
                response = await http.post(
                    "/application/o/token/",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self._config.client_id,
                        "client_secret": self._client_secret.get_secret_value(),
                        "scope": SCOPES,
                    },
                )
        except httpx.HTTPError:
            raise ProviderError("authentik_unavailable") from None
        if response.status_code in (400, 401):
            raise LinkRefused("refresh_refused")  # expired, revoked or already used
        if response.is_error:
            raise ProviderError("refresh_failed")
        return _tokens(response, "refresh_failed")

    async def revoke_token(self, token: str, kind: TokenKind) -> None:
        """RFC 7009 revocation at Authentik's OAuth2 provider (P1a-02, desk-checked)."""
        try:
            async with self._client() as http:
                response = await http.post(
                    "/application/o/revoke/",
                    data={
                        "token": token,
                        "token_type_hint": kind,
                        "client_id": self._config.client_id,
                        "client_secret": self._client_secret.get_secret_value(),
                    },
                )
            response.raise_for_status()
        except httpx.HTTPError:
            raise ProviderError("revocation_failed") from None

    # --- tenant SSO sources (P1b-07) ---------------------------------------------------

    def _public_headers(self) -> dict[str, str]:
        public = self._config.public_url
        if public is None:
            raise ProviderError("no_public_url")
        return {"Host": urlsplit(public).netloc, "X-Forwarded-Proto": "https"}

    async def start_sso(self, kind: SsoKind, slug: str) -> SsoRedirect:
        path = f"/source/saml/{slug}/" if kind == "saml" else f"/source/oauth/login/{slug}/"
        async with self._client() as http:
            try:
                response = await http.get(path, headers=self._public_headers())
            except httpx.HTTPError:
                raise ProviderError("authentik_unavailable") from None
            location = response.headers.get("location", "") if response.is_redirect else ""
            if not location.startswith("https://"):
                raise ProviderError("sso_not_started")
            return SsoRedirect(url=location, resume=_encode_resume(dict(http.cookies)))

    async def finish_sso(
        self, kind: SsoKind, slug: str, params: Mapping[str, str], resume: str
    ) -> IssuedTokens:
        cookies, _ = _decode_resume(resume)
        async with self._client() as http:
            http.cookies.update(cookies)
            try:
                if kind == "saml":
                    response = await http.post(
                        f"/source/saml/{slug}/acs/",
                        data=dict(params),
                        headers=self._public_headers(),
                    )
                else:
                    response = await http.get(
                        f"/source/oauth/callback/{slug}/",
                        params=dict(params),
                        headers=self._public_headers(),
                    )
            except httpx.HTTPError:
                raise ProviderError("authentik_unavailable") from None
            # Accepted: a redirect into the source's flow (authentication or enrollment).
            # Refused (bad state, the mapping's domain check, a denied match): an error
            # page or a redirect elsewhere.
            # A refusal by the mapping (P1c-02) is the source flows' policy denying the
            # plan: Authentik's access-denied page, carrying the mapping's code.
            target = urlsplit(response.headers.get("location", "") if response.is_redirect else "")
            if not target.path.startswith("/if/flow/"):
                raise source_refusal("" if response.is_redirect else response.text)
            flow = target.path.removeprefix("/if/flow/").strip("/")
            done = await self._challenge(http, flow, target.query)
            if done.get("component") != "xak-flow-redirect":
                raise source_refusal(str(done.get("error_message") or ""))
            return await self._authorize(http)

    async def _find(self, path: str, **filters: str) -> dict[str, Any] | None:
        response = await self._api.get(path, params=filters)
        response.raise_for_status()
        results: list[dict[str, Any]] = response.json().get("results", [])
        return results[0] if results else None

    async def _flow_pk(self, slug: str) -> str:
        flow = await self._find("/api/v3/flows/instances/", slug=slug)
        if flow is None:
            raise ProviderError("flow_missing")
        return str(flow["pk"])

    async def _upsert_named(self, path: str, body: dict[str, Any]) -> str:
        """Create or update the object named ``body["name"]``; return its pk."""
        found = await self._find(path, name=body["name"])
        if found is None:
            response = await self._api.post(path, json=body)
        else:
            response = await self._api.patch(f"{path}{found['pk']}/", json=body)
        response.raise_for_status()
        return str(response.json()["pk"])

    async def _saml_keypairs(self, spec: SourceSpec) -> tuple[str, str]:
        """(verification, signing): the IdP's certificate, and our own signing key,
        generated in Authentik so the private key never leaves it."""
        if not spec.certificate_pem:
            raise ProviderError("certificate_missing")
        verification = await self._upsert_named(
            KEYPAIRS,
            {
                "name": f"ask-spore-idp-{spec.slug}",
                "certificate_data": spec.certificate_pem,
                "key_data": "",
            },
        )
        signing = await self._find(KEYPAIRS, name=f"ask-spore-sp-{spec.slug}")
        if signing is None:
            response = await self._api.post(
                f"{KEYPAIRS}generate/",
                json={
                    "common_name": f"ask-spore-sp-{spec.slug}",
                    "subject_alt_name": "",
                    "validity_days": 3650,
                },
            )
            response.raise_for_status()
            signing = response.json()
        return verification, str(signing["pk"])

    def _oauth_fields(self, spec: SourceSpec, secret: SecretStr | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "provider_type": PROVIDER_TYPES[spec.kind],
            "consumer_key": spec.config["client_id"],
            "additional_scopes": "",
            "authorization_code_auth_method": "post_body",
        }
        if secret is not None:
            body["consumer_secret"] = secret.get_secret_value()
        if spec.kind == "entra":
            # The client's Entra tenant is pinned in every endpoint and in the issuer, so
            # only its directory can answer for this source.
            tid = spec.config["entra_tenant_id"]
            login = f"https://login.microsoftonline.com/{tid}"
            body.update(
                authorization_url=f"{login}/oauth2/v2.0/authorize",
                access_token_url=f"{login}/oauth2/v2.0/token",
                profile_url="https://graph.microsoft.com/v1.0/me",
                oidc_well_known_url=f"{login}/v2.0/.well-known/openid-configuration",
                oidc_jwks_url=f"{login}/discovery/v2.0/keys",
            )
            if spec.config.get("admin_group_ids"):
                body["additional_scopes"] = ENTRA_GROUPS_SCOPE
        elif spec.kind == "oidc":
            body["oidc_well_known_url"] = (
                f"{spec.config['issuer']}/.well-known/openid-configuration"
            )
        return body

    async def configure_source(self, spec: SourceSpec, client_secret: SecretStr | None) -> None:
        kind_family = family(spec.kind)
        try:
            mapping = await self._upsert_named(
                MAPPINGS[kind_family],
                {"name": f"ask-spore-{spec.slug}", "expression": mapping_expression(spec)},
            )
            body: dict[str, Any] = {
                "name": spec.name,
                "slug": spec.slug,
                "enabled": True,
                "authentication_flow": await self._flow_pk(self._config.source_authentication_flow),
                "enrollment_flow": await self._flow_pk(self._config.source_enrollment_flow),
                "user_matching_mode": "identifier",
                "user_path_template": SSO_USER_PATH,
                "user_property_mappings": [mapping],
                "policy_engine_mode": "any",
            }
            if kind_family == "saml":
                verification, signing = await self._saml_keypairs(spec)
                body.update(
                    sso_url=spec.config["sso_url"],
                    binding_type="redirect",
                    name_id_policy=SAML_EMAIL_NAME_ID,
                    verification_kp=verification,
                    signing_kp=signing,
                    pre_authentication_flow=await self._flow_pk(
                        self._config.source_pre_authentication_flow
                    ),
                    allow_idp_initiated=False,
                    signed_assertion=True,
                )
            else:
                body.update(self._oauth_fields(spec, client_secret))
            # A kind change can move the source between families: one source per tenant.
            other = "oauth" if kind_family == "saml" else "saml"
            if await self._find(SOURCES[other], slug=spec.slug) is not None:
                (await self._api.delete(f"{SOURCES[other]}{spec.slug}/")).raise_for_status()
            existing = await self._find(SOURCES[kind_family], slug=spec.slug)
            if existing is None:
                if kind_family == "oauth" and client_secret is None:
                    raise ProviderError("client_secret_required")
                response = await self._api.post(SOURCES[kind_family], json=body)
            else:
                response = await self._api.patch(f"{SOURCES[kind_family]}{spec.slug}/", json=body)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("source_not_configured") from None

    async def remove_source(self, kind: SsoKind, slug: str) -> None:
        kind_family = family(kind)
        try:
            response = await self._api.delete(f"{SOURCES[kind_family]}{slug}/")
            if response.status_code != 404:
                response.raise_for_status()
            names = [(MAPPINGS[kind_family], f"ask-spore-{slug}")]
            if kind_family == "saml":
                names += [(KEYPAIRS, f"ask-spore-idp-{slug}"), (KEYPAIRS, f"ask-spore-sp-{slug}")]
            for path, name in names:
                found = await self._find(path, name=name)
                if found is not None:
                    (await self._api.delete(f"{path}{found['pk']}/")).raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("source_not_removed") from None

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

    async def disable_user(self, email: str) -> None:
        """``is_active`` off (the provisioner's role may change users, not delete them,
        blueprint ``ask-spore-provisioner``); the operator deletes the account in
        Authentik's admin interface.

        Every account of the address is ours to deactivate: the sign-in-link account
        (username = email) and each one an SSO source created (username
        ``<source slug>.<email>``, the generated mapping), so a user who signed in by
        SSO is deactivated too (Phase 1c release F5)."""
        try:
            response = await self._api.get("/api/v3/core/users/", params={"email": email})
            response.raise_for_status()
            results: list[dict[str, Any]] = response.json().get("results", [])
            for user in results:
                if not _is_account_of(user.get("username", ""), email):
                    continue
                patched = await self._api.patch(
                    f"/api/v3/core/users/{user['pk']}/", json={"is_active": False}
                )
                patched.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError):
            raise ProviderError("user_not_disabled") from None


def _is_account_of(username: str, email: str) -> bool:
    """The address's sign-in-link account or an account an SSO source created for it."""
    return (
        username == email
        or re.fullmatch(r"sso-[a-z0-9-]+\." + re.escape(email), username) is not None
    )


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
