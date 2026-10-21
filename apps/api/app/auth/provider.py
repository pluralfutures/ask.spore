"""The identity provider behind sign-in links, as the API sees it (P1a-02).

Authentik and the transactional email provider are external services. The API
talks to them only through ``SignInLinkProvider``: ``app.auth.authentik`` is the
real implementation (Authentik's flow executor and OIDC endpoints; Authentik's
email stage sends the link over the configured SMTP relay, Scaleway Transactional
Email), and the tests use an in-memory fake (``tests/fake_idp.py``).

The controls the compliance guide requires of sign-in links do not depend on the
provider: browser binding, one POST per link, expiry and no enumeration are enforced
by ``app.auth.links`` before the provider is called.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import SecretStr

from app.tenancy.login_policy import SsoKind


class LinkRefused(Exception):
    """The provider would not redeem the link token (unknown, expired or already used)."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class ProviderError(Exception):
    """The provider could not be reached or answered something unexpected."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


# RFC 7009 token_type_hint values.
TokenKind = Literal["access_token", "refresh_token"]


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    # P1b-08: with the ``offline_access`` scope, to renew the session before the access
    # token (8 hours) expires. Kept in an HttpOnly cookie for the refresh route only.
    refresh_token: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    """One tenant's SSO source as the API asks Authentik to configure it (P1b-07).

    Non-secret: the client secret travels separately and is stored in Authentik only.
    ``tenant_id`` and ``verified_domains`` are the tenant's own, from our database:
    the source's property mapping stamps ``tenant_id`` on every user it brings in and
    refuses any address outside ``verified_domains``.
    """

    tenant_id: UUID
    slug: str
    name: str
    kind: SsoKind
    verified_domains: tuple[str, ...]
    config: Mapping[str, str | list[str]]
    certificate_pem: str | None = None  # SAML: the IdP's public signing certificate


@dataclass(frozen=True)
class SsoRedirect:
    """Where the browser goes to sign in at the IdP, and what the callback needs back."""

    url: str
    resume: str  # opaque provider state, kept in the starting browser's cookie only


class SsoProvider(Protocol):
    async def start_sso(self, kind: SsoKind, slug: str) -> SsoRedirect:
        """Begin a sign-in through source ``slug``; the browser is sent to ``url``."""
        ...

    async def finish_sso(
        self, kind: SsoKind, slug: str, params: Mapping[str, str], resume: str
    ) -> IssuedTokens:
        """Hand the IdP's answer (``params``) to the source; raise LinkRefused if refused."""
        ...


class SourceAdmin(Protocol):
    async def configure_source(self, spec: SourceSpec, client_secret: SecretStr | None) -> None:
        """Create or update the tenant's source; ``None`` keeps the stored secret."""
        ...

    async def remove_source(self, kind: SsoKind, slug: str) -> None:
        """Delete the source and everything created for it."""
        ...


class SignInLinkProvider(Protocol):
    async def send_sign_in_link(self, email: str) -> None:
        """Email ``email`` a single-use link to the landing page (token in the fragment)."""
        ...

    async def redeem_sign_in_link(self, token: str) -> IssuedTokens:
        """Complete the sign-in flow with ``token``; raise LinkRefused if it is not valid."""
        ...

    async def provision_user(self, *, email: str, display_name: str, tenant_id: UUID) -> None:
        """Create or update the provider's user, carrying ``tenant_id`` into its tokens."""
        ...

    async def refresh_session(self, refresh_token: str) -> IssuedTokens:
        """New tokens for a refresh token (rotated: the old one is spent); LinkRefused if
        the provider will not (P1b-08)."""
        ...

    async def revoke_token(self, token: str, kind: TokenKind) -> None:
        """Revoke a token at the provider on sign-out (P1a-02, P1b-08; best effort)."""
        ...

    async def aclose(self) -> None: ...
