"""Test double for Authentik and the email provider (``SignInLinkProvider``).

Signs real RS256 access tokens with a throwaway key and serves the matching JWKS
through an httpx MockTransport, so the API's real ``JwksTokenValidator`` checks
them. Link tokens are single-use and expire, like Authentik's flow tokens; the
"outbox" stands in for the email that Authentik would send.
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.provider import IssuedTokens, LinkRefused
from app.auth.tokens import TENANT_CLAIM, JwksTokenValidator

ISSUER = "http://authentik-server:9000/application/o/ask-spore/"
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
class FakeSignInLinks:
    """Implements app.auth.provider.SignInLinkProvider in memory."""

    key: rsa.RSAPrivateKey = field(default_factory=new_key)
    link_ttl: float = 900
    users: dict[str, tuple[uuid.UUID, str]] = field(default_factory=dict)
    outbox: list[tuple[str, str]] = field(default_factory=list)  # (email, link token)
    links: dict[str, _Link] = field(default_factory=dict)
    redeemed: list[str] = field(default_factory=list)  # every token the API submitted
    # Make the next redeem return a token for a different identity (identity check).
    impersonate: tuple[str, uuid.UUID] | None = None

    async def send_sign_in_link(self, email: str) -> None:
        if email not in self.users:
            return  # Authentik would find no user; the API checks first anyway
        token = secrets.token_urlsafe(24)
        self.links[token] = _Link(email=email, expires_at=time.monotonic() + self.link_ttl)
        self.outbox.append((email, token))

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens:
        self.redeemed.append(token)
        link = self.links.get(token)
        if link is None or link.used:
            raise LinkRefused("refused_by_provider")
        if time.monotonic() > link.expires_at:
            raise LinkRefused("refused_by_provider")
        link.used = True
        email, tenant_id = self.impersonate or (link.email, self.users[link.email][0])
        return IssuedTokens(access_token=sign(self.key, email=email, tenant_id=tenant_id))

    async def provision_user(self, *, email: str, display_name: str, tenant_id: uuid.UUID) -> None:
        self.users[email] = (tenant_id, display_name)

    async def aclose(self) -> None:
        return None

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
