"""OIDC access-token validation against the issuer's JWKS (P1a-02).

Every authenticated request carries an Authentik access token (a JWT), in the
``askspore_session`` cookie set at sign-in or an ``Authorization: Bearer`` header.
``JwksTokenValidator`` checks the signature against the issuer's published keys
(asymmetric algorithms only), the issuer, the audience (our client ID), expiry and
issue time, and requires the claims the API maps to a user: ``email`` and
``ask_spore_tenant``, the tenant UUID that Authentik copies from the user's
attributes when the user is provisioned (``app.auth.provider``). The user row is
then looked up by that tenant and email (``app.tenancy.context.resolve_user``).

No token, claim value or email is ever logged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

import httpx
import jwt

TENANT_CLAIM = "ask_spore_tenant"
# P1b-07: set on users that arrive from a tenant's SSO source, by that source's property
# mapping (app.auth.authentik): which source, and what the IdP said about the user.
SSO_CLAIM = "ask_spore_sso"
MAX_SOURCE_SLUG_LENGTH = 72
MAX_DOMAIN_LENGTH = 253
# Authentik signs with the provider's certificate (RS256 or ES256). Symmetric
# algorithms (HS256 with the client secret) and "none" are refused.
ALGORITHMS = ("RS256", "ES256")
MAX_EMAIL_LENGTH = 320
MAX_TOKEN_LENGTH = 8192


class InvalidToken(Exception):
    """The token is not acceptable; ``error_code`` says why (for metadata-only logs)."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class SsoClaims:
    """What a tenant's source recorded at its last sign-in (P1b-07)."""

    source: str  # the Authentik source's slug
    hd: str | None  # Google Workspace hosted domain, as the IdP sent it
    email_verified: bool
    admin: bool  # in one of the source's admin groups (Entra group mapping)


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str
    tenant_id: UUID
    expires_at: datetime
    sso: SsoClaims | None = None


def sso_from_claims(claims: dict[str, Any]) -> SsoClaims | None:
    """The SSO claim if it is well formed, else None (a sign-in link user has none)."""
    raw = claims.get(SSO_CLAIM)
    if not isinstance(raw, dict):
        return None
    source, hd = raw.get("source"), raw.get("hd") or None
    if not isinstance(source, str) or not 0 < len(source) <= MAX_SOURCE_SLUG_LENGTH:
        return None
    if hd is not None and (not isinstance(hd, str) or len(hd) > MAX_DOMAIN_LENGTH):
        return None
    return SsoClaims(
        source=source,
        hd=hd.strip().lower() if hd else None,
        email_verified=raw.get("email_verified") is True,
        admin=raw.get("admin") is True,
    )


class TokenValidator(Protocol):
    async def validate(self, token: str) -> Identity: ...


def identity_from_claims(claims: dict[str, Any]) -> Identity:
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > MAX_EMAIL_LENGTH:
        raise InvalidToken("no_email")
    try:
        tenant_id = UUID(str(claims.get(TENANT_CLAIM)))
    except ValueError:
        raise InvalidToken("no_tenant") from None
    return Identity(
        subject=str(claims["sub"]),
        email=email.strip().lower(),
        tenant_id=tenant_id,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
        sso=sso_from_claims(claims),
    )


class JwksTokenValidator:
    """Validates tokens of one issuer and audience; caches the issuer's JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        http: httpx.AsyncClient,
        cache_seconds: float = 300,
        leeway_seconds: int = 30,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_url = issuer.rstrip("/") + "/jwks/"  # Authentik: <issuer>jwks/
        self._http = http
        self._cache_seconds = cache_seconds
        self._leeway = leeway_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0

    async def _refresh(self) -> None:
        try:
            response = await self._http.get(self._jwks_url)
            response.raise_for_status()
            keys = jwt.PyJWKSet.from_dict(response.json()).keys
        except (httpx.HTTPError, ValueError, jwt.PyJWTError):
            raise InvalidToken("jwks_unavailable") from None
        self._keys = {key.key_id: key for key in keys if key.key_id}
        self._fetched_at = time.monotonic()

    async def _key(self, kid: str) -> jwt.PyJWK:
        stale = time.monotonic() - self._fetched_at > self._cache_seconds
        # An unknown kid triggers at most one refresh per cache period (key rotation).
        if stale or (kid not in self._keys and time.monotonic() - self._fetched_at > 10):
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise InvalidToken("unknown_key")
        return key

    async def validate(self, token: str) -> Identity:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            raise InvalidToken("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise InvalidToken("malformed") from None
        algorithm, kid = header.get("alg"), header.get("kid")
        if algorithm not in ALGORITHMS or not isinstance(kid, str):
            raise InvalidToken("bad_algorithm")
        key = await self._key(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise InvalidToken("expired") from None
        except jwt.PyJWTError:
            raise InvalidToken("invalid") from None
        return identity_from_claims(claims)
