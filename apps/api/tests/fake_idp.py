"""Test double for Authentik and the email provider (``SignInLinkProvider``), and for
the tenants' SSO sources and their IdPs (``SsoProvider``, ``SourceAdmin``; P1b-07).

Signs real RS256 access tokens with a throwaway key and serves the matching JWKS
through an httpx MockTransport, so the API's real ``JwksTokenValidator`` checks
them. Link tokens are single-use and expire, like Authentik's flow tokens; the
"outbox" stands in for the email that Authentik would send.

SSO: ``configure_source`` keeps the source as the API specified it; ``start_sso``
returns an IdP URL carrying a state; ``answer`` plays the IdP (the user signs in there
with whatever address and claims the test chooses) and returns the callback parameters;
``finish_sso`` mints the token Authentik would, with ``ask_spore_tenant`` from the
source's tenant and ``ask_spore_sso`` from the IdP's claims. By default it does
**not** apply the source mapping's domain and ``hd`` checks, so the tests prove the
API's own checks; ``mint_tenant`` and ``mint_source`` simulate a misconfigured source.
With ``apply_mapping`` (P1c-02) it runs the source's real generated mapping and the
blueprint's source-flow policy as Authentik would: a refusal is the policy's denial page
(read through ``source_refusal``, as the adapter reads it), and a mapping that raises is
recorded in ``events`` as Authentik records it (``configuration_error``).
"""

from __future__ import annotations

import html
import json
import secrets
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.auth.authentik import source_refusal
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
from app.tenancy.login_policy import SsoKind
from tests.authentik_expressions import run_source_mapping, run_source_policy

ISSUER = "http://authentik-server:9000/application/o/ask-spore/"
# P1b-08: the one TOTP code the fake's authenticator accepts.
TOTP_CODE = "135790"
SETUP_URI = "otpauth://totp/ask.spore:synthetic?secret=SYNTHETICSECRET&issuer=ask.spore"
CLIENT_ID = "ask-spore"
KID = "test-key-1"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_of(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**public, "kid": kid, "use": "sig", "alg": "RS256"}]}


def sign(
    key: rsa.RSAPrivateKey,
    *,
    email: str,
    tenant_id: uuid.UUID | str | None,
    lifetime: int = 3600,
    kid: str = KID,
    **overrides: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": f"sub-{email}",
        "iat": now,
        "exp": now + lifetime,
        "email": email,
    }
    if tenant_id is not None:
        claims[TENANT_CLAIM] = str(tenant_id)
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@dataclass
class _Link:
    email: str
    expires_at: float
    used: bool = False


@dataclass
class FakeSource:
    spec: SourceSpec
    client_secret: str | None


@dataclass
class _Answer:
    email: str
    hd: str | None
    groups: tuple[str, ...]
    email_verified: bool


@dataclass
class FakeSignInLinks:
    """Implements app.auth.provider.SignInLinkProvider in memory."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    link_ttl: float = 900
    users: dict[str, tuple[uuid.UUID, str]] = field(default_factory=dict)
    outbox: list[tuple[str, str]] = field(default_factory=list)  # (email, link token)
    links: dict[str, _Link] = field(default_factory=dict)
    redeemed: list[str] = field(default_factory=list)  # every token the API submitted
    revoked: list[str] = field(default_factory=list)  # tokens revoked, either kind
    # P1b-08: refresh token -> the claims its renewals carry; spent ones are removed.
    refresh_tokens: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Simulate an Authentik that does not honour RFC 7009 revocation of refresh tokens.
    ignore_refresh_revocation: bool = False
    # P1b-08: the admin group the link flow's second factor is bound to, who has enrolled
    # an authenticator, and link flows waiting for a code (resume -> token claims).
    mfa_group: set[str] = field(default_factory=set)
    totp_enrolled: set[str] = field(default_factory=set)
    mfa_pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    mfa_sync: list[tuple[str, bool]] = field(default_factory=list)
    fail_mfa_sync: bool = False
    # P1c-07: users disabled on removal (a re-provisioned user is active again).
    disabled: set[str] = field(default_factory=set)
    fail_disable: bool = False
    # Make the next redeem return a token for a different identity (identity check).
    impersonate: tuple[str, uuid.UUID] | None = None
    # P1b-07: sources by slug, pending IdP round trips, and what each IdP answered.
    sources: dict[str, FakeSource] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    sso_sessions: dict[str, tuple[str, str]] = field(default_factory=dict)  # state
    sso_answers: dict[str, tuple[str, _Answer]] = field(default_factory=dict)  # code
    finished: list[str] = field(default_factory=list)  # slugs finish_sso was called for
    fail_configure: bool = False
    # A misconfigured source: mint another tenant or source into the token.
    mint_tenant: uuid.UUID | None = None
    mint_source: str | None = None
    # P1c-02: run the mapping and the source-flow policy; Authentik's events when they fail.
    apply_mapping: bool = False
    events: list[str] = field(default_factory=list)

    async def send_sign_in_link(self, email: str) -> None:
        if email not in self.users:
            return  # Authentik would find no user; the API checks first anyway
        token = secrets.token_urlsafe(24)
        self.links[token] = _Link(email=email, expires_at=time.monotonic() + self.link_ttl)
        self.outbox.append((email, token))

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens | MfaRequired:
        self.redeemed.append(token)
        link = self.links.get(token)
        if link is None or link.used:
            raise LinkRefused("refused_by_provider")
        if time.monotonic() > link.expires_at:
            raise LinkRefused("refused_by_provider")
        link.used = True
        email, tenant_id = self.impersonate or (link.email, self.users[link.email][0])
        claims = {"email": email, "tenant_id": tenant_id}
        if link.email in self.mfa_group:
            # The validation stage bound to the admin group: the flow waits for a code.
            resume = secrets.token_urlsafe(24)
            self.mfa_pending[resume] = claims
            return self._challenge(link.email, resume, failed=False)
        return self._issue(claims)

    def _challenge(self, email: str, resume: str, *, failed: bool) -> MfaRequired:
        if email in self.totp_enrolled:
            return MfaRequired(stage="validate", resume=resume, failed=failed)
        return MfaRequired(stage="setup", resume=resume, setup_uri=SETUP_URI, failed=failed)

    async def answer_mfa(self, resume: str, code: str) -> IssuedTokens | MfaRequired:
        claims = self.mfa_pending.get(resume)
        if claims is None:
            raise LinkRefused("refused_by_provider")
        if code != TOTP_CODE:
            return self._challenge(claims["email"], resume, failed=True)
        del self.mfa_pending[resume]
        self.totp_enrolled.add(claims["email"])
        return replace(self._issue(claims), mfa=True)

    async def set_admin_mfa(self, email: str, required: bool) -> None:
        if self.fail_mfa_sync:
            raise ProviderError("mfa_group_not_updated")
        self.mfa_sync.append((email, required))
        if required:
            self.mfa_group.add(email)
        else:
            self.mfa_group.discard(email)

    def _issue(self, claims: dict[str, Any], lifetime: int = 3600) -> IssuedTokens:
        # A distinct token per sign-in, as Authentik issues (two in one second differ).
        token = sign(self.key, **claims, lifetime=lifetime, jti=secrets.token_hex(8))
        refresh = secrets.token_urlsafe(32)
        self.refresh_tokens[refresh] = claims
        return IssuedTokens(access_token=token, refresh_token=refresh)

    async def refresh_session(self, refresh_token: str) -> IssuedTokens:
        claims = self.refresh_tokens.pop(refresh_token, None)  # rotated: spent once
        if claims is None:
            raise LinkRefused("refresh_refused")
        return self._issue(claims)

    async def provision_user(self, *, email: str, display_name: str, tenant_id: uuid.UUID) -> None:
        self.users[email] = (tenant_id, display_name)
        self.disabled.discard(email)

    async def disable_user(self, email: str) -> None:
        if self.fail_disable:
            raise ProviderError("user_not_disabled")
        if email in self.users:
            self.disabled.add(email)

    async def revoke_token(self, token: str, kind: TokenKind) -> None:
        self.revoked.append(token)
        if kind == "refresh_token" and not self.ignore_refresh_revocation:
            self.refresh_tokens.pop(token, None)

    async def aclose(self) -> None:
        return None

    # --- SSO sources (P1b-07) -----------------------------------------------------------

    async def configure_source(self, spec: SourceSpec, client_secret: SecretStr | None) -> None:
        if self.fail_configure:
            raise ProviderError("source_not_configured")
        existing = self.sources.get(spec.slug)
        secret = client_secret.get_secret_value() if client_secret is not None else None
        if spec.kind != "saml" and secret is None:
            if existing is None or existing.client_secret is None:
                raise ProviderError("client_secret_required")
            secret = existing.client_secret
        self.sources[spec.slug] = FakeSource(spec=spec, client_secret=secret)

    async def remove_source(self, kind: SsoKind, slug: str) -> None:
        self.sources.pop(slug, None)
        self.removed.append(slug)

    async def start_sso(self, kind: SsoKind, slug: str) -> SsoRedirect:
        if slug not in self.sources:
            raise ProviderError("sso_not_started")
        state, resume = secrets.token_urlsafe(16), secrets.token_urlsafe(24)
        self.sso_sessions[state] = (slug, resume)
        return SsoRedirect(url=f"https://idp.example/{slug}/authorize?state={state}", resume=resume)

    def answer(
        self,
        redirect_url: str,
        *,
        email: str,
        hd: str | None = None,
        groups: tuple[str, ...] = (),
        email_verified: bool = True,
        saml: bool = False,
    ) -> dict[str, str]:
        """The IdP signs the user in; returns the parameters it sends back to us."""
        (state,) = parse_qs(urlsplit(redirect_url).query)["state"]
        code = secrets.token_urlsafe(16)
        self.sso_answers[code] = (state, _Answer(email, hd, groups, email_verified))
        if saml:
            return {"SAMLResponse": code, "RelayState": state}
        return {"code": code, "state": state}

    async def finish_sso(
        self, kind: SsoKind, slug: str, params: Mapping[str, str], resume: str
    ) -> IssuedTokens:
        self.finished.append(slug)
        state = params.get("state") or params.get("RelayState") or ""
        code = params.get("code") or params.get("SAMLResponse") or ""
        if self.sso_sessions.pop(state, None) != (slug, resume):
            raise LinkRefused("refused_by_source")
        found = self.sso_answers.pop(code, None)
        if found is None or found[0] != state:
            raise LinkRefused("refused_by_source")
        answer = found[1]
        source = self.sources[slug].spec
        if self.apply_mapping:
            self._run_mapping(source, answer, saml=kind == "saml")
        admin_groups = source.config.get("admin_group_ids", [])
        return self._issue(
            {
                "email": answer.email,
                "tenant_id": self.mint_tenant or source.tenant_id,
                SSO_CLAIM: {
                    "source": self.mint_source or slug,
                    "hd": answer.hd or "",
                    "email_verified": answer.email_verified,
                    "admin": bool(set(answer.groups) & set(admin_groups)),
                },
            }
        )

    def _run_mapping(self, source: SourceSpec, answer: _Answer, *, saml: bool) -> None:
        if saml:
            variables: dict[str, Any] = {"name_id": SimpleNamespace(text=answer.email)}
        else:
            info: dict[str, Any] = {"email": answer.email, "email_verified": answer.email_verified}
            if answer.hd is not None:
                info["hd"] = answer.hd
            variables = {"info": info, "properties": {"groups": list(answer.groups)}}
        try:
            properties = run_source_mapping(source, **variables)
        except Exception:
            # Authentik: HTTP 500 on the callback, and these two events.
            self.events += ["property_mapping_exception", "configuration_error"]
            raise LinkRefused("refused_by_source") from None
        passing, messages = run_source_policy({"prompt_data": properties})
        if not passing:
            # Authentik's access-denied page (policies/denied.html) with the messages.
            raise source_refusal(f"<p>{html.escape(chr(10).join(messages))}</p>")

    def expire_all(self) -> None:
        for link in self.links.values():
            link.expires_at = 0

    def last_token(self) -> str:
        return self.outbox[-1][1]


def validator_for(
    key: rsa.RSAPrivateKey, jwks_calls: list[str] | None = None
) -> JwksTokenValidator:
    """The API's real validator, with the JWKS served from ``key``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if jwks_calls is not None:
            jwks_calls.append(str(request.url))
        assert str(request.url) == ISSUER + "jwks/"
        return httpx.Response(200, json=jwks_of(key))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JwksTokenValidator(issuer=ISSUER, audience=CLIENT_ID, http=http)
